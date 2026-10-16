import copy
import hashlib
import hmac
import ipaddress
import json
import mimetypes
import os
import secrets
import ssl
import subprocess
import tempfile
import threading
import time
import uuid
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from . import __version__, options
from .config import COLLECTIONS, build_config, client_config, eligible, host, require, validate
from . import native
from .updates import UpdateChecker
from .runtime import Metrics, atomic_write
from .store import password_hash, password_matches
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
            length = int(self.headers.get("Content-Length", "0"))
            require(0 < length <= 1_048_576, "Request is too large or empty")
            data = json.loads(self.rfile.read(length))
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
            if mutation and not hmac.compare_digest(self.headers.get("X-CSRF-Token", ""), session["csrf"]):
                self.send(403, {"error": "Invalid security token; refresh the page"})
                return None
            return session

        def same_origin(self):
            origin = self.headers.get("Origin")
            require(self.headers.get("Sec-Fetch-Site") != "cross-site", "Request origin is not allowed")
            if origin:
                require(urlsplit(origin).netloc == self.headers.get("Host"), "Request origin is not allowed")

        def do_GET(self):
            try:
                self.get()
            except (ValueError, KeyError, TypeError) as exc:
                self.send(400, {"error": str(exc) if isinstance(exc, ValueError) else "Invalid data structure"})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                self.send(500, {"error": "Operation failed; check service status"})

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
                state = store.get("state")
                client = next((c for c in state["clients"] if hmac.compare_digest(c["token"], token)), None)
                active = runtime.active
                live_client = next((c for c in active["clients"] if client and c["id"] == client["id"]), None) if active else None
                if not client or not live_client or not eligible(client, store.totals()):
                    return self.send(404, {"error": "Subscription is unavailable"})
                result = client_config(active, live_client, store.totals())
                usage = store.totals().get(client["id"], {})
                from .config import expiry
                info = "upload={}; download={}; total={}; expire={}".format(usage.get("upload", 0), usage.get("download", 0), live_client["quota_bytes"], int(expiry(live_client.get("expires_at"))))
                return self.send(200, result, headers={"Subscription-Userinfo": info, "Profile-Update-Interval": "6"})
            if role == "subscription":
                return self.send(404, {"error": "Not found"})
            if path.startswith("/api/"):
                session = self.auth()
                if not session:
                    return
                if path == "/api/session":
                    return self.send(200, {"csrf": session["csrf"], "username": store.get("admin")["username"]})
                if path == "/api/access":
                    return self.send(200, access.info())
                if path.startswith("/api/access-status/"):
                    return self.send(200, access.status(path.rsplit("/", 1)[-1]))
                if path == "/api/options":
                    return self.send(200, options.schema())
                if path == "/api/core-schema":
                    return self.send(200, native.payload())
                if path == "/api/state":
                    state = copy.deepcopy(store.get("state"))
                    for profile in state["tls"]:
                        profile.pop("private_key", None)
                    return self.send(200, native.redact(state))
                if path == "/api/dashboard":
                    with runtime.lock:
                        status = runtime.status()
                        return self.send(200, {"metrics": metrics.read(store.directory), "core": status,
                                               "panel_version": __version__, "updates": UpdateChecker(store).status(status["version"]),
                                               "totals": store.totals(), "events": store.events()})
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
                admin = store.get("admin")
                require(admin is not None, "Administrator is not initialized; run the init command")
                username = str(data.get("username", ""))
                password = str(data.get("password", ""))
                valid = password_matches(password, admin["password"])
                if not valid or not hmac.compare_digest(username.encode(), admin["username"].encode()):
                    return self.send(401, {"error": "Incorrect username or password"})
                token, csrf = store.new_session()
                cookie = "nara_session=" + token + "; HttpOnly; SameSite=Strict; Path=" + cookie_path + "; Max-Age=43200" + ("; Secure" if secure_cookie else "")
                store.audit("Administrator signed in")
                return self.send(200, {"csrf": csrf}, headers={"Set-Cookie": cookie})
            if not self.auth(mutation=True):
                return
            data = self.json_body()
            if path == "/api/access":
                require(isinstance(data.get("current_url"), str), "Panel address is required")
                parsed = urlsplit(data["current_url"])
                require(parsed.netloc == self.headers.get("Host"), "Panel address must match this request")
                result = access.request(data.get("values"), data.get("revision"), data["current_url"])
                return self.send(202, result)
            if path == "/api/logout":
                store.logout(self.cookie_token())
                return self.send(200, {"ok": True}, headers={"Set-Cookie": "nara_session=; Max-Age=0; HttpOnly; SameSite=Strict; Path=" + cookie_path + ("; Secure" if secure_cookie else "")})
            if path == "/api/password":
                admin = store.get("admin")
                require(password_matches(str(data.get("current", "")), admin["password"]), "Current password is incorrect")
                require(isinstance(data.get("password"), str) and 12 <= len(data["password"]) <= 256, "New password must contain at least 12 characters")
                admin["password"] = password_hash(data["password"])
                store.set("admin", admin)
                with store.connect() as db:
                    db.execute("DELETE FROM sessions")
                return self.send(200, {"ok": True})
            with runtime.lock:
                state = store.get("state")
                reset_client = None
                if path in ("/api/save", "/api/delete", "/api/self-signed", "/api/settings", "/api/core-options", "/api/reset-traffic", "/api/rotate-token", "/api/apply", "/api/reorder-rules"):
                    require(data.get("revision") == state["revision"], "Settings changed in another request; refresh the page")
                if path == "/api/apply":
                    return self.send(200, runtime.apply(state))
                if path == "/api/check":
                    directory, _ = runtime.prepare(state)
                    import shutil
                    shutil.rmtree(directory)
                    return self.send(200, {"ok": True})
                if path == "/api/stop":
                    runtime.stop()
                    store.set("autostart", False)
                    store.audit("Core stopped by administrator")
                    return self.send(200, {"ok": True})
                if path == "/api/self-signed":
                    profile = self_signed(data)
                    profile.update(certificate_info(profile))
                    profile.update({f["key"]: data[f["key"]] for f in options.TLS if f["key"] in data})
                    state["tls"].append(profile)
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
                        state[collection] = [r for r in state[collection] if r["id"] != data.get("id")]
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
                        if collection == "clients":
                            row["uuid"] = existing.get("uuid") or str(uuid.uuid4())
                            row["password"] = existing.get("password") or secrets.token_urlsafe(24)
                            row["token"] = existing.get("token") or secrets.token_urlsafe(32)
                        if collection == "tls":
                            for f in options.TLS:
                                if f["key"] not in record:
                                    row.pop(f["key"], None)
                            row["kind"] = existing.get("kind", "imported")
                            row.update(certificate_info(row))
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
                    require(index is not None and index > 0, "Rule cannot be moved")
                    state[collection][index - 1], state[collection][index] = state[collection][index], state[collection][index - 1]
                elif path in ("/api/reset-traffic", "/api/rotate-token"):
                    client = next((c for c in state["clients"] if c["id"] == data.get("id")), None)
                    require(client is not None, "Client not found")
                    if path == "/api/rotate-token":
                        client["token"] = secrets.token_urlsafe(32)
                    else:
                        reset_client = client["id"]
                else:
                    return self.send(404, {"error": "Not found"})
                validate(state)
                state["revision"] += 1
                result = runtime.apply(state, save=True, reset_client=reset_client)
                store.audit("Settings saved and applied: " + path.split("/")[-1])
                return self.send(200, {"ok": True, "revision": state["revision"], **result})

    return Handler


def serve(store, runtime, bind="127.0.0.1", port=10000, secure_cookie=False, web_path="", sub_port=10001, sub_path="/subscriptions", access_config=None):
    from .access import Access
    access = Access(store.directory, access_config or {"NARA_WEB_PATH": web_path, "NARA_PORT": port, "NARA_SUB_PATH": sub_path, "NARA_SUB_PORT": sub_port})
    web_dir = Path(__file__).resolve().parent.parent / "web"
    server = ThreadingHTTPServer((bind, port), make_handler(store, runtime, web_dir, secure_cookie, web_path, access=access))
    try:
        subscription = ThreadingHTTPServer((bind, sub_port), make_handler(store, runtime, web_dir, False, sub_path, role="subscription", access=access))
    except Exception:
        server.server_close()
        raise
    server.daemon_threads = subscription.daemon_threads = True
    threading.Thread(target=subscription.serve_forever, kwargs={"poll_interval": .5}, daemon=True).start()
    threading.Thread(target=runtime.worker, daemon=True).start()
    updates = UpdateChecker(store)
    threading.Thread(target=updates.worker, daemon=True).start()
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
        updates.shutdown.set()
        with runtime.lock:
            runtime.stop()
        server.server_close()
