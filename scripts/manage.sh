#!/usr/bin/env bash
# Interactive Linux lifecycle manager, also installed as /usr/local/bin/nara.
set -euo pipefail
manager_source=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
source "$manager_source/scripts/terminal.sh"
app_dir=/opt/nara-panel
manager_work=''

require_installed() {
    [[ -x "$app_dir/.venv/bin/python" && -d "$app_dir/nara" ]] || { ui_error 'NARA is not installed. Choose New installation first.'; return 1; }
}
manager_python() { (cd "$manager_source" && PYTHONDONTWRITEBYTECODE=1 "$app_dir/.venv/bin/python" -m nara.maintenance "$@"); }
prepare_system() {
    ui_title 'System preparation'
    ui_warn 'Upgrading installed system packages. Services may restart; the server will not reboot automatically.'
    apt-get update </dev/null
    DEBIAN_FRONTEND=noninteractive apt-get -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold upgrade -y </dev/null
    DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates curl tar gzip python3 </dev/null
}
latest_source() {
    [[ -z "$manager_work" ]] || return 0
    manager_work=$(mktemp -d)
    ui_info 'Downloading the latest NARA release...'
    curl --proto '=https' --tlsv1.2 -fLsS --retry 3 'https://codeload.github.com/kevinzakarian/Nara-Panel/tar.gz/refs/heads/main' -o "$manager_work/source.tar.gz"
    tar -xzf "$manager_work/source.tar.gz" -C "$manager_work"
    latest_dir="$manager_work/Nara-Panel-main"
    [[ -f "$latest_dir/scripts/install.sh" && -f "$latest_dir/nara/server.py" && -f "$latest_dir/scripts/manage.sh" ]] || { ui_error 'Invalid source archive.'; return 1; }
}
prepare_build() {
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv openssl git </dev/null
    python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ is required"'
    local arch digest
    case $(uname -m) in
        x86_64) arch=amd64; digest=ecbadb99091a3f46e31f5f934b068b1864eafa7995211b39eaddf76996045fe5 ;;
        aarch64|arm64) arch=arm64; digest=94f3e30b8e374bc285e7dadc11e0865726b9bc6e85b841ccceaabc0214c6b7c8 ;;
        *) ui_error 'Automatic builds support amd64 and arm64.'; return 1 ;;
    esac
    if [[ ! -x "$manager_work/go/bin/go" ]]; then
        ui_info 'Downloading the verified, isolated Go toolchain...'
        curl --proto '=https' --tlsv1.2 -fLsS --retry 3 "https://go.dev/dl/go1.27.2.linux-${arch}.tar.gz" -o "$manager_work/go.tar.gz"
        printf '%s  %s\n' "$digest" "$manager_work/go.tar.gz" | sha256sum -c -
        tar -xzf "$manager_work/go.tar.gz" -C "$manager_work"
    fi
}
full_install() {
    latest_source
    prepare_build
    PATH="$manager_work/go/bin:$PATH" GOPATH="$manager_work/gopath" GOCACHE="$manager_work/gocache" NARA_KEEP_ENTRY=1 NARA_MANAGER_LOCK_HELD=1 sh "$latest_dir/scripts/install.sh" </dev/tty
}
backup_installed() {
    # Old versions do not yet include the maintenance module.
    (cd "$latest_dir" && PYTHONDONTWRITEBYTECODE=1 python3 -m nara.maintenance backup)
}
install_new() {
    if [[ -d "$app_dir/nara" ]]; then
        ui_warn 'NARA is already installed. Use an upgrade option to preserve it.'
        return 1
    fi
    if [[ -e /etc/nara-panel.env || -d /var/lib/nara-panel ]]; then ui_info 'Saved data found. Reinstalling will preserve it.'; fi
    full_install
}
upgrade_full() {
    require_installed
    latest_source
    ui_warn 'Panel and core will restart. Existing accounts, settings, HTTPS, port and webPath are retained.'
    backup_installed
    full_install
}
upgrade_panel() {
    require_installed
    latest_source
    backup_installed
    NARA_MANAGER_LOCK_HELD=1 bash "$latest_dir/update.sh" --source "$latest_dir"
}
https_menu() {
    require_installed
    ui_title 'Panel HTTPS / Certificate'
    printf '  1  Trusted domain certificate + automatic renewal\n  2  Self-signed certificate for a domain or IP\n  3  Import an existing PEM certificate and private key\n  4  HTTPS status and certificate details\n  0  Back\n'
    ui_ask 'Choose an option [0]: ' || return
    case ${REPLY:-0} in
        1) manager_python https automatic ;;
        2) manager_python https self-signed ;;
        3) manager_python https import ;;
        4) manager_python https-status ;;
        0) return ;;
        *) ui_error 'Choose a number from the menu.'; return 1 ;;
    esac
}
reset_password() {
    require_installed
    ui_warn 'All current administrator sessions will be signed out. Client accounts are preserved.'
    (cd "$app_dir" && runuser -u nara-panel -- .venv/bin/python -m nara reset-password --data /var/lib/nara-panel </dev/tty)
}
uninstall_panel() {
    require_installed
    ui_title 'Uninstall NARA'
    ui_warn 'This stops the panel, its core and its dedicated HTTPS proxy.'
    printf '  1  Remove application; keep private data, entry settings and certificates\n  2  Remove application and permanently delete its data/settings/certificates\n  0  Cancel\n'
    ui_warn 'Existing backup archives are retained in /var/backups/nara-panel for both options.'
    ui_ask 'Choose an option [0]: ' || return
    local mode=${REPLY:-0}
    [[ "$mode" != 0 ]] || return 0
    [[ "$mode" == 1 || "$mode" == 2 ]] || { ui_error 'Invalid choice.'; return 1; }
    local token=UNINSTALL
    [[ "$mode" != 2 ]] || token='DELETE NARA DATA'
    ui_ask "Type $token to confirm:" || return
    [[ "$REPLY" == "$token" ]] || { ui_warn 'Cancelled; nothing removed.'; return 0; }
    manager_python uninstall "$mode"
}
show_menu() {
    ui_title 'Server manager'
    if [[ -x "$app_dir/.venv/bin/python" ]]; then manager_python versions || true; else ui_info 'NARA is not installed.'; fi
    if [[ -f /var/run/reboot-required ]]; then ui_warn 'System updates require a reboot. Reboot manually when convenient.'; fi
    printf '\n  1   New installation\n  2   Upgrade panel only (keep current core)\n  3   Upgrade panel + rebuild bundled compatible core\n  4   Panel HTTPS / Certificate\n  5   Service status and entry URL\n  6   Restart panel service\n  7   Stop panel and core\n  8   Start panel service\n  9   Recent logs\n  10  Create a private backup\n  11  Change administrator password\n  12  Uninstall NARA\n  0   Exit\n'
}
manager_main() {
    [[ $(uname -s) == Linux && $(id -u) == 0 ]] || { ui_error 'Run as root on a Linux server.'; return 1; }
    command -v apt-get >/dev/null && command -v systemctl >/dev/null || { ui_error 'Debian 12+ / Ubuntu 22.04+ with systemd is required.'; return 1; }
    if ! { : </dev/tty; } 2>/dev/null; then ui_error 'An interactive SSH terminal is required.'; return 1; fi
    local prepared=0 locked=0 option
    for option in "$@"; do case "$option" in --system-prepared) prepared=1 ;; --lock-held) locked=1 ;; *) ui_error 'Unexpected argument.'; return 1 ;; esac; done
    if [[ "$locked" == 0 ]]; then exec 9>/run/lock/nara-panel-manager.lock; flock -n 9 || { ui_error 'Another NARA maintenance session is running.'; return 1; }; fi
    trap '[[ -z "$manager_work" ]] || rm -rf "$manager_work"' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    [[ "$prepared" == 1 ]] || prepare_system
    while true; do
        show_menu
        ui_ask 'Choose an option [0]:' || break
        option=${REPLY:-0}
        [[ "$option" != 0 ]] || break
        # Use a subshell with errexit active: a failed action never falls through.
        set +e
        (
            set -e
            trap '[[ -z "$manager_work" ]] || rm -rf "$manager_work"' EXIT
            case "$option" in
                1) install_new ;; 2) upgrade_panel ;; 3) upgrade_full ;; 4) https_menu ;;
                5) require_installed; manager_python status ;;
                6) require_installed; systemctl restart nara-panel; manager_python health; ui_success 'Panel service restarted. The core follows its saved start/stop state.' ;;
                7) require_installed; systemctl stop nara-panel; ui_success 'Panel and core stopped. HTTPS proxy, if configured, remains running.' ;;
                8) require_installed; systemctl start nara-panel; manager_python health; ui_success 'Panel service started. The core follows its saved start/stop state.' ;;
                9) require_installed; journalctl -u nara-panel -u nara-panel-https -n 60 --no-pager ;;
                10) require_installed; manager_python backup ;; 11) reset_password ;; 12) uninstall_panel ;;
                *) ui_error 'Choose a number from the menu.'; exit 1 ;;
            esac
        )
        action_status=$?
        set -e
        if [[ "$action_status" != 0 ]]; then ui_error 'Action did not complete. Read the error above; the menu is still available.'; fi
        [[ -d "$app_dir/nara" || "$option" != 12 || "$action_status" != 0 ]] || break
        ui_pause || break
    done
}
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then manager_main "$@"; fi
