#!/usr/bin/env bash
# Update application code using the installed core and existing panel settings.
set -euo pipefail
[[ $(uname -s) == Linux && $(id -u) == 0 ]] || { echo 'Run this updater as root on the Linux server.' >&2; exit 1; }
if [[ ${NARA_MANAGER_LOCK_HELD:-0} != 1 ]]; then
    exec 9>/run/lock/nara-panel-manager.lock
    flock -n 9 || { echo 'Another NARA maintenance session is running.' >&2; exit 1; }
fi
app_dir=/opt/nara-panel
[[ -x "$app_dir/.venv/bin/python" && -d "$app_dir/nara" && -d "$app_dir/web" ]] || { echo 'NARA is not installed. Run install.sh first.' >&2; exit 1; }
work_dir=$(mktemp -d)
rollback_needed=0
was_running=0
was_access_running=0
if systemctl is-active --quiet nara-panel-access.path; then was_access_running=1; fi
if systemctl is-active --quiet nara-panel; then was_running=1; fi
cleanup() {
    status=$?
    trap - EXIT
    if [[ $status != 0 && $rollback_needed == 1 ]]; then
        echo 'Update failed; restoring the previous application code.' >&2
        systemctl stop nara-panel || true
        systemctl stop nara-panel-access.path || true
        if [[ -f "$work_dir/backup/urls.json" ]]; then
            (cd "$app_dir" && .venv/bin/python -m nara.access restore-urls --snapshot "$work_dir/backup/urls.json") || true
        fi
        if [[ -f "$work_dir/backup/panel.env" ]]; then cp -p "$work_dir/backup/panel.env" /etc/nara-panel.env; fi
        for suffix in path service; do
            if [[ -f "$work_dir/backup/access.$suffix" ]]; then cp -p "$work_dir/backup/access.$suffix" "/etc/systemd/system/nara-panel-access.$suffix";
            else rm -f "/etc/systemd/system/nara-panel-access.$suffix"; fi
        done
        if [[ $was_access_running == 0 ]]; then systemctl disable nara-panel-access.path || true; fi
        for item in Caddyfile metadata.json; do
            if [[ -f "$work_dir/backup/$item" ]]; then cp -p "$work_dir/backup/$item" "/etc/nara-panel/https/current/$item"; fi
        done
        systemctl daemon-reload || true
        if [[ $was_access_running == 1 ]]; then systemctl start nara-panel-access.path || true; fi
        if [[ -f "$work_dir/backup/Caddyfile" ]]; then systemctl restart nara-panel-https || true; fi
        for item in nara web scripts; do
            rm -rf "$app_dir/$item"
            if [[ -d "$work_dir/backup/$item" ]]; then cp -R "$work_dir/backup/$item" "$app_dir/"; fi
        done
        if [[ -f "$work_dir/backup/manager-command" ]]; then
            install -m 755 "$work_dir/backup/manager-command" /usr/local/bin/nara
        else
            rm -f /usr/local/bin/nara
        fi
        if [[ $was_running == 1 ]]; then systemctl start nara-panel || true; fi
    fi
    rm -rf "$work_dir"
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
if [[ ${1:-} == --source && $# == 2 ]]; then
    source_dir=$(cd -- "$2" && pwd)
elif [[ $# == 0 ]]; then
    curl --proto '=https' --tlsv1.2 -fLsS --retry 3 'https://codeload.github.com/kevinzakarian/Nara-Panel/tar.gz/refs/heads/main' -o "$work_dir/source.tar.gz"
    tar -xzf "$work_dir/source.tar.gz" -C "$work_dir"
    source_dir="$work_dir/Nara-Panel-main"
else
    echo 'Usage: update.sh [--source /path/to/trusted/source]' >&2
    exit 1
fi
[[ -f "$source_dir/nara/server.py" && -f "$source_dir/web/index.html" ]] || { echo 'Invalid source archive.' >&2; exit 1; }
if ! cmp -s "$source_dir/requirements.txt" "$app_dir/requirements.txt"; then
    echo 'Dependencies changed. Use the full installer for this update.' >&2
    exit 1
fi
PYTHONPYCACHEPREFIX="$work_dir/pycache" "$app_dir/.venv/bin/python" -m compileall -q "$source_dir/nara"
mkdir "$work_dir/backup"
cp -R "$app_dir/nara" "$app_dir/web" "$work_dir/backup/"
if [[ -d "$app_dir/scripts" ]]; then cp -R "$app_dir/scripts" "$work_dir/backup/"; fi
if [[ -f /usr/local/bin/nara ]]; then cp /usr/local/bin/nara "$work_dir/backup/manager-command"; fi
if [[ -f /etc/nara-panel.env ]]; then cp -p /etc/nara-panel.env "$work_dir/backup/panel.env"; fi
for suffix in path service; do
    if [[ -f "/etc/systemd/system/nara-panel-access.$suffix" ]]; then cp -p "/etc/systemd/system/nara-panel-access.$suffix" "$work_dir/backup/access.$suffix"; fi
done
for item in Caddyfile metadata.json; do
    if [[ -f "/etc/nara-panel/https/current/$item" ]]; then cp -p "/etc/nara-panel/https/current/$item" "$work_dir/backup/"; fi
done
# Run the new source's owner-safe snapshot against the existing database.
(cd "$source_dir" && "$app_dir/.venv/bin/python" -m nara.access snapshot) > "$work_dir/backup/urls.json"
systemctl stop nara-panel
rollback_needed=1
for item in nara web scripts; do
    rm -rf "$app_dir/$item"
    cp -R "$source_dir/$item" "$app_dir/"
done
install -m 755 "$source_dir/scripts/nara-command.sh" /usr/local/bin/nara
chmod -R u=rwX,go=rX "$app_dir/nara" "$app_dir/web"
(cd "$app_dir" && .venv/bin/python -m nara.access migrate)
install -m 644 "$source_dir/deploy/nara-panel-access.path" /etc/systemd/system/nara-panel-access.path
install -m 644 "$source_dir/deploy/nara-panel-access.service" /etc/systemd/system/nara-panel-access.service
systemctl daemon-reload
systemctl enable --now nara-panel-access.path
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
if [[ -f /etc/nara-panel/https/current/metadata.json ]]; then
    .venv/bin/python -m nara.maintenance restore-https
fi
.venv/bin/python -c 'from nara.maintenance import Layout, subscription_health; subscription_health(Layout())'
echo 'Share refreshed subscription links/QR codes; subscriptions now use their own path and port.'
rollback_needed=0
