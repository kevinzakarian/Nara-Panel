"""Display installation access details on the controlling terminal only."""
import ipaddress
import json
import os
import subprocess
import sys
from pathlib import Path
from .install_config import read_env
from .maintenance import Layout, database_as_owner, needs_database_owner
from .store import Store
from .terminal import styled


def terminal_text(value):
    # A password is data, never terminal escape instructions.
    return "".join(character if character.isprintable() else ascii(character)[1:-1] for character in str(value))


def administrator(paths=None):
    paths = paths or Layout()
    def read():
        return {"username": Store(paths.data).get("admin")["username"]}
    # Root must not create SQLite WAL/SHM files owned by root in service data.
    return database_as_owner(paths, read) if needs_database_owner(paths) else read()


def entry_urls(settings, metadata=None, addresses=None):
    if addresses is None:
        try:
            addresses = subprocess.check_output(["hostname", "-I"], text=True, stderr=subprocess.DEVNULL).split()
        except (OSError, subprocess.SubprocessError):
            addresses = []
    valid = []
    for address in addresses:
        try:
            valid.append(ipaddress.ip_address(address))
        except ValueError:
            continue
    public = [address for address in valid if address.is_global]
    address = str((public or valid)[0]) if valid else "YOUR_SERVER_IP"
    if settings.get("NARA_BIND") in ("127.0.0.1", "::1"):
        address = settings["NARA_BIND"]
    if ":" in address:
        address = "[" + address + "]"
    metadata = metadata or {}
    panel = metadata.get("url") or "http://" + address + ":" + settings["NARA_PORT"] + settings["NARA_WEB_PATH"] + "/"
    subscription = metadata.get("subscription_url") or "http://" + address + ":" + settings["NARA_SUB_PORT"] + settings["NARA_SUB_PATH"] + "/"
    return panel, subscription


def show_summary(settings, admin, credentials=None, metadata=None, stream=None, addresses=None, reveal=True):
    stream = stream or sys.stdout
    panel, subscription = entry_urls(settings, metadata, addresses)
    def line(label, value, color):
        print(styled("  " + label + ": " + terminal_text(value), stream, color), file=stream)
    print(styled("\n  NARA / Installation complete\n", stream, "32"), file=stream)
    line("Panel URL", panel, "36")
    line("Username", admin["username"], "32")
    if credentials and credentials.get("username") == admin["username"]:
        line("Password", credentials["password"] if reveal else "Set during installation (shown only in the terminal)", "33")
    else:
        line("Password", "Unchanged — use your existing password", "33")
    line("Subscription URL base", subscription, "36")
    print("\n  Allow the panel and subscription TCP ports in your firewall.", file=stream)
    print("  Entry settings: /etc/nara-panel.env", file=stream)
    print("  Server management menu: sudo nara\n", file=stream)


def main():
    settings = read_env(Path(os.environ["NARA_SETUP_ENV"]))
    credential_path = Path(os.environ["NARA_SETUP_CREDENTIALS"]) if os.environ.get("NARA_SETUP_CREDENTIALS") else None
    try:
        credentials = json.loads(credential_path.read_text()) if credential_path else None
        metadata_path = Path("/etc/nara-panel/https/current/metadata.json")
        metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
        admin = administrator()
        try:
            terminal = open("/dev/tty", "w")
        except OSError:
            # Never leak a newly chosen password into redirected install logs.
            show_summary(settings, admin, credentials, metadata, reveal=False)
            print("No controlling terminal: the new password was not displayed.")
        else:
            with terminal:
                show_summary(settings, admin, credentials, metadata, terminal)
    finally:
        if credential_path:
            credential_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
