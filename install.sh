#!/usr/bin/env bash
# curl -fsSL https://raw.githubusercontent.com/kevinzakarian/Nara-Panel/main/install.sh | sudo bash
set -euo pipefail
if [[ $(uname -s) != Linux ]]; then echo 'NARA requires Linux.' >&2; exit 1; fi
if [[ $(id -u) != 0 ]]; then echo 'Run this installer as root (or pipe it to sudo bash).' >&2; exit 1; fi
if ! { : </dev/tty; } 2>/dev/null; then echo 'Run from an interactive SSH terminal; webPath, port, and administrator password require a terminal.' >&2; exit 1; fi
if ! command -v apt-get >/dev/null; then echo 'Automatic setup supports Debian 12+ and Ubuntu 22.04+. For other distributions, install the dependencies in README.md and run scripts/install.sh.' >&2; exit 1; fi
command -v systemctl >/dev/null || { echo 'systemd is required.' >&2; exit 1; }
echo 'Installing NARA dependencies...'
apt-get update </dev/null
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv openssl ca-certificates curl git tar gzip </dev/null
python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ is required (Debian 12+ / Ubuntu 22.04+)"'
case $(uname -m) in
    x86_64) go_arch=amd64; go_sha=ecbadb99091a3f46e31f5f934b068b1864eafa7995211b39eaddf76996045fe5 ;;
    aarch64|arm64) go_arch=arm64; go_sha=94f3e30b8e374bc285e7dadc11e0865726b9bc6e85b841ccceaabc0214c6b7c8 ;;
    *) echo 'Automatic setup currently supports amd64 and arm64 Linux.' >&2; exit 1 ;;
esac
work_dir=$(mktemp -d)
trap 'rm -rf "$work_dir"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
echo 'Downloading NARA Panel...'
curl --proto '=https' --tlsv1.2 -fLsS --retry 3 'https://codeload.github.com/kevinzakarian/Nara-Panel/tar.gz/refs/heads/main' -o "$work_dir/source.tar.gz"
tar -xzf "$work_dir/source.tar.gz" -C "$work_dir"
source_dir="$work_dir/Nara-Panel-main"
[[ -f "$source_dir/scripts/install.sh" && -f "$source_dir/nara/server.py" ]] || { echo 'Invalid source archive.' >&2; exit 1; }
# Use an isolated verified toolchain; do not replace the system Go installation.
echo 'Downloading the verified Go build toolchain...'
curl --proto '=https' --tlsv1.2 -fLsS --retry 3 "https://go.dev/dl/go1.27.2.linux-${go_arch}.tar.gz" -o "$work_dir/go.tar.gz"
printf '%s  %s\n' "$go_sha" "$work_dir/go.tar.gz" | sha256sum -c -
tar -xzf "$work_dir/go.tar.gz" -C "$work_dir"
export PATH="$work_dir/go/bin:$PATH"
export GOPATH="$work_dir/gopath"
export GOCACHE="$work_dir/gocache"
sh "$source_dir/scripts/install.sh" </dev/tty
