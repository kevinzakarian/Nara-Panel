"""Panel entry-point validation shared by the server and installer."""
import re
import secrets
import socket
import string


def normalize_web_path(value):
    if value in ("", "/"):
        return ""  # Kept for existing installations and local development.
    segment = value.strip("/")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", segment):
        raise ValueError("webPath must be one segment of 1–64 letters, numbers, hyphens, or underscores")
    return "/" + segment


def random_web_path():
    while True:
        value = "".join(secrets.choice(string.ascii_letters) for _ in range(8))
        if any(c.islower() for c in value) and any(c.isupper() for c in value):
            return "/" + value


def panel_port(value):
    if not re.fullmatch(r"[0-9]{1,5}", str(value)) or not 1 <= int(value) <= 65535:
        raise ValueError("Port must be an integer between 1 and 65535")
    port = int(value)
    if port == 10085:
        raise ValueError("Port 10085 is reserved for the core statistics API")
    return port


def port_available(port):
    try:
        with socket.socket() as sock:
            sock.bind(("0.0.0.0", port))
    except OSError:
        return False
    return True


def ask_configuration(prompt=input, announce=print, available=port_available, defaults=None, keep_panel=False):
    defaults = defaults or {}
    def ask_path(label, default, different=None):
        while True:
            answer = prompt(label + " [" + (default or "Enter = random 8 letters") + "]: ").strip()
            try:
                value = normalize_web_path(answer or default) if answer or default else random_web_path()
                if not value:
                    raise ValueError("Choose a nonempty path")
                if value == different:
                    raise ValueError("webPath and subPath must be different")
                return value
            except ValueError as exc:
                announce(str(exc))
    def ask_port(label, default, excluded):
        while True:
            answer = prompt(label + " [" + str(default) + "]: ").strip()
            try:
                value = panel_port(answer or str(default))
                if value in excluded:
                    raise ValueError("Panel, subscription and statistics ports must be different")
                if not available(value):
                    raise ValueError("This port is already in use; choose another port")
                return value
            except ValueError as exc:
                announce(str(exc))
    if keep_panel and defaults.get("NARA_PORT"):
        path = normalize_web_path(defaults.get("NARA_WEB_PATH", ""))
        port = panel_port(defaults['NARA_PORT'])
        if not available(port):
            raise ValueError("The saved panel port is in use by another process")
    else:
        path = ask_path("Panel webPath", defaults.get("NARA_WEB_PATH"))
        port = ask_port("Panel port", defaults.get("NARA_PORT", 10000), {int(defaults.get("NARA_STATS_PORT", 10085))})
    if keep_panel and defaults.get("NARA_SUB_PATH") and defaults.get("NARA_SUB_PORT"):
        sub_path = normalize_web_path(defaults['NARA_SUB_PATH'])
        sub_port = panel_port(defaults['NARA_SUB_PORT'])
        if not available(sub_port):
            raise ValueError("The saved subscription port is in use by another process")
    else:
        sub_path = ask_path("Subscription subPath", defaults.get("NARA_SUB_PATH"), path)
        sub_port = ask_port("Subscription port", defaults.get("NARA_SUB_PORT", 10001 if port != 10001 else 10002), {port, int(defaults.get("NARA_STATS_PORT", 10085))})
    if path == sub_path or not sub_path or len({port, sub_port, int(defaults.get('NARA_STATS_PORT', 10085))}) != 3:
        raise ValueError("Panel and subscription require different paths and ports")
    return {"NARA_WEB_PATH": path, "NARA_PORT": str(port), "NARA_SUB_PATH": sub_path, "NARA_SUB_PORT": str(sub_port)}


def read_env(path):
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def configure_file(path, keep_panel=False):
    from .runtime import atomic_write
    from .terminal import input_label, styled
    defaults = read_env(path)
    # All interaction uses the controlling terminal, including curl | bash installs.
    with open("/dev/tty", "r") as terminal_input, open("/dev/tty", "w") as terminal_output:
        terminal_output.write("\n" + styled("NARA / Panel entry settings", terminal_output) + "\nPress Enter to accept the value in brackets.\n")
        def prompt(message):
            terminal_output.write("\n" + input_label(message, terminal_output))
            terminal_output.flush()
            line = terminal_input.readline()
            if not line:
                raise ValueError("An interactive terminal is required for installation")
            return line.rstrip("\n")
        def announce(message):
            terminal_output.write(styled("  [!] " + message, terminal_output, "33") + "\n")
        from .maintenance import Layout, configured_inbound_ports
        reserved = configured_inbound_ports(Layout())
        values = ask_configuration(prompt, announce=announce, defaults=defaults, keep_panel=keep_panel,
                                   available=lambda port: port not in reserved and port_available(port))
    values = {**defaults, **values}
    values.setdefault("NARA_BIND", "0.0.0.0")
    values.setdefault("NARA_STATS_PORT", "10085")
    values.setdefault("NARA_SECURE_COOKIE", "0")
    values["NARA_ACCESS_MANAGED"] = "1"
    atomic_write(path, "".join(key + "=" + value + "\n" for key, value in sorted(values.items())))
    path.chmod(0o600)
    return values


if __name__ == "__main__":
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument("env_file", type=Path)
    parser.add_argument("--keep-panel", action="store_true")
    args = parser.parse_args()
    result = configure_file(args.env_file, args.keep_panel)
    print("Panel entry: port " + result["NARA_PORT"] + result["NARA_WEB_PATH"] + "/")
    print("Subscription entry: port " + result["NARA_SUB_PORT"] + result["NARA_SUB_PATH"] + "/")
