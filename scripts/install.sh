#!/bin/sh
set -eu
umask 022  # Application/venv files must be readable by the service user.
[ "$(uname -s)" = Linux ] || { echo "This installer requires Linux." >&2; exit 1; }
[ "$(id -u)" = 0 ] || { echo "Run as root or with sudo." >&2; exit 1; }
command -v systemctl >/dev/null || { echo "systemd is required." >&2; exit 1; }
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
. "$source_dir/scripts/terminal.sh"
ui_title "Installation / Upgrade"
if [ "${NARA_MANAGER_LOCK_HELD:-0}" != 1 ]; then
    exec 9>/run/lock/nara-panel-manager.lock
    flock -n 9 || { ui_error 'Another NARA maintenance session is running.'; exit 1; }
fi
python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ is required"'
command -v openssl >/dev/null || { echo "Install OpenSSL first." >&2; exit 1; }
# Stage configuration: failed installs never overwrite the live entry URL.
setup_dir=$(mktemp -d)
was_running=0
was_enabled=0
was_https_running=0
was_https_enabled=0
was_access_running=0
if systemctl is-active --quiet nara-panel-access.path; then was_access_running=1; fi
if systemctl is-enabled --quiet nara-panel; then was_enabled=1; fi
if systemctl is-active --quiet nara-panel-https; then was_https_running=1; fi
if systemctl is-enabled --quiet nara-panel-https; then was_https_enabled=1; fi
mutating=0
cleanup() {
    status=$?
    trap - EXIT
    if [ "$status" -ne 0 ] && [ "$mutating" = 1 ]; then
        ui_warn 'Installation failed; restoring the previous application, core and entry settings.'
        systemctl stop nara-panel || true
        systemctl stop nara-panel-access.path || true
        if [ "$was_access_running" = 0 ]; then systemctl disable nara-panel-access.path || true; fi
        if [ "$was_enabled" = 0 ]; then systemctl disable nara-panel || true; fi
        for item in nara web scripts bin .venv requirements.txt; do
            rm -rf "/opt/nara-panel/$item"
            if [ -e "$setup_dir/previous/$item" ]; then cp -R "$setup_dir/previous/$item" /opt/nara-panel/; fi
        done
        if [ "$was_https_running" = 0 ]; then systemctl stop nara-panel-https || true; fi
        if [ "$was_https_enabled" = 0 ]; then systemctl disable nara-panel-https || true; fi
        for item in env unit https-unit access-path access-unit command; do
            case "$item" in env) target=/etc/nara-panel.env ;; unit) target=/etc/systemd/system/nara-panel.service ;; https-unit) target=/etc/systemd/system/nara-panel-https.service ;; access-path) target=/etc/systemd/system/nara-panel-access.path ;; access-unit) target=/etc/systemd/system/nara-panel-access.service ;; command) target=/usr/local/bin/nara ;; esac
            if [ -f "$setup_dir/previous-$item" ]; then cp -p "$setup_dir/previous-$item" "$target"; else rm -f "$target"; fi
        done
        systemctl daemon-reload || true
        if [ "$was_access_running" = 1 ]; then systemctl start nara-panel-access.path || true; fi
    fi
    if [ "$status" -ne 0 ] && [ "$was_running" = 1 ]; then systemctl start nara-panel || true; fi
    rm -rf "$setup_dir"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if [ -f /etc/nara-panel.env ]; then cp /etc/nara-panel.env "$setup_dir/panel.env"; fi
cd "$source_dir"
if [ -n "${NARA_INSTALL_CORE:-}" ]; then
    core=$NARA_INSTALL_CORE
else
    ui_info "Downloading the prebuilt compatible core. No Go compiler is installed or required."
    python3 "$source_dir/scripts/fetch-core.py" --output "$setup_dir/core" </dev/null
    core=$setup_dir/core/sing-box
fi
[ -x "$core" ] || { ui_error 'A compatible prebuilt core is required; compilation is not used as a fallback.'; exit 1; }
"$core" version | grep -q with_v2ray_api || { echo "The core requires with_v2ray_api." >&2; exit 1; }
"$core" version | grep -q with_quic || { echo "The core requires with_quic." >&2; exit 1; }
# Download/verify first, then snapshot before changing the installed application.
mkdir "$setup_dir/previous"
for item in nara web scripts bin .venv requirements.txt; do
    if [ -e "/opt/nara-panel/$item" ]; then cp -R "/opt/nara-panel/$item" "$setup_dir/previous/"; fi
done
if [ -f /etc/nara-panel.env ]; then cp -p /etc/nara-panel.env "$setup_dir/previous-env"; fi
if [ -f /etc/systemd/system/nara-panel.service ]; then cp -p /etc/systemd/system/nara-panel.service "$setup_dir/previous-unit"; fi
if [ -f /etc/systemd/system/nara-panel-https.service ]; then cp -p /etc/systemd/system/nara-panel-https.service "$setup_dir/previous-https-unit"; fi
for item in path service; do
    if [ -f "/etc/systemd/system/nara-panel-access.$item" ]; then
        case "$item" in path) label=access-path ;; service) label=access-unit ;; esac
        cp -p "/etc/systemd/system/nara-panel-access.$item" "$setup_dir/previous-$label"
    fi
done
if [ -f /usr/local/bin/nara ]; then cp -p /usr/local/bin/nara "$setup_dir/previous-command"; fi
# Stop only NARA so its existing port can be retained.
if systemctl is-active --quiet nara-panel; then
    was_running=1
    systemctl stop nara-panel
fi
if { [ "${NARA_KEEP_ENTRY:-0}" = 1 ] || [ -f /etc/nara-panel/https/current/metadata.json ]; } && [ -f "$setup_dir/panel.env" ]; then
    PYTHONDONTWRITEBYTECODE=1 python3 -m nara.install_config "$setup_dir/panel.env" --keep-panel
else
    PYTHONDONTWRITEBYTECODE=1 python3 -m nara.install_config "$setup_dir/panel.env"
fi
mutating=1
id nara-panel >/dev/null 2>&1 || useradd --system --home-dir /var/lib/nara-panel --shell /usr/sbin/nologin nara-panel
install -d -m 755 /opt/nara-panel /opt/nara-panel/bin
install -d -o nara-panel -g nara-panel -m 700 /var/lib/nara-panel
chown -hR nara-panel:nara-panel /var/lib/nara-panel
python3 -m venv /opt/nara-panel/.venv
/opt/nara-panel/.venv/bin/python -m pip install --disable-pip-version-check -r "$source_dir/requirements.txt" </dev/null
for item in nara web scripts; do
    rm -rf "/opt/nara-panel/$item"
    cp -R "$source_dir/$item" /opt/nara-panel/
done
chmod -R u=rwX,go=rX /opt/nara-panel/nara /opt/nara-panel/web /opt/nara-panel/scripts
install -m 755 "$source_dir/scripts/nara-command.sh" /usr/local/bin/nara
cp "$source_dir/requirements.txt" /opt/nara-panel/
install -m 755 "$core" /opt/nara-panel/bin/sing-box
if [ -f "$(dirname "$core")/libcronet.so" ]; then
    install -m 755 "$(dirname "$core")/libcronet.so" /opt/nara-panel/bin/libcronet.so
fi
for notice in libcronet.LICENSE SING-BOX-LICENSE SING-BOX-COPYING build.json; do
    if [ -f "$(dirname "$core")/$notice" ]; then
        install -m 644 "$(dirname "$core")/$notice" "/opt/nara-panel/bin/$notice"
    fi
done
install -m 644 "$source_dir/deploy/nara-panel.service" /etc/systemd/system/nara-panel.service
install -m 644 "$source_dir/deploy/nara-panel-access.path" /etc/systemd/system/nara-panel-access.path
install -m 644 "$source_dir/deploy/nara-panel-access.service" /etc/systemd/system/nara-panel-access.service
cd /opt/nara-panel
# An interrupted earlier installation can leave a database without an administrator.
if ! runuser -u nara-panel -- .venv/bin/python -c 'from nara.store import Store; import sys; sys.exit(0 if Store("/var/lib/nara-panel").get("admin") else 1)'; then
    runuser -u nara-panel -- .venv/bin/python -m nara init --data /var/lib/nara-panel </dev/tty
fi
install -m 600 "$setup_dir/panel.env" /etc/nara-panel.env
systemctl daemon-reload
systemctl enable nara-panel nara-panel-access.path
systemctl start nara-panel-access.path
systemctl restart nara-panel
NARA_SETUP_ENV="$setup_dir/panel.env" PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
import ipaddress, os, subprocess, time, urllib.request
from pathlib import Path
from nara.install_config import read_env
settings = read_env(Path(os.environ['NARA_SETUP_ENV']))
port, path = settings['NARA_PORT'], settings['NARA_WEB_PATH']
probe = 'http://127.0.0.1:' + port + path + '/api/health'
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for attempt in range(30):
    try:
        with opener.open(probe, timeout=2) as response:
            if response.status == 200:
                break
    except OSError:
        time.sleep(1)
else:
    raise SystemExit('Service did not become ready. Run: journalctl -u nara-panel -n 50')
print('\nNARA installation complete.')
try:
    addresses = subprocess.check_output(['hostname', '-I'], text=True).split()
    public = [address for address in addresses if ipaddress.ip_address(address).is_global]
    address = (public or addresses)[0]
    if ':' in address:
        address = '[' + address + ']'
except (OSError, subprocess.SubprocessError, IndexError, ValueError):
    address = 'YOUR_SERVER_IP'
if settings.get('NARA_BIND') in ('127.0.0.1', '::1'):
    address = '127.0.0.1'
metadata = Path('/etc/nara-panel/https/current/metadata.json')
if metadata.exists():
    import json
    print('Panel URL: ' + json.loads(metadata.read_text())['url'])
else:
    print('Panel URL: http://' + address + ':' + port + path + '/')
if metadata.exists() and json.loads(metadata.read_text()).get('subscription_url'):
    print('Subscription URL base: ' + json.loads(metadata.read_text())['subscription_url'])
else:
    print('Subscription URL base: http://' + address + ':' + settings['NARA_SUB_PORT'] + settings['NARA_SUB_PATH'] + '/')
print('Allow the subscription TCP port separately when using HTTP.')
print('Saved entry settings: /etc/nara-panel.env')
print('Allow TCP port ' + port + ' in your firewall if using direct access.')
print('Server management menu: sudo nara (includes panel HTTPS setup).')
PY
if [ -f /etc/nara-panel/https/current/metadata.json ]; then
    if ! PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m nara.maintenance restore-https; then
        ui_warn 'Panel installed, but saved HTTPS could not be verified. Use menu 4 to repair the certificate/proxy; direct access remains restricted to the saved bind address.'
    fi
fi
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -c 'from nara.maintenance import Layout, subscription_health; subscription_health(Layout())'
mutating=0
ui_success "NARA is ready. Run sudo nara to reopen the management menu."
