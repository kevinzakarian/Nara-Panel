#!/usr/bin/env bash
# Update application code using the installed core and existing panel settings.
set -euo pipefail
[[ $(uname -s) == Linux && $(id -u) == 0 ]] || { echo 'Run this updater as root on the Linux server.' >&2; exit 1; }
app_dir=/opt/nara-panel
[[ -x "$app_dir/.venv/bin/python" && -d "$app_dir/nara" && -d "$app_dir/web" ]] || { echo 'NARA is not installed. Run install.sh first.' >&2; exit 1; }
work_dir=$(mktemp -d)
rollback_needed=0
was_running=0
if systemctl is-active --quiet nara-panel; then was_running=1; fi
cleanup() {
    status=$?
    trap - EXIT
    if [[ $status != 0 && $rollback_needed == 1 ]]; then
        echo 'Update failed; restoring the previous application code.' >&2
        systemctl stop nara-panel || true
        cp -R "$work_dir/backup/nara" "$work_dir/backup/web" "$app_dir/"
        if [[ $was_running == 1 ]]; then systemctl start nara-panel || true; fi
    fi
    rm -rf "$work_dir"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
curl --proto '=https' --tlsv1.2 -fLsS --retry 3 'https://codeload.github.com/kevinzakarian/Nara-Panel/tar.gz/refs/heads/main' -o "$work_dir/source.tar.gz"
tar -xzf "$work_dir/source.tar.gz" -C "$work_dir"
source_dir="$work_dir/Nara-Panel-main"
[[ -f "$source_dir/nara/server.py" && -f "$source_dir/web/index.html" ]] || { echo 'Invalid source archive.' >&2; exit 1; }
if ! cmp -s "$source_dir/requirements.txt" "$app_dir/requirements.txt"; then
    echo 'Dependencies changed. Use the full installer for this update.' >&2
    exit 1
fi
PYTHONPYCACHEPREFIX="$work_dir/pycache" "$app_dir/.venv/bin/python" -m compileall -q "$source_dir/nara"
mkdir "$work_dir/backup"
cp -R "$app_dir/nara" "$app_dir/web" "$work_dir/backup/"
systemctl stop nara-panel
rollback_needed=1
cp -R "$source_dir/nara" "$source_dir/web" "$app_dir/"
chmod -R u=rwX,go=rX "$app_dir/nara" "$app_dir/web"
systemctl start nara-panel
cd "$app_dir"
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
import json, time, urllib.request
from pathlib import Path
from nara import __version__
from nara.install_config import read_env
settings = read_env(Path('/etc/nara-panel.env'))
url = 'http://127.0.0.1:' + settings.get('NARA_PORT', '10000') + settings.get('NARA_WEB_PATH', '') + '/api/health'
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for attempt in range(30):
    try:
        with opener.open(url, timeout=2) as response:
            if response.status == 200 and json.load(response).get('version') == __version__:
                print('NARA updated to ' + __version__ + '. Your panel URL, accounts, and core settings are preserved.')
                break
    except (OSError, ValueError):
        time.sleep(1)
else:
    raise SystemExit('Service did not become ready. Review: journalctl -u nara-panel -n 50')
PY
rollback_needed=0
