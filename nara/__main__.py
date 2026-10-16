import argparse
import getpass
import os
import signal
import sys
from .store import Store, password_hash
from .runtime import Runtime
from .server import serve
from .install_config import normalize_web_path
from .terminal import input_label


def main():
    parser = argparse.ArgumentParser(description="NARA · Sing-box server panel")
    parser.add_argument("command", choices=("init", "serve", "reset-password"))
    parser.add_argument("--data", default=os.environ.get("NARA_DATA", "./data"))
    parser.add_argument("--bind", default=os.environ.get("NARA_BIND", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("NARA_PORT", "10000")))
    parser.add_argument("--web-path", default=os.environ.get("NARA_WEB_PATH", ""))
    parser.add_argument("--stats-port", type=int, default=int(os.environ.get("NARA_STATS_PORT", "10085")))
    parser.add_argument("--binary", default=os.environ.get("NARA_CORE", "sing-box"))
    parser.add_argument("--username", default="admin")
    args = parser.parse_args()
    try:
        args.web_path = normalize_web_path(args.web_path)
        if not 1 <= args.port <= 65535 or not 1 <= args.stats_port <= 65535 or args.port == args.stats_port:
            raise ValueError("Panel and statistics ports must be different and between 1 and 65535")
    except ValueError as exc:
        parser.error(str(exc))
    os.umask(0o077)
    store = Store(args.data)
    if args.command in ("init", "reset-password"):
        if store.get("admin") and args.command == "init":
            parser.error("Admin already exists. Use reset-password instead.")
        print("\nNARA / Administrator credentials\nPassword input is hidden; no characters will appear while typing.")
        password = getpass.getpass(input_label("Admin password (12+ characters): "))
        if len(password) < 12 or len(password) > 256:
            parser.error("Password must be 12–256 characters.")
        if password != getpass.getpass(input_label("Repeat password: ")):
            parser.error("Passwords do not match.")
        store.set("admin", {"username": args.username, "password": password_hash(password)})
        with store.connect() as db:
            db.execute("DELETE FROM sessions")
        print("Admin saved.")
    else:
        if not store.get("admin"):
            parser.error("Run python3 -m nara init first.")
        # One owner per database; an orphan core is terminated by systemd's cgroup.
        import fcntl
        lock_file = open(store.directory / "panel.lock", "w")
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("Another NARA instance owns this data directory.")
        runtime = Runtime(store, args.binary, args.stats_port)
        def stop(signum, frame):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, stop)
        serve(store, runtime, args.bind, args.port, os.environ.get("NARA_SECURE_COOKIE") == "1", args.web_path)
        lock_file.close()


if __name__ == "__main__":
    main()
