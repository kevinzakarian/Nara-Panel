import contextlib
import hashlib
import hmac
import json
import secrets
import sqlite3
import time
from pathlib import Path
from .config import initial_state, normalize_dns_record


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 600_000).hex()
    return "pbkdf2_sha256:600000:" + salt + ":" + digest


def password_matches(password, encoded):
    return hmac.compare_digest(password_hash(password, encoded.split(":")[2]), encoded)


class Store:
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        self.path = self.directory / "panel.sqlite3"
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS traffic(id TEXT PRIMARY KEY, upload INTEGER NOT NULL DEFAULT 0,
                    download INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS api_keys(id TEXT PRIMARY KEY, hash TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
                    scopes TEXT NOT NULL, created REAL NOT NULL, expires REAL NOT NULL, last_used REAL, revoked INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, event TEXT NOT NULL, payload TEXT NOT NULL,
                    created REAL NOT NULL, attempts INTEGER DEFAULT 0, available REAL DEFAULT 0, status TEXT DEFAULT 'queued');
                CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, at REAL, message TEXT);
            """)
            db.execute("INSERT OR IGNORE INTO kv VALUES('state', ?)", (json.dumps(initial_state()),))
        self.path.chmod(0o600)

    @contextlib.contextmanager
    def connect(self):
        db = sqlite3.connect(str(self.path), timeout=15)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            value = json.loads(row[0]) if row else default
            if key in ("state", "active") and isinstance(value, dict):
                for name, initial in initial_state().items():
                    value.setdefault(name, initial)
                value["dns_servers"] = [normalize_dns_record(row) for row in value["dns_servers"]]
                for client in value.get("clients", []):
                    if "note" in client and client["note"] is None: client["note"] = ""
            return value

    def set(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO kv VALUES(?,?)", (key, json.dumps(value)))

    def commit_configuration(self, state, save=False, reset_client=None):
        """Publish the active model, optional edits, and a usage reset together."""
        with self.connect() as db:
            records = [("active", state), ("autostart", True)]
            if save:
                records.append(("state", state))
            for key, value in records:
                db.execute("INSERT OR REPLACE INTO kv VALUES(?,?)", (key, json.dumps(value)))
            if reset_client:
                for client_id in reset_client if isinstance(reset_client, list) else [reset_client]:
                    db.execute("DELETE FROM traffic WHERE id=?", (client_id,))

    def audit(self, message):
        with self.connect() as db:
            db.execute("INSERT INTO audit(at, message) VALUES(?,?)", (time.time(), message))
            db.execute("DELETE FROM audit WHERE id NOT IN (SELECT id FROM audit ORDER BY id DESC LIMIT 300)")

    def events(self):
        with self.connect() as db:
            return [{"at": r[0], "message": r[1]} for r in db.execute("SELECT at,message FROM audit ORDER BY id DESC LIMIT 20")]

    def totals(self):
        with self.connect() as db:
            return {r[0]: {"upload": r[1], "download": r[2]} for r in db.execute("SELECT id,upload,download FROM traffic")}

    def add_traffic(self, deltas):
        with self.connect() as db:
            for client_id, direction, value in deltas:
                if direction not in ("upload", "download") or value < 0:
                    raise ValueError("Invalid traffic counter")
                db.execute("INSERT OR IGNORE INTO traffic(id) VALUES(?)", (client_id,))
                db.execute("UPDATE traffic SET " + direction + "=" + direction + "+? WHERE id=?", (value, client_id))

    def session(self, raw):
        with self.connect() as db:
            row = db.execute("SELECT csrf,expires FROM sessions WHERE token=?", (hashlib.sha256(raw.encode()).hexdigest(),)).fetchone()
            return {"csrf": row[0], "expires": row[1]} if row and row[1] > time.time() else None

    def new_session(self):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute("DELETE FROM kv WHERE key IN (SELECT 'reauth:' || token FROM sessions WHERE expires<?)", (time.time(),))
            db.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
            db.execute("INSERT INTO sessions VALUES(?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), csrf, time.time() + 43200))
        return token, csrf

    def logout(self, raw):
        with self.connect() as db:
            hashed = hashlib.sha256(raw.encode()).hexdigest()
            db.execute("DELETE FROM kv WHERE key=?", ("reauth:" + hashed,))
            db.execute("DELETE FROM sessions WHERE token=?", (hashed,))
