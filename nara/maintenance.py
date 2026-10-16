"""Root-only Linux maintenance behind the interactive NARA manager.

Commands never evaluate the environment file as shell code. HTTPS uses a dedicated
Caddy service/configuration, independent of any existing system web server.
"""
import argparse
import contextlib
import datetime
import ipaddress
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import socket
import sqlite3
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from .install_config import normalize_web_path, panel_port, read_env
from .runtime import atomic_write
from .terminal import input_label, styled


class Layout:
    def __init__(self, root=Path("/")):
        self.root = Path(root)
        self.app = self.root / "opt/nara-panel"
        self.data = self.root / "var/lib/nara-panel"
        self.env = self.root / "etc/nara-panel.env"
        self.https = self.root / "etc/nara-panel/https"
        self.https_data = self.root / "var/lib/nara-panel-https"
        self.unit = self.root / "etc/systemd/system/nara-panel-https.service"
        self.backups = self.root / "var/backups/nara-panel"


def run(arguments, **kwargs):
    return subprocess.run(arguments, check=True, text=True, **kwargs)


def active(unit):
    return subprocess.run(["systemctl", "is-active", "--quiet", unit], check=False).returncode == 0


def settings(paths):
    value = read_env(paths.env)
    value["NARA_PORT"] = str(panel_port(value.get("NARA_PORT", "10000")))
    value["NARA_WEB_PATH"] = normalize_web_path(value.get("NARA_WEB_PATH", ""))
    return value


def write_env(path, values):
    # Preserve unknown administrator settings but never introduce additional lines.
    for key, value in values.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or any(c in str(value) for c in "\r\n\x00"):
            raise ValueError("Invalid environment setting")
    atomic_write(path, "".join(key + "=" + str(value) + "\n" for key, value in sorted(values.items())))
    path.chmod(0o600)


def panel_health(paths, timeout=30):
    config = settings(paths)
    url = "http://127.0.0.1:" + config["NARA_PORT"] + config["NARA_WEB_PATH"] + "/api/health"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while True:
        try:
            with opener.open(url, timeout=2) as response:
                if response.status == 200:
                    return json.load(response)
        except (OSError, ValueError):
            pass
        if time.monotonic() >= deadline:
            raise ValueError("Panel is not ready. Check: journalctl -u nara-panel -n 50")
        time.sleep(1)


def snapshot_database(source, destination):
    owner = source.stat()
    if os.geteuid() == 0 and owner.st_uid != 0:
        # Connecting to a WAL database as root can create root-owned -wal/-shm
        # files and temporarily lock the service out. Snapshot as its own user.
        account = pwd.getpwuid(owner.st_uid).pw_name
        with tempfile.TemporaryDirectory(prefix=".nara-backup-", dir=source.parent) as directory:
            os.chown(directory, owner.st_uid, owner.st_gid)
            snapshot = Path(directory) / "panel.sqlite3"
            worker = "import contextlib,sqlite3,sys; from urllib.parse import quote\nwith contextlib.closing(sqlite3.connect('file:'+quote(sys.argv[1])+'?mode=ro',uri=True)) as source, contextlib.closing(sqlite3.connect(sys.argv[2])) as target: source.backup(target)"
            run(["runuser", "-u", account, "--", sys.executable, "-c", worker, str(source), str(snapshot)], cwd=source.parent, stdin=subprocess.DEVNULL, timeout=120)
            shutil.copyfile(snapshot, destination)
    else:
        with contextlib.closing(sqlite3.connect(str(source))) as database, contextlib.closing(sqlite3.connect(str(destination))) as target:
            database.backup(target)


def backup(paths):
    paths.backups.mkdir(parents=True, exist_ok=True, mode=0o700)
    paths.backups.chmod(0o700)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
    descriptor, name = tempfile.mkstemp(prefix="nara-" + stamp + "-", suffix=".tar.gz", dir=paths.backups)
    os.close(descriptor)
    destination = Path(name)
    try:
        with tempfile.TemporaryDirectory(dir=paths.backups) as directory:
            staging = Path(directory)
            database = paths.data / "panel.sqlite3"
            if database.exists():
                # SQLite's online backup includes committed WAL data consistently.
                snapshot_database(database, staging / "panel.sqlite3")
            with tarfile.open(destination, "w:gz", dereference=False) as archive:
                if (staging / "panel.sqlite3").exists():
                    archive.add(staging / "panel.sqlite3", arcname="var/lib/nara-panel/panel.sqlite3")
                if paths.data.exists():
                    for item in paths.data.iterdir():
                        if item.name not in ("panel.sqlite3", "panel.sqlite3-wal", "panel.sqlite3-shm", "panel.lock", "core.log", "runtime"):
                            archive.add(item, arcname="var/lib/nara-panel/" + item.name)
                for item in (paths.env, paths.https, paths.https_data,
                             paths.unit,
                             paths.root / "etc/systemd/system/nara-panel.service.d"):
                    if item.exists():
                        archive.add(item, arcname=str(item.relative_to(paths.root)))
        destination.chmod(0o600)
        print("Private backup saved: " + str(destination))
        print("Contains account credentials and private keys. Store it privately; it is not uploaded.")
        return destination
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def hostname(value, automatic=False):
    value = value.strip()
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        address = None
    if address is not None:
        if automatic:
            raise ValueError("Automatic certificates require a public domain name; use Self-signed or Import for an IP.")
        return str(address)
    try:
        value = value.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("Enter a domain or IP without a scheme, path or port") from exc
    labels = value.split(".")
    if len(value) > 253 or len(labels) < 2 or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels):
        raise ValueError("Enter a domain or IP without a scheme, path or port")
    if automatic and (value.endswith((".localhost", ".local", ".internal", ".test", ".invalid", ".example", ".home.arpa")) or labels[-1].isdigit()):
        raise ValueError("A publicly resolvable domain is required")
    return value


def site_url(host, path):
    return "https://" + ("[" + host + "]" if ":" in host else host) + path + "/"


def caddyfile(host, port, path, mode, generation, legacy=False):
    host = hostname(host, automatic=mode == "automatic")
    port = panel_port(port)
    path = normalize_web_path(path)
    if port in (80, 443):
        raise ValueError("The internal panel port cannot be 80 or 443 when enabling panel HTTPS")
    authority = "[" + host + "]" if ":" in host else host
    # admin off avoids collisions with a separate existing Caddy admin API.
    # TCP-only HTTPS leaves UDP 443 available for QUIC proxy inbounds.
    lines = ["{", "    admin off", "    skip_install_trust"]
    try:
        ipaddress.ip_address(host)
        # IP clients do not send SNI. Choose the configured IP certificate even
        # when a local readiness probe reaches us through 127.0.0.1 / NAT.
        lines += ["    default_sni " + host]
    except ValueError:
        pass
    # Caddy 2.4/2.5 (Ubuntu 22.04) have HTTP/3 off by default and use
    # an older server-options syntax. Caddy 2.6+ enable it by default.
    if not legacy:
        lines += ["    servers {", "        protocols h1 h2", "    }"]
    lines += ["}", "https://" + authority + " {"]
    if mode != "automatic":
        lines += ['    tls "' + str(generation / "cert.pem") + '" "' + str(generation / "key.pem") + '"']
    # Preserve the prefix, including all subscription URLs. No access logs/tokens.
    if path:
        lines += ["    @panel path " + path + " " + path + "/*", "    handle @panel {", "        reverse_proxy 127.0.0.1:" + str(port), "    }", "    handle {", '        respond "Not found" 404', "    }"]
    else:
        lines += ["    reverse_proxy 127.0.0.1:" + str(port)]
    return "\n".join(lines + ["}", ""])


def ask(message):
    with open("/dev/tty", "r") as terminal_input, open("/dev/tty", "w") as terminal_output:
        terminal_output.write(input_label(message, terminal_output) + " ")
        terminal_output.flush()
        answer = terminal_input.readline()
        if not answer:
            raise ValueError("An interactive terminal is required")
        return answer.rstrip("\n")


def read_pem(path):
    if not path.is_absolute() or not path.is_file():
        raise ValueError("Use an absolute path to a regular PEM file")
    with path.open("rb") as file:
        data = file.read(1_000_001)
    if len(data) > 1_000_000:
        raise ValueError("PEM files must be smaller than 1 MB")
    value = data.decode("utf-8")
    if "ENCRYPTED" in value:
        raise ValueError("Use an unencrypted private key PEM; encrypted keys cannot be loaded unattended")
    return value


def assert_proxy_ports_free():
    for port in (80, 443):
        for family, address in ((socket.AF_INET, "0.0.0.0"), (socket.AF_INET6, "::")):
            try:
                with socket.socket(family, socket.SOCK_STREAM) as sock:
                    if family == socket.AF_INET6:
                        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
                    sock.bind((address, port))
            except OSError as exc:
                if family == socket.AF_INET6 and exc.errno in (97, 99):
                    continue  # Hosts without IPv6 support.
                raise ValueError("TCP port " + str(port) + " is busy. Keep your existing web server and configure HTTPS there, or free this port first.") from exc


def ensure_caddy():
    if shutil.which("caddy"):
        return
    # Package installation must not launch the distribution's default web site.
    if subprocess.run(["systemctl", "cat", "caddy.service"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        raise ValueError("A Caddy service already exists but its binary is missing. Repair it before continuing.")
    run(["systemctl", "mask", "--runtime", "caddy.service"])
    try:
        run(["apt-get", "install", "-y", "--no-install-recommends", "caddy"], env={**os.environ, "DEBIAN_FRONTEND": "noninteractive"}, stdin=subprocess.DEVNULL)
        run(["systemctl", "disable", "caddy.service"])
    finally:
        run(["systemctl", "unmask", "--runtime", "caddy.service"])


def https_service(paths):
    return """[Unit]
Description=NARA panel HTTPS (dedicated Caddy proxy)
Wants=network-online.target nara-panel.service
After=network-online.target nara-panel.service
[Service]
User=nara-https
Group=nara-https
ExecStart=/usr/bin/caddy run --config /etc/nara-panel/https/current/Caddyfile --adapter caddyfile
Environment=XDG_DATA_HOME=/var/lib/nara-panel-https/data
Environment=XDG_CONFIG_HOME=/var/lib/nara-panel-https/config
StateDirectory=nara-panel-https
StateDirectoryMode=0700
Restart=on-failure
RestartSec=5
UMask=0077
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/nara-panel-https
[Install]
WantedBy=multi-user.target
""".replace("/usr/bin/caddy", shutil.which("caddy") or "/usr/bin/caddy")


def verify_https(host, path, certificate=None, timeout=90):
    context = ssl.create_default_context(cafile=str(certificate) if certificate else None)
    # Test local listener with the real SNI and certificate verification, independent
    # of DNS hairpin/NAT. The CA still validates public DNS and reachability itself.
    deadline = time.monotonic() + timeout
    while True:
        try:
            with socket.create_connection(("127.0.0.1", 443), timeout=3) as raw:
                with context.wrap_socket(raw, server_hostname=host) as stream:
                    authority = "[" + host + "]" if ":" in host else host
                    request = "GET " + path + "/api/health HTTP/1.1\r\nHost: " + authority + "\r\nConnection: close\r\n\r\n"
                    stream.sendall(request.encode("ascii"))
                    if b" 200 " in stream.recv(4096).split(b"\r\n", 1)[0]:
                        return
        except (OSError, ValueError):
            pass
        if time.monotonic() >= deadline:
            raise ValueError("HTTPS or certificate verification failed. Check DNS, TCP 80/443 and journalctl -u nara-panel-https -n 50. Previous settings were restored.")
        time.sleep(2)


def set_public_url(paths, url):
    from .store import Store
    store = Store(paths.data)
    previous = {}
    with store.connect() as db:
        for name in ("state", "active"):
            row = db.execute("SELECT value FROM kv WHERE key=?", (name,)).fetchone()
            if row:
                state = json.loads(row[0])
                previous[name] = state["settings"].get("public_url", "")
                state["settings"]["public_url"] = url
                db.execute("UPDATE kv SET value=? WHERE key=?", (json.dumps(state), name))
    return previous


def restore_public_urls(paths, values):
    from .store import Store
    store = Store(paths.data)
    with store.connect() as db:
        for name, url in values.items():
            row = db.execute("SELECT value FROM kv WHERE key=?", (name,)).fetchone()
            if row:
                state = json.loads(row[0])
                state["settings"]["public_url"] = url
                db.execute("UPDATE kv SET value=? WHERE key=?", (json.dumps(state), name))


def configure_https(paths, mode):
    config = settings(paths)
    if int(config["NARA_PORT"]) in (80, 443):
        raise ValueError("First move the internal panel port away from 80/443 in /etc/nara-panel.env and restart NARA.")
    print("\nPanel HTTPS uses a dedicated Caddy proxy on TCP 80/443.")
    print("The internal panel will listen only on 127.0.0.1; its port and webPath are preserved.")
    print("Keep TCP 80/443 open in your firewall. Existing reverse-proxy configurations are not modified.")
    if mode == "automatic":
        print("Point every A/AAAA record at this server first. Certificates are obtained and renewed automatically.")
        print("The domain is submitted to public certificate authorities and certificate transparency logs.")
    else:
        print("Self-signed certificates require explicit trust on each device; imported certificates must already be trusted.")
    host = hostname(ask("Public domain:" if mode == "automatic" else "Domain or IP:"), automatic=mode == "automatic")
    if mode == "automatic":
        socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    certificate_pem = private_key_pem = None
    if mode == "import":
        cert_source = Path(ask("Full-chain certificate PEM file (absolute path):")).expanduser()
        key_source = Path(ask("Private key PEM file (absolute path):")).expanduser()
        certificate_pem, private_key_pem = read_pem(cert_source), read_pem(key_source)
        from .server import certificate_info
        certificate_info({"server_name": host, "certificate": certificate_pem, "private_key": private_key_pem})
    backup(paths)
    was_proxy = active("nara-panel-https")
    was_panel = active("nara-panel")
    proxy_enabled = subprocess.run(["systemctl", "is-enabled", "--quiet", "nara-panel-https"], check=False).returncode == 0
    old_urls = None
    panel_changed = False
    proxy_touched = was_proxy
    old_env = paths.env.read_text()
    old_unit = paths.unit.read_text() if paths.unit.exists() else None
    paths.https.mkdir(parents=True, exist_ok=True, mode=0o755)
    paths.https.parent.chmod(0o755)
    paths.https.chmod(0o755)
    current = paths.https / "current"
    if current.exists() and not current.is_symlink():
        raise ValueError("Unexpected HTTPS current path; refusing to replace it")
    old_target = os.readlink(current) if current.is_symlink() else None
    generation = Path(tempfile.mkdtemp(prefix="generation-", dir=paths.https))
    try:
        if was_proxy:
            run(["systemctl", "stop", "nara-panel-https"])
        assert_proxy_ports_free()
        ensure_caddy()
        installed_caddy = run(["caddy", "version"], capture_output=True).stdout
        match = re.search(r"v?(\d+)\.(\d+)\.", installed_caddy)
        if not match or tuple(map(int, match.groups())) < (2, 4):
            raise ValueError("Caddy 2.4 or later is required")
        legacy_caddy = tuple(map(int, match.groups())) < (2, 6)
        if subprocess.run(["id", "nara-https"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            run(["useradd", "--system", "--home-dir", "/var/lib/nara-panel-https", "--shell", "/usr/sbin/nologin", "nara-https"])
        if mode == "self-signed":
            try:
                ipaddress.ip_address(host)
                san = "IP:" + host
            except ValueError:
                san = "DNS:" + host
            run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes", "-days", "365", "-subj", "/CN=" + host, "-addext", "subjectAltName=" + san, "-keyout", str(generation / "key.pem"), "-out", str(generation / "cert.pem")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif mode == "import":
            atomic_write(generation / "cert.pem", certificate_pem)
            atomic_write(generation / "key.pem", private_key_pem)
        if mode != "automatic":
            from .server import certificate_info
            certificate_info({"server_name": host, "certificate": (generation / "cert.pem").read_text(), "private_key": (generation / "key.pem").read_text()})
        atomic_write(generation / "Caddyfile", caddyfile(host, config["NARA_PORT"], config["NARA_WEB_PATH"], mode, generation, legacy=legacy_caddy))
        atomic_write(generation / "metadata.json", json.dumps({"host": host, "mode": mode, "url": site_url(host, config["NARA_WEB_PATH"])}))
        for item in [generation, *generation.iterdir()]:
            shutil.chown(item, user="root", group="nara-https")
            item.chmod(0o750 if item.is_dir() else 0o640)
        run(["caddy", "validate", "--config", str(generation / "Caddyfile"), "--adapter", "caddyfile"], stdout=subprocess.DEVNULL)
        current.unlink(missing_ok=True)
        current.symlink_to(generation.name)
        atomic_write(paths.unit, https_service(paths))
        paths.unit.chmod(0o644)
        panel_changed = True
        write_env(paths.env, {**config, "NARA_BIND": "127.0.0.1", "NARA_SECURE_COOKIE": "1"})
        run(["systemctl", "daemon-reload"])
        run(["systemctl", "restart", "nara-panel"])
        panel_health(paths)
        proxy_touched = True
        run(["systemctl", "start", "nara-panel-https"])
        print("Waiting for a verified HTTPS connection (up to 90 seconds)...")
        verify_https(host, config["NARA_WEB_PATH"], generation / "cert.pem" if mode == "self-signed" else None)
        # Finish root-side SQLite writes while the service is stopped; all
        # journal files are closed before returning the DB to its service user.
        run(["systemctl", "stop", "nara-panel"])
        old_urls = set_public_url(paths, site_url(host, config["NARA_WEB_PATH"]))
        # Load the updated active model into memory too, so future quota-driven
        # reapplication cannot restore a stale public URL.
        run(["systemctl", "restart", "nara-panel"])
        panel_health(paths)
        run(["systemctl", "enable", "nara-panel-https"])
        print(styled("HTTPS is ready: " + site_url(host, config["NARA_WEB_PATH"]), color="32"))
        if mode == "automatic":
            print("Caddy renews the certificate automatically while its service is running.")
        else:
            print("Certificate: " + str(generation / "cert.pem") + " (renew/re-import before expiry).")
            if mode == "self-signed":
                print("Only this public certificate may be shared for device trust. Keep key.pem private.")
        # Previous certificates may still be in a private backup; no stale keys here.
        for item in paths.https.glob("generation-*"):
            if item != generation:
                shutil.rmtree(item, ignore_errors=True)
    except Exception:
        if proxy_touched:
            subprocess.run(["systemctl", "stop", "nara-panel-https"], check=False)
        if proxy_touched and not proxy_enabled:
            subprocess.run(["systemctl", "disable", "nara-panel-https"], check=False)
        if old_urls is not None:
            run(["systemctl", "stop", "nara-panel"])
            restore_public_urls(paths, old_urls)
        atomic_write(paths.env, old_env)
        current.unlink(missing_ok=True)
        if old_target:
            current.symlink_to(old_target)
        if old_unit is not None:
            atomic_write(paths.unit, old_unit)
            paths.unit.chmod(0o644)
        else:
            paths.unit.unlink(missing_ok=True)
        run(["systemctl", "daemon-reload"])
        if panel_changed:
            if was_panel:
                run(["systemctl", "restart", "nara-panel"])
            else:
                subprocess.run(["systemctl", "stop", "nara-panel"], check=False)
        if was_proxy:
            run(["systemctl", "start", "nara-panel-https"])
        shutil.rmtree(generation, ignore_errors=True)
        raise


def https_status(paths):
    metadata = paths.https / "current/metadata.json"
    if not metadata.exists():
        print("Panel HTTPS has not been configured through NARA. An external proxy may be configured separately.")
        return
    data = json.loads(metadata.read_text())
    print("HTTPS URL: " + data["url"] + "\nCertificate mode: " + data["mode"])
    print("HTTPS service: " + ("running" if active("nara-panel-https") else "stopped"))
    certificate = paths.https / "current/cert.pem"
    if certificate.exists():
        run(["openssl", "x509", "-in", str(certificate), "-noout", "-subject", "-dates", "-fingerprint", "-sha256"])
    else:
        print("Managed certificates and automatic renewal: /var/lib/nara-panel-https/data/caddy")
        for certificate in paths.https_data.glob("data/caddy/certificates/*/*/*.crt"):
            run(["openssl", "x509", "-in", str(certificate), "-noout", "-subject", "-dates"])


def restore_https_service(paths):
    """Recreate the dedicated proxy after reinstalling retained/restored data."""
    metadata = paths.https / "current/metadata.json"
    if not metadata.exists():
        return
    ensure_caddy()
    if subprocess.run(["id", "nara-https"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        run(["useradd", "--system", "--home-dir", "/var/lib/nara-panel-https", "--shell", "/usr/sbin/nologin", "nara-https"])
    paths.https.parent.chmod(0o755)
    paths.https.chmod(0o755)
    for generation in paths.https.glob("generation-*"):
        for item in [generation, *generation.iterdir()]:
            shutil.chown(item, user="root", group="nara-https")
            item.chmod(0o750 if item.is_dir() else 0o640)
    if paths.https_data.exists():
        for item in [paths.https_data, *paths.https_data.rglob("*")]:
            shutil.chown(item, user="nara-https", group="nara-https")
    run(["caddy", "validate", "--config", str(paths.https / "current/Caddyfile"), "--adapter", "caddyfile"], stdout=subprocess.DEVNULL)
    atomic_write(paths.unit, https_service(paths))
    paths.unit.chmod(0o644)
    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", "--now", "nara-panel-https"])
    data = json.loads(metadata.read_text())
    verify_https(data["host"], settings(paths)["NARA_WEB_PATH"], paths.https / "current/cert.pem" if data["mode"] == "self-signed" else None)


def versions(paths):
    installed = paths.app / "nara/__init__.py"
    match = re.search(r'__version__\s*=\s*[\x22\x27]([0-9.]+)', installed.read_text()) if installed.exists() else None
    print("NARA v" + (match.group(1) if match else "unknown"))
    core = paths.app / "bin/sing-box"
    if core.exists():
        result = run([str(core), "version"], capture_output=True)
        print(result.stdout.splitlines()[0])


def status(paths):
    versions(paths)
    config = settings(paths)
    print("Panel/core service: " + ("running" if active("nara-panel") else "stopped"))
    print("Internal panel: http://" + config.get("NARA_BIND", "0.0.0.0") + ":" + config["NARA_PORT"] + config["NARA_WEB_PATH"] + "/")
    if not (paths.https / "current/metadata.json").exists():
        print("Direct URL: http://YOUR_SERVER_IP:" + config["NARA_PORT"] + config["NARA_WEB_PATH"] + "/")
    https_status(paths)
    print("Entry settings: /etc/nara-panel.env\nPrivate data: /var/lib/nara-panel")


def uninstall(paths, mode):
    # The shell has already required an exact typed confirmation.
    if mode == "1":
        backup(paths)
    for unit in ("nara-panel-https", "nara-panel"):
        subprocess.run(["systemctl", "disable", "--now", unit], check=False)
        if active(unit):
            raise ValueError("Could not stop " + unit + "; no application files were removed")
    for item in (paths.unit, paths.root / "etc/systemd/system/nara-panel.service", paths.root / "usr/local/bin/nara"):
        item.unlink(missing_ok=True)
    if paths.app.exists():
        shutil.rmtree(paths.app)
    if mode == "2":
        for item in (paths.data, paths.https, paths.https_data, paths.root / "etc/systemd/system/nara-panel.service.d"):
            if item.exists():
                shutil.rmtree(item)
        paths.env.unlink(missing_ok=True)
    run(["systemctl", "daemon-reload"])
    print("NARA removed. " + ("Private data, entry settings and certificates were kept for reinstallation." if mode == "1" else "NARA data, entry settings and certificates were deleted."))
    print("Existing backup archives, service users and system packages were retained.")


def main():
    parser = argparse.ArgumentParser(description="NARA maintenance (use the nara menu)")
    parser.add_argument("command", choices=("backup", "health", "versions", "status", "https", "https-status", "restore-https", "uninstall"))
    parser.add_argument("option", nargs="?")
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error("Run the NARA manager as root")
    if os.uname().sysname != "Linux":
        parser.error("The server manager requires Linux")
    os.umask(0o077)
    paths = Layout()
    try:
        if args.command == "https":
            if args.option not in ("automatic", "self-signed", "import"):
                parser.error("Invalid certificate mode")
            configure_https(paths, args.option)
        elif args.command == "uninstall":
            if args.option not in ("1", "2"):
                parser.error("Invalid removal mode")
            uninstall(paths, args.option)
        else:
            {"backup": backup, "health": panel_health, "versions": versions, "status": status, "https-status": https_status, "restore-https": restore_https_service}[args.command](paths)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        parser.exit(1, "NARA: " + str(exc) + "\n")


if __name__ == "__main__":
    main()
