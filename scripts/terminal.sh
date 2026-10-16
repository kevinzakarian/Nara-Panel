#!/bin/sh
# Shared terminal presentation. NO_COLOR and dumb terminals remain readable.
ui_init() {
    UI_BOLD='' UI_RESET='' UI_CYAN='' UI_GREEN='' UI_YELLOW='' UI_RED=''
    if [ -t 1 ] && [ "${TERM:-dumb}" != dumb ] && [ -z "${NO_COLOR+x}" ]; then
        UI_BOLD=$(printf '\033[1m'); UI_RESET=$(printf '\033[0m')
        UI_CYAN=$(printf '\033[36m'); UI_GREEN=$(printf '\033[32m')
        UI_YELLOW=$(printf '\033[33m'); UI_RED=$(printf '\033[31m')
    fi
}
ui_title() { printf '\n%s%s  NARA  /  %s%s\n\n' "$UI_BOLD" "$UI_CYAN" "$1" "$UI_RESET"; }
ui_info() { printf '%s  > %s%s\n' "$UI_CYAN" "$*" "$UI_RESET"; }
ui_success() { printf '%s  [OK] %s%s\n' "$UI_GREEN" "$*" "$UI_RESET"; }
ui_warn() { printf '%s  [!] %s%s\n' "$UI_YELLOW" "$*" "$UI_RESET"; }
ui_error() { printf '%s  [ERROR] %s%s\n' "$UI_RED" "$*" "$UI_RESET" >&2; }
# Always read from the controlling terminal: curl | bash owns stdin.
ui_ask() {
    printf '\n%s%s  [INPUT] %s%s ' "$UI_BOLD" "$UI_CYAN" "$1" "$UI_RESET" >/dev/tty || return 1
    IFS= read -r REPLY </dev/tty || return 1
}
ui_pause() { ui_ask 'Press Enter to return to the menu.'; }
ui_init
