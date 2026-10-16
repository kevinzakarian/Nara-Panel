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


def ask_configuration(prompt=input, announce=print, available=port_available, defaults=None):
    defaults = defaults or {}
    while True:
        path_default = defaults.get("NARA_WEB_PATH")
        answer = prompt("Panel webPath [{}]: ".format(path_default or "Enter = random 8 letters" )).strip()
        try:
            path = normalize_web_path(answer or path_default) if answer or path_default else random_web_path()
            if not path:
                raise ValueError("Choose a nonempty webPath")
            break
        except ValueError as exc:
            announce(str(exc))
    while True:
        port_default = defaults.get("NARA_PORT", "10000")
        answer = prompt("Panel port [{}]: ".format(port_default)).strip()
        try:
            port = panel_port(answer or port_default)
            if port == int(defaults.get("NARA_STATS_PORT", "10085")):
                raise ValueError("This port is reserved for the core statistics API")
            if not available(port):
                raise ValueError("This port is already in use; choose another port")
            break
        except ValueError as exc:
            announce(str(exc))
    return {"NARA_WEB_PATH": path, "NARA_PORT": str(port)}


def read_env(path):
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if line and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def configure_file(path):
    from .runtime import atomic_write
    defaults = read_env(path)
    # All interaction uses the controlling terminal, including curl | bash installs.
    with open("/dev/tty", "r") as terminal_input, open("/dev/tty", "w") as terminal_output:
        def prompt(message):
            terminal_output.write(message)
            terminal_output.flush()
            line = terminal_input.readline()
            if not line:
                raise ValueError("An interactive terminal is required for installation")
            return line.rstrip("\n")
        values = ask_configuration(prompt, defaults=defaults)
    values = {**defaults, **values}
    values.setdefault("NARA_BIND", "0.0.0.0")
    values.setdefault("NARA_STATS_PORT", "10085")
    values.setdefault("NARA_SECURE_COOKIE", "0")
    atomic_write(path, "".join(key + "=" + value + "\n" for key, value in sorted(values.items())))
    path.chmod(0o600)
    return values


if __name__ == "__main__":
    import argparse
    from pathlib import Path
    parser = argparse.ArgumentParser()
    parser.add_argument("env_file", type=Path)
    args = parser.parse_args()
    result = configure_file(args.env_file)
    print("Panel entry: port " + result["NARA_PORT"] + result["NARA_WEB_PATH"] + "/")
