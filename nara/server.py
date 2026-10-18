import copy
import hashlib
import hmac
import ipaddress
import json
import mimetypes
import re
import secrets
import ssl
import subprocess
import tempfile
import threading
import time
import uuid
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
from .http import BoundedHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from . import __version__, options
from .config import COLLECTIONS, build_config, client_config, eligible, host, normalize_dns_record, require, validate
from . import native, warp, security, clients, notifications, accounts, api_keys, rest, traffic, portable, client_links, migration
from .updates import UpdateChecker
from .runtime import Metrics, atomic_write
from .store import password_matches
from .install_config import normalize_web_path


def run_openssl(arguments, timeout=20):
    try:
        return subprocess.run(["openssl"] + arguments, capture_output=True, timeout=timeout)
    except FileNotFoundError:
        raise ValueError("OpenSSL executable was not found. Install OpenSSL and check the service PATH.")
    except OSError:
        raise ValueError("OpenSSL could not be started. Check executable permissions and the service PATH.")


def certificate_info(profile):
    host(profile["server_name"])
    with tempfile.TemporaryDirectory() as temp:
        cert, key = Path(temp) / "cert.pem", Path(temp) / "key.pem"
        atomic_write(cert, profile["certificate"])
        atomic_write(key, profile["private_key"])
        try:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(str(cert), str(key))
            decoded = ssl._ssl._test_decode_cert(str(cert))
        except (ssl.SSLError, ssl.CertificateError, ValueError, KeyError):
            raise ValueError("Certificate and private key are invalid or do not match")
        # ssl.match_hostname was removed in Python 3.12. Use the existing
        # OpenSSL dependency to check DNS names and IP SANs without a network request.
        try:
            ipaddress.ip_address(profile["server_name"])
            check_option = "-checkip"
        except ValueError:
            check_option = "-checkhost"
        checked = run_openssl(["x509", "-in", str(cert), "-noout", check_option, profile["server_name"]])
        # OpenSSL 1.1.1/3.0 can exit zero even on mismatch. Require the positive
        # check message too; "does NOT match" must never be accepted.
        require(checked.returncode == 0 and b" does match certificate" in checked.stdout,
                "Certificate does not match the configured server domain or IP address")
        expires = ssl.cert_time_to_seconds(decoded["notAfter"])
        require(expires > time.time(), "Certificate has expired")
        der = ssl.PEM_cert_to_DER_cert(profile["certificate"])
        return {"expires": expires, "fingerprint": hashlib.sha256(der).hexdigest()}


def self_signed(data):
    server_name = data.get("server_name", "")
    host(server_name)
    days = int(data.get("days", 365))
    require(1 <= days <= 3650, "Certificate validity must be between 1 and 3650 days")
    try:
        ipaddress.ip_address(server_name)
        san = "IP:" + server_name
    except ValueError:
        san = "DNS:" + server_name
    with tempfile.TemporaryDirectory() as temp:
        cert, key = Path(temp) / "cert.pem", Path(temp) / "key.pem"
        result = run_openssl(["req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256",
                                 "-nodes", "-days", str(days), "-subj", "/CN=" + server_name,
                                 "-addext", "subjectAltName=" + san, "-keyout", str(key), "-out", str(cert)],
                             timeout=20)
        require(result.returncode == 0, "Certificate generation failed; OpenSSL 1.1.1 or later is required")
        return {"id": uuid.uuid4().hex, "name": data.get("name") or server_name, "server_name": server_name,
                "kind": "self_signed", "certificate": cert.read_text(), "private_key": key.read_text()}


def make_handler(store, runtime, web_dir, secure_cookie=False, web_path="", role="panel", access=None):
    from .access import Access
    access = access or Access(store.directory, {"NARA_WEB_PATH": web_path})
    base_path = normalize_web_path(web_path)
    cookie_path = base_path + "/"
    metrics = Metrics()
    login_attempts = {}
    throttle_lock = threading.Lock()
    updates = UpdateChecker(store)
    warp_lock = threading.Lock()
    account_lock = threading.RLock()
    api_limits, api_limit_lock = {}, threading.Lock()
    migrations = migration.Manager(store, runtime) if role == "panel" else None

    class Handler(BaseHTTPRequestHandler):
        server_version = "NARA"

        def log_message(self, *args):
            pass  # Paths can contain subscription bearer tokens.

        def route_path(self):
            path = urlsplit(self.path).path
            if base_path:
                if not path.startswith(base_path + "/"):
                    return None
                return path[len(base_path):]
            return path

        def send(self, status, data, content_type="application/json; charset=utf-8", headers=None):
            if isinstance(data, (dict, list)):
                data = json.dumps(data, ensure_ascii=False).encode()
            elif isinstance(data, str):
                data = data.encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(data)

        def json_body(self):
            require(self.headers.get("Content-Type", "").split(";")[0] == "application/json", "Request must use application/json")
            require(not self.headers.get("Transfer-Encoding") and len(self.headers.get_all("Content-Length", [])) == 1, "Use one Content-Length without Transfer-Encoding")
            length = int(self.headers.get("Content-Length", "0"))
            require(0 < length <= (16*1024*1024 if self.route_path() in ('/api/backup/preview', '/api/backup/restore') else 1_048_576), "Request is too large or empty")
            raw = self.rfile.read(length)
            require(len(raw) == length, "Incomplete request body")
            def invalid_constant(value):
                raise ValueError("JSON numbers must be finite")
            data = json.loads(raw, parse_constant=invalid_constant)
            require(isinstance(data, dict), "Invalid request structure")
            return data

        def cookie_token(self):
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
                return cookie["nara_session"].value if "nara_session" in cookie else ""
            except Exception:
                return ""

        def auth(self, mutation=False):
            session = store.session(self.cookie_token())
            if not session:
                self.send(401, {"error": "Please sign in first"})
                return None
            if mutation and not hmac.compare_digest(self.headers.get("X-CSRF-Token", "").encode(), session["csrf"].encode()):
                self.send(403, {"error": "Invalid security token; refresh the page"})
                return None
            return session

        def same_origin(self):
            origin = self.headers.get("Origin")
            require(self.headers.get("Sec-Fetch-Site") != "cross-site", "Request origin is not allowed")
            if origin:
                parsed = urlsplit(origin)
                require(parsed.scheme in ("http", "https") and parsed.netloc == self.headers.get("Host") and
                        not (parsed.username or parsed.password or parsed.query or parsed.fragment) and parsed.path in ("", "/") and
                        (not secure_cookie or parsed.scheme == "https"), "Request origin is not allowed")

        def do_GET(self):
            try:
                self.get()
            except (ValueError, KeyError, TypeError) as exc:
                self.send(400, {"error": str(exc) if isinstance(exc, ValueError) else "Invalid data structure"})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                self.send(500, {"error": "Operation failed; check service status"})

        def rest_api(self, method, path):
            self._secure_cookie, self._base_path = secure_cookie, base_path
            return rest.API(self, store, runtime, access, updates, metrics, api_limits, api_limit_lock).handle(method, path)

        def do_PATCH(self):
            try:
                self.same_origin()
                path = self.route_path()
                if role != 'panel' or not path or not path.startswith('/api/v1/'):
                    return self.send(404, {'error': 'Not found'})
                return self.rest_api(self.command, path[len('/api/v1/'):])
            except ValueError as exc:
                return self.send(400, {'error': str(exc)})

        do_DELETE = do_PATCH
        do_PUT = do_PATCH

        def get(self):
            if base_path and urlsplit(self.path).path == base_path:
                return self.send(308, "", headers={"Location": base_path + "/"})
            path = self.route_path()
            if path is None:
                return self.send(404, {"error": "Not found"})
            if path == "/api/health":
                return self.send(200, {"ok": True, "version": __version__})
            if role == "subscription" and path.startswith("/") and path.count("/") == 1 and len(path) > 1:
                token = path[1:]
                if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
                    return self.send(404, {"error": "Subscription is unavailable"})
                state = store.get("state")
                client = next((c for c in state["clients"] if hmac.compare_digest(c["token"], token)), None)
                active = runtime.active
                live_client = next((c for c in active["clients"] if client and c["id"] == client["id"]), None) if active else None
                totals = store.totals() if client and live_client else {}
                if not client or not live_client or not eligible(client, totals):
                    return self.send(404, {"error": "Subscription is unavailable"})
                result = client_config(active, live_client, totals)
                usage = totals.get(client["id"], {})
                from .config import expiry
                info = "upload={}; download={}; total={}; expire={}".format(usage.get("upload", 0), usage.get("download", 0), live_client["quota_bytes"], int(expiry(live_client.get("expires_at"))))
                return self.send(200, result, headers={"Subscription-Userinfo": info, "Profile-Update-Interval": "6"})
            if role == "subscription":
                return self.send(404, {"error": "Not found"})
            if path.startswith('/api/v1/'):
                return self.rest_api('GET', path[len('/api/v1/'):])
            if path.startswith("/api/"):
                session = self.auth()
                if not session:
                    return
                if path == "/api/session":
                    return self.send(200, {"csrf": session["csrf"], **security.public_admin(store.get("admin"))})
                if path == "/api/access":
                    return self.send(200, access.info())
                if path.startswith("/api/access-status/"):
                    return self.send(200, access.status(path.rsplit("/", 1)[-1]))
                if path == '/api/admin':
                    return self.send(200, {**security.public_admin(store.get('admin')), 'avatars': security.AVATARS})
                if path == '/api/openapi':
                    return self.send(200, rest.openapi())
                if path == '/api/api-keys':
                    return self.send(200, {'keys': api_keys.listing(store), 'scopes': api_keys.SCOPES})
                if path == '/api/telegram':
                    return self.send(200, {**notifications.public_settings(store), 'event_labels': {k: v[1] for k, v in notifications.EVENTS.items() if k != 'test'}})
                if path == "/api/options":
                    return self.send(200, options.schema())
                if path == "/api/core-schema":
                    return self.send(200, native.payload())
                if path == "/api/state":
                    state = copy.deepcopy(store.get("state"))
                    for profile in state["tls"]:
                        profile.pop("private_key", None)
                    return self.send(200, native.redact(state))
                if path == '/api/migration':
                    return self.send(200, migrations.status())
                if path == '/api/traffic':
                    query=parse_qs(urlsplit(self.path).query)
                    return self.send(200, traffic.history(store, query.get('kind',['client'])[0], query.get('id',[''])[0], query.get('range',['24h'])[0]))
                if path.startswith('/api/client-links/'):
                    model=store.get('state')
                    client=next((x for x in model['clients'] if x['id']==path.rsplit('/',1)[-1]),None)
                    require(client is not None,'Client no longer exists')
                    return self.send(200, {'links':client_links.links(model,client,store.totals())})
                if path == "/api/dashboard":
                    with runtime.lock:
                        status = runtime.status()
                        return self.send(200, {"metrics": metrics.read(store.directory), "core": status,
                                               "panel_version": __version__, "updates": updates.status(status["version"]),
                                               "totals": store.totals(), "traffic": traffic.summary(store), "events": store.events()})
                if path == "/api/config":
                    return self.send(200, build_config(store.get("state"), store.totals(), runtime.run_dir, runtime.stats_port))
                if path.startswith("/api/export/"):
                    state = runtime.active
                    require(state is not None, "Apply your changes first")
                    client = next((c for c in state["clients"] if c["id"] == path.split("/")[-1]), None)
                    require(client is not None, "Apply the client changes first")
                    return self.send(200, client_config(state, client, store.totals()))
                return self.send(404, {"error": "Not found"})
            assets = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/style.css": "style.css", "/favicon.svg": "favicon.svg",
                      "/vendor/qrcodegen.js": "vendor/qrcodegen.js", "/subscription-qr.js": "subscription-qr.js", "/options.js": "options.js"}
            assets["/core-editor.js"] = "core-editor.js"
            assets["/dns-presets.js"] = "dns-presets.js"
            assets["/routing.js"] = "routing.js"
            assets["/dns-rules.js"] = "dns-rules.js"
            for script in ("account.js", "integrations.js", "clients.js", "insights.js", "transfer.js"):
                assets["/" + script] = script
            if path in assets:
                file = web_dir / assets[path]
                return self.send(200, file.read_bytes(), mimetypes.guess_type(str(file))[0] or "text/plain")
            self.send(404, {"error": "Not found"})

        def do_POST(self):
            if role != "panel":
                return self.send(404, {"error": "Not found"})
            try:
                self.same_origin()
                self.post()
            except (ValueError, KeyError, TypeError, OverflowError) as exc:
                if self.route_path() in ("/api/save", "/api/settings", "/api/core-options", "/api/clients-bulk-create", "/api/clients-bulk-action"):
                    notifications.emit(store, "apply_failed", "A settings change was rejected. Previous working settings were retained.", "apply-failed", 300)
                self.send(400, {"error": str(exc) if isinstance(exc, ValueError) else "Invalid data structure"})
            except subprocess.TimeoutExpired:
                self.send(400, {"error": "Operation timed out"})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                self.send(500, {"error": "Operation failed; check settings and dependencies"})

        def post(self):
            path = self.route_path()
            if path is None:
                return self.send(404, {"error": "Not found"})
            if path.startswith('/api/v1/'):
                return self.rest_api('POST', path[len('/api/v1/'):])
            if path == "/api/login":
                data = self.json_body()
                peer = self.client_address[0]
                now = time.time()
                with throttle_lock:
                    # A reverse proxy may share one peer; this intentionally caps total attempts too.
                    for address in list(login_attempts):
                        login_attempts[address] = [t for t in login_attempts[address] if now - t < 900]
                        if not login_attempts[address]:
                            del login_attempts[address]
                    attempts = login_attempts.setdefault(peer, [])
                    if len(attempts) >= 10:
                        return self.send(429, {"error": "Too many sign-in attempts; try again in 15 minutes"})
                    attempts.append(now)
                with account_lock:
                    admin = store.get("admin")
                    require(admin is not None, "Administrator is not initialized; run the init command")
                    username = str(data.get("username", ""))
                    password = str(data.get("password", ""))
                    valid = len(password) <= 256 and password_matches(password, admin["password"])
                    if not valid or not hmac.compare_digest(username.encode(), admin["username"].encode()):
                        notifications.emit(store, 'login_failed', 'An administrator sign-in attempt was rejected.', 'failed-login', 900)
                        return self.send(401, {"error": "Incorrect username or password"})
                    if admin.get('totp_secret') and not data.get('code'):
                        return self.send(200, {'two_factor_required': True})
                    if not security.verify_factor(admin, data.get('code', '')):
                        notifications.emit(store, 'login_failed', 'An administrator sign-in attempt was rejected.', 'failed-login', 900)
                        return self.send(401, {'error': 'Invalid or already used verification code'})
                    if admin.get('totp_secret'): store.set('admin', admin)
                    token, csrf = store.new_session()
                with throttle_lock:login_attempts.pop(peer, None)
                cookie = "nara_session=" + token + "; HttpOnly; SameSite=Strict; Path=" + cookie_path + "; Max-Age=43200" + ("; Secure" if secure_cookie else "")
                store.audit("Administrator signed in")
                notifications.emit(store, 'login', 'A new authenticated administrator session started.')
                return self.send(200, {"csrf": csrf}, headers={"Set-Cookie": cookie})
            if not self.auth(mutation=True):
                return
            data = self.json_body()
            if path in ('/api/migration/probe','/api/migration/start'):
                request_host=urlsplit('//'+self.headers.get('Host','')).hostname
                require(secure_cookie or request_host in ('127.0.0.1','::1','localhost') and ipaddress.ip_address(self.client_address[0]).is_loopback,'Enable panel HTTPS before providing root SSH credentials')
                require(not (store.directory/'access-request.json').exists(),'Another maintenance operation is pending')
                with account_lock:
                    accounts.verify(store,store.get('admin'),data,self.cookie_token())
                return self.send(200, migration.probe(store,data) if path.endswith('/probe') else migrations.start(data))
            if path == '/api/traffic/settings':
                value=traffic.validate(data.get('settings'))
                store.set('traffic_settings', value)
                store.audit('Server traffic and alert policy saved')
                return self.send(200, {'ok':True})
            if path == '/api/traffic/reset':
                with runtime.lock:
                    if runtime.running:runtime.collect()
                    traffic.sample_host(store)
                    traffic.reset(store,data.get('kind'))
                return self.send(200, {'ok':True})
            if path in ('/api/backup/create','/api/backup/restore','/api/clients-csv'):
                with account_lock:
                    accounts.verify(store,store.get('admin'),data,self.cookie_token())
                if path=='/api/backup/create':
                    with runtime.lock:
                        if runtime.running:runtime.collect()
                        result=portable.snapshot(store)
                    proof=secrets.token_urlsafe(32)
                    store.set('prepared_update_backup',{'proof':proof,'session':hashlib.sha256(self.cookie_token().encode()).hexdigest(),'expires':time.time()+900,'filename':result['filename']})
                    return self.send(200,{**result,'proof':proof})
                if path=='/api/backup/restore':
                    return self.send(200,portable.restore(store,runtime,data.get('backup')))
                current='http://'+self.headers.get('Host','')+base_path+'/'
                return self.send(200,{'csv':client_links.export(store,access,current,data.get('ids'))})
            if path=='/api/backup/preview':
                return self.send(200,portable.preview(store,data.get('backup')))
            if path == "/api/warp":
                return self.send(200, self.provision_warp(data))
            if path == "/api/check-updates":
                started = updates.start()
                return self.send(200, {"started": started, "updates": updates.status(runtime.version())})
            if path == "/api/update-panel":
                require(migrations.status().get("status")!="running","Wait for the server migration to finish before updating")
                prepared=store.get('prepared_update_backup',{})
                require(data.get('confirmed') is True and isinstance(data.get('backup_proof'),str) and hmac.compare_digest(prepared.get('proof',''),data['backup_proof']) and prepared.get('expires',0)>time.time() and prepared.get('session')==hashlib.sha256(self.cookie_token().encode()).hexdigest(),'Confirm the update and download a fresh private backup first')
                result = access.request_update(data.get('version'))
                store.set('prepared_update_backup',{})
                store.audit('Panel update requested: ' + result['version'])
                return self.send(200, result)
            if path == "/api/access":
                require(isinstance(data.get("current_url"), str), "Panel address is required")
                parsed = urlsplit(data["current_url"])
                require(parsed.netloc == self.headers.get("Host"), "Panel address must match this request")
                result = access.request(data.get("values"), data.get("revision"), data["current_url"])
                return self.send(202, result)
            if path == "/api/logout":
                store.logout(self.cookie_token())
                return self.send(200, {"ok": True}, headers={"Set-Cookie": "nara_session=; Max-Age=0; HttpOnly; SameSite=Strict; Path=" + cookie_path + ("; Secure" if secure_cookie else "")})
            if path == "/api/password" or path.startswith('/api/admin/'):
                action = 'credentials' if path == '/api/password' else path[len('/api/admin/'):]
                with account_lock:
                    result = accounts.action(store, action, data, self.cookie_token())
                if action != 'avatar':notifications.emit(store, 'admin_changed', 'Administrator account security was updated.')
                return self.send(200, result)
            if path in ('/api/api-keys/create', '/api/api-keys/revoke'):
                with account_lock:
                    admin = store.get('admin')
                    accounts.verify(store, admin, data, self.cookie_token())
                    result = api_keys.create(store, data) if path.endswith('/create') else api_keys.revoke(store, data.get('id')) or {'ok': True}
                    store.set('admin', admin)
                store.audit('API key created' if path.endswith('/create') else 'API key revoked')
                notifications.emit(store, 'api_key', 'A machine-access key was created.' if path.endswith('/create') else 'A machine-access key was revoked.')
                return self.send(200, result)
            if path in ('/api/telegram/chats', '/api/telegram/check'):
                with account_lock:
                    admin = store.get('admin')
                    accounts.verify(store, admin, data, self.cookie_token())
                    value = notifications.validate_settings({'enabled': False, 'bot_token': data.get('bot_token', '')}, notifications.settings(store))
                    require(value.get('bot_token'), 'Enter a bot token first')
                    store.set('admin', admin)
                if path.endswith('/check'):
                    return self.send(200, {'bot': notifications.bot_info(value['bot_token'])})
                return self.send(200, {'chats': notifications.chats(value['bot_token'])})
            if path in ('/api/telegram', '/api/telegram/test'):
                with account_lock:
                    admin = store.get('admin')
                    accounts.verify(store, admin, data, self.cookie_token())
                    if path.endswith('/test'):
                        require(notifications.settings(store)['enabled'], 'Save and enable Telegram notifications first')
                        notifications.enqueue(store, 'test', 'Your bot is ready. Selected NARA events will appear here. No credentials or subscription links are included.')
                    else:
                        previous = notifications.settings(store)
                        value = notifications.validate_settings(data.get('settings'), previous)
                        notifications.save_settings(store, value, previous)
                store.audit('Telegram test queued' if path.endswith('/test') else 'Telegram notification settings updated')
                return self.send(200, {'ok': True, 'queued': path.endswith('/test')})
            if path in ('/api/clients-bulk-preview', '/api/clients-action-preview'):
                with runtime.lock:
                    state = store.get('state')
                    require(data.get('revision') == state['revision'], 'Settings changed; refresh the page')
                    return self.send(200, clients.preview(store, state, data, self.cookie_token(), 'create' if path == '/api/clients-bulk-preview' else 'action'))
            return self.send(*self.mutate(path, data))

        def provision_warp(self, data):
            require(data.get("accept_terms") is True, "Accept Cloudflare’s consumer terms to register WARP")
            require(warp_lock.acquire(blocking=False), "WARP creation is already in progress")
            try:
                with runtime.lock:
                    state = store.get("state")
                    require(data.get("revision") == state["revision"], "Settings changed in another request; refresh the page")
                    require("with_wireguard" in runtime.build_info()["tags"], "Install the compatible NARA core with WireGuard support first")
                pending = store.get("warp_pending")
                if not pending:
                    pending = {"id": uuid.uuid4().hex, "config": warp.create(runtime.binary)}
                    # Keep a completed registration privately if apply or a concurrent edit fails.
                    # A retry uses the same keys instead of registering another account.
                    store.set("warp_pending", pending)
                with runtime.lock:
                    state = store.get("state")
                    require(data.get("revision") == state["revision"], "Settings changed during WARP creation; refresh and retry. The registered configuration was kept privately.")
                    existing = next((row for row in state["endpoints"] if row["id"] == pending["id"]), None)
                    if existing:
                        store.set("warp_pending", None)
                        return {"ok": True, "tag": existing["tag"], "revision": state["revision"]}
                    row = warp.record(pending["config"], state)
                    row["id"] = pending["id"]
                    state["endpoints"].append(row)
                    validate(state)
                    state["revision"] += 1
                    result = runtime.apply(state, save=True)
                    store.set("warp_pending", None)
                    store.audit("Cloudflare WARP destination created and applied")
                    notifications.emit(store, "config_saved", "A Cloudflare WARP destination was registered and applied.")
                    return {"ok": True, "tag": row["tag"], "revision": state["revision"], **result}
            finally:
                warp_lock.release()

        def mutate(self, path, data):
            with runtime.lock:
                state = store.get("state")
                reset_client = None
                created, affected, row = [], [], None
                if path in ("/api/save", "/api/delete", "/api/self-signed", "/api/settings", "/api/core-options", "/api/reset-traffic", "/api/rotate-token", "/api/apply", "/api/reorder-rules", "/api/clients-bulk-create", "/api/clients-bulk-action"):
                    require(data.get("revision") == state["revision"], "Settings changed in another request; refresh the page")
                if path == "/api/apply":
                    return 200, runtime.apply(state)
                if path == "/api/check":
                    directory, _ = runtime.prepare(state)
                    import shutil
                    shutil.rmtree(directory)
                    return 200, {"ok": True}
                if path == "/api/stop":
                    runtime.stop()
                    store.set("autostart", False)
                    store.audit("Core stopped by administrator")
                    return 200, {"ok": True}
                if path == "/api/self-signed":
                    profile = self_signed(data)
                    profile.update(certificate_info(profile))
                    profile.update({f["key"]: data[f["key"]] for f in options.TLS if f["key"] in data})
                    state["tls"].append(profile)
                    row = profile
                elif path == "/api/clients-bulk-create":
                    created = (clients.prepared(store, state, data, getattr(self, 'api_identity', self.cookie_token()), 'create')['rows']
                               if data.get('preview_id') else clients.plan_create(state, data))
                    state["clients"].extend(created)
                elif path == "/api/clients-bulk-action":
                    plan = (clients.prepared(store, state, data, getattr(self, 'api_identity', self.cookie_token()), 'action')['data']
                            if data.get('preview_id') else data)
                    affected, reset_client = clients.plan_action(state, plan, store.totals())
                elif path == "/api/settings":
                    state["settings"] = data["settings"]
                elif path == "/api/core-options":
                    section = data.get("section")
                    require(section in ("log", "dns", "ntp", "certificate", "route", "experimental"), "Invalid core section")
                    require(isinstance(data.get("options"), dict), "Core options must be an object")
                    state.setdefault("core_options", {})[section] = native.preserve_secrets(data["options"], state.get("core_options", {}).get(section, {}))
                    if section == "dns" and "default_resolver" in data:
                        state["settings"]["dns_final"] = data["default_resolver"]
                    if section == "dns":
                        state["settings"]["dns_options"] = {}
                elif path in ("/api/save", "/api/delete"):
                    collection = data.get("collection")
                    require(collection in COLLECTIONS, "Invalid collection")
                    if path == "/api/delete":
                        if collection == "clients": affected = [r for r in state[collection] if r["id"] == data.get("id")]
                        state[collection] = [r for r in state[collection] if r["id"] != data.get("id")]
                        if collection == "client_groups":
                            for client in state["clients"]:
                                client["group_ids"] = [value for value in client.get("group_ids", []) if value != data.get("id")]
                    else:
                        record = data["record"]
                        require(isinstance(record, dict), "Invalid record")
                        existing = next((r for r in state[collection] if r["id"] == record.get("id")), {})
                        row = {**existing, **record}
                        for key in ("config", "extra_options", "extra_client_options"):
                            if key in record:
                                row[key] = native.preserve_secrets(record[key], existing.get(key, {}))
                        row["id"] = existing.get("id") or uuid.uuid4().hex
                        if row.get("mode") == "native" or collection in native.EXTRA_COLLECTIONS:
                            row["mode"] = "native"
                            require(isinstance(row.get("config"), dict), "Core configuration must be an object")
                            row["tag"] = row["config"].get("tag", "")
                            row["type"] = row["config"].get("type", "")
                            if collection == "inbounds":
                                row["port"] = row["config"].get("listen_port", 0)
                                row["listen"] = row["config"].get("listen", "")
                        if collection == 'client_groups' and isinstance(row.get('name'), str): row['name'] = row['name'].strip()
                        if collection == "clients":
                            if isinstance(row.get('name'), str): row['name'] = row['name'].strip()
                            for key, value in {'enabled': True, 'quota_bytes': 0, 'expires_at': '', 'note': '', 'group_ids': [], 'tags': []}.items():
                                row.setdefault(key, value)
                            if not row.get("name"):
                                row["name"] = clients.random_name(c["name"] for c in state["clients"])
                            row["uuid"] = existing.get("uuid") or str(uuid.uuid4())
                            row["password"] = existing.get("password") or secrets.token_urlsafe(24)
                            row["token"] = existing.get("token") or secrets.token_urlsafe(32)
                        if collection == "tls":
                            for f in options.TLS:
                                if f["key"] not in record:
                                    row.pop(f["key"], None)
                            row["kind"] = existing.get("kind", "imported")
                            row.update(certificate_info(row))
                        if collection == "dns_servers":
                            row = normalize_dns_record(row)
                        if collection == "dns_servers" and row.get("mode") != "native":
                            if row.get("type") == "local":
                                for key in ("server", "port", "domain_resolver", "path", "server_name"):
                                    row.pop(key, None)
                            if row.get("type") not in ("https", "h3"):
                                row.pop("path", None)
                            if row.get("type") not in ("https", "tls", "quic", "h3"):
                                row.pop("server_name", None)
                        if collection == "rule_sets" and row.get("mode") != "native":
                            for key in (("url", "format", "update_interval") if row.get("type") == "inline" else ("rules",)):
                                row.pop(key, None)
                        if collection == "dns_rules" and row.get("mode") != "native" and row.get("action") == "reject":
                            row.pop("server", None)
                        if existing:
                            state[collection] = [row if r["id"] == row["id"] else r for r in state[collection]]
                        else:
                            state[collection].append(row)
                elif path == "/api/reorder-rules":
                    collection = data.get("collection", "dns_rules")
                    require(collection in ("dns_rules", "route_rules", "rule_sets"), "Invalid ordered collection")
                    index = next((n for n, r in enumerate(state[collection]) if r["id"] == data.get("id")), None)
                    direction = data.get("direction", "up")
                    require(direction in ("up", "down"), "Invalid rule move direction")
                    target = (index + (1 if direction == "down" else -1)) if index is not None else -1
                    require(index is not None and 0 <= target < len(state[collection]), "Rule cannot be moved")
                    state[collection][target], state[collection][index] = state[collection][index], state[collection][target]
                elif path in ("/api/reset-traffic", "/api/rotate-token"):
                    client = next((c for c in state["clients"] if c["id"] == data.get("id")), None)
                    require(client is not None, "Client not found")
                    if path == "/api/rotate-token":
                        client["token"] = secrets.token_urlsafe(32)
                    else:
                        reset_client = client["id"]
                else:
                    return 404, {"error": "Not found"}
                validate(state)
                state["revision"] += 1
                result = runtime.apply(state, save=True, reset_client=reset_client)
                if path in ('/api/clients-bulk-create', '/api/clients-bulk-action') and data.get('preview_id'):
                    with store.connect() as db: db.execute('DELETE FROM kv WHERE key=?', ('bulk-preview:' + data['preview_id'],))
                store.audit("Settings saved and applied: " + path.split("/")[-1] + (" · API key: " + self.api_actor if hasattr(self, "api_actor") else ""))
                event = "config_saved"
                if path == "/api/clients-bulk-create":event = "clients_created"
                elif path == "/api/clients-bulk-action":event = "clients_deleted" if (plan if data.get("preview_id") else data).get("operation") == "delete" else "clients_updated"
                elif data.get("collection") == "clients":event = "clients_deleted" if path == "/api/delete" else "clients_updated" if data.get("record", {}).get("id") else "clients_created"
                items = created or affected or ([row] if row and data.get('collection') == 'clients' else [])
                detail = 'Settings were validated and applied. Core is running.'
                if items:
                    names = ', '.join(str(item.get('name', '')).replace('\n', ' ') for item in items[:5])
                    detail = f'{len(items)} client(s) · {names}' + (f' · +{len(items)-5} more' if len(items)>5 else '')
                    if path == '/api/clients-bulk-action': detail += '\nAction: ' + str((plan if data.get('preview_id') else data).get('operation', '')).replace('_', ' ')
                    detail += '\nChanges are applied. Your other clients are unchanged.'
                notifications.emit(store, event, detail)
                return 200, {"ok": True, "revision": state["revision"], **result,
                             **({"ids": [row["id"] for row in created]} if created else {}),
                             **({"affected": len(affected)} if affected else {}),
                             **({"record_id": row["id"]} if row else {})}

    return Handler


def serve(store, runtime, bind="127.0.0.1", port=10000, secure_cookie=False, web_path="", sub_port=10001, sub_path="/subscriptions", access_config=None):
    from .access import Access
    access = Access(store.directory, access_config or {"NARA_WEB_PATH": web_path, "NARA_PORT": port, "NARA_SUB_PATH": sub_path, "NARA_SUB_PORT": sub_port})
    web_dir = Path(__file__).resolve().parent.parent / "web"
    server = BoundedHTTPServer((bind, port), make_handler(store, runtime, web_dir, secure_cookie, web_path, access=access))
    try:
        subscription = BoundedHTTPServer((bind, sub_port), make_handler(store, runtime, web_dir, False, sub_path, role="subscription", access=access))
    except Exception:
        server.server_close()
        raise
    server.daemon_threads = subscription.daemon_threads = True
    threading.Thread(target=subscription.serve_forever, kwargs={"poll_interval": .5}, daemon=True).start()
    threading.Thread(target=runtime.worker, daemon=True).start()
    notifier = notifications.Worker(store, runtime)
    threading.Thread(target=notifier.run, daemon=True).start()
    print("NARA panel: http://" + bind + ":" + str(port) + normalize_web_path(web_path) + "/", flush=True)
    print("Subscriptions: http://" + bind + ":" + str(sub_port) + normalize_web_path(sub_path) + "/", flush=True)
    try:
        server.serve_forever(poll_interval=.5)
    except KeyboardInterrupt:
        pass
    finally:
        subscription.shutdown()
        subscription.server_close()
        runtime.shutdown.set()
        store.notification_wakeup.set()
        with runtime.lock:
            runtime.stop()
        server.server_close()
