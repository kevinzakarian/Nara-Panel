#!/usr/bin/env bash
# curl -fsSL https://raw.githubusercontent.com/kevinzakarian/Nara-Panel/main/install.sh | sudo bash
set -euo pipefail
[[ $(uname -s) == Linux ]] || { echo 'NARA requires Linux.' >&2; exit 1; }
[[ $(id -u) == 0 ]] || { echo 'Run as root (or pipe to sudo bash).' >&2; exit 1; }
if ! { : </dev/tty; } 2>/dev/null; then echo 'Run from an interactive SSH terminal.' >&2; exit 1; fi
command -v apt-get >/dev/null || { echo 'Automatic setup supports Debian 12+ and Ubuntu 22.04+.' >&2; exit 1; }
command -v systemctl >/dev/null || { echo 'systemd is required.' >&2; exit 1; }
exec 9>/run/lock/nara-panel-manager.lock
flock -n 9 || { echo 'Another NARA maintenance session is running.' >&2; exit 1; }
color='' reset=''
if [[ -t 1 && ${TERM:-dumb} != dumb && ! ${NO_COLOR+x} ]]; then color=$'\e[1;36m'; reset=$'\e[0m'; fi
printf '\n%s  NARA / System preparation%s\n\n' "$color" "$reset"
echo 'Refreshing package lists and upgrading installed system packages before opening the menu.'
echo 'This may restart services. The server will not reboot automatically.'
apt-get update </dev/null
DEBIAN_FRONTEND=noninteractive apt-get -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold upgrade -y </dev/null
DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl tar gzip python3 iproute2 tzdata openssh-client </dev/null
work_dir=$(mktemp -d)
trap 'rm -rf "$work_dir"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
curl --proto '=https' --tlsv1.2 -fLsS --retry 3 'https://codeload.github.com/kevinzakarian/Nara-Panel/tar.gz/refs/heads/main' -o "$work_dir/source.tar.gz"
tar -xzf "$work_dir/source.tar.gz" -C "$work_dir"
source_dir="$work_dir/Nara-Panel-main"
[[ -f "$source_dir/scripts/manage.sh" && -f "$source_dir/nara/server.py" ]] || { echo 'Invalid source archive.' >&2; exit 1; }
bash "$source_dir/scripts/manage.sh" --system-prepared --lock-held </dev/tty
