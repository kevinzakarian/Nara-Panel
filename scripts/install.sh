#!/bin/sh
set -eu
[ "$(uname -s)" = Linux ] || { echo "This installer requires Linux." >&2; exit 1; }
[ "$(id -u)" = 0 ] || { echo "Run as root or with sudo." >&2; exit 1; }
command -v systemctl >/dev/null || { echo "systemd is required." >&2; exit 1; }
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ is required"'
command -v openssl >/dev/null || { echo "Install OpenSSL first." >&2; exit 1; }
# Stage configuration: failed installs never overwrite the live entry URL.
setup_dir=$(mktemp -d)
was_running=0
cleanup() {
    status=$?
    trap - EXIT
    if [ "$status" -ne 0 ] && [ "$was_running" = 1 ]; then systemctl start nara-panel || true; fi
    rm -rf "$setup_dir"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if [ -f /etc/nara-panel.env ]; then cp /etc/nara-panel.env "$setup_dir/panel.env"; fi
# Stop only NARA's own service so its existing port can be retained on upgrades.
if systemctl is-active --quiet nara-panel; then
    was_running=1
    systemctl stop nara-panel
fi
cd "$source_dir"
PYTHONDONTWRITEBYTECODE=1 python3 -m nara.install_config "$setup_dir/panel.env"
core=${NARA_INSTALL_CORE:-$source_dir/dist/sing-box}
if [ ! -x "$core" ]; then
    echo "Building the Sing-box core with per-client statistics. This may take several minutes..."
    CGO_ENABLED=0 sh "$source_dir/scripts/build-core.sh" "$core" </dev/null
fi
"$core" version | grep -q with_v2ray_api || { echo "The core requires with_v2ray_api." >&2; exit 1; }
"$core" version | grep -q with_quic || { echo "The core requires with_quic." >&2; exit 1; }
id nara-panel >/dev/null 2>&1 || useradd --system --home-dir /var/lib/nara-panel --shell /usr/sbin/nologin nara-panel
install -d -m 755 /opt/nara-panel /opt/nara-panel/bin
install -d -o nara-panel -g nara-panel -m 700 /var/lib/nara-panel
python3 -m venv /opt/nara-panel/.venv
/opt/nara-panel/.venv/bin/python -m pip install --disable-pip-version-check -r "$source_dir/requirements.txt" </dev/null
cp -R "$source_dir/nara" "$source_dir/web" /opt/nara-panel/
cp "$source_dir/requirements.txt" /opt/nara-panel/
install -m 755 "$core" /opt/nara-panel/bin/sing-box
if [ -f "$(dirname "$core")/libcronet.so" ]; then
    install -m 755 "$(dirname "$core")/libcronet.so" /opt/nara-panel/bin/libcronet.so
    install -m 644 "$(dirname "$core")/libcronet.LICENSE" /opt/nara-panel/bin/libcronet.LICENSE
fi
install -m 644 "$source_dir/deploy/nara-panel.service" /etc/systemd/system/nara-panel.service
cd /opt/nara-panel
# An interrupted earlier installation can leave a database without an administrator.
if ! runuser -u nara-panel -- .venv/bin/python -c 'from nara.store import Store; import sys; sys.exit(0 if Store("/var/lib/nara-panel").get("admin") else 1)'; then
    runuser -u nara-panel -- .venv/bin/python -m nara init --data /var/lib/nara-panel </dev/tty
fi
install -m 600 "$setup_dir/panel.env" /etc/nara-panel.env
systemctl daemon-reload
systemctl enable nara-panel
systemctl restart nara-panel
NARA_SETUP_ENV="$setup_dir/panel.env" PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
import ipaddress, os, subprocess, time, urllib.request
from pathlib import Path
from nara.install_config import read_env
settings = read_env(Path(os.environ['NARA_SETUP_ENV']))
port, path = settings['NARA_PORT'], settings['NARA_WEB_PATH']
probe = 'http://127.0.0.1:' + port + path + '/api/health'
for attempt in range(30):
    try:
        with urllib.request.urlopen(probe, timeout=2) as response:
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
print('Panel URL: http://' + address + ':' + port + path + '/')
print('Saved entry settings: /etc/nara-panel.env')
print('Allow TCP port ' + port + ' in your firewall if using direct access.')
print('For public HTTPS, put a reverse proxy in front and enable NARA_SECURE_COOKIE=1.')
PY
