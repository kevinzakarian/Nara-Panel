"""Panel-entry release checks. Never installs or executes downloaded data."""
import json
import re
import threading
import time
import urllib.request
from .network import open_https
from . import __version__

PANEL_URL = "https://api.github.com/repos/kevinzakarian/Nara-Panel/releases/latest"
CORE_URL = "https://api.github.com/repos/SagerNet/sing-box/releases/latest"
MAX_RESPONSE = 2_000_000  # Official releases can contain hundreds of assets.


def version(value):
    match = re.search(r"(?:^|\s|v)(\d+)\.(\d+)\.(\d+)(?:$|\s)", str(value))
    return tuple(map(int, match.groups())) if match else None


def fetch(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Nara-Panel/" + __version__, "Accept": "application/json"})
    with open_https(request, timeout=10) as response:
        if not response.url.startswith("https://"):
            raise ValueError("An HTTPS response is required")
        body = response.read(MAX_RESPONSE + 1)
        if len(body) > MAX_RESPONSE:
            raise ValueError("Release response is too large")
        return json.loads(body)


class UpdateChecker:
    def __init__(self, store):
        self.store = store
        self.lock = threading.Lock()
        self.check_lock = threading.Lock()
        self.running = False

    def start(self):
        """Check once for a panel entry, sharing any check already in flight."""
        with self.lock:
            if self.running:
                return False
            self.running = True
        def run():
            try:
                self.check()
            finally:
                with self.lock:
                    self.running = False
        try:
            threading.Thread(target=run, daemon=True).start()
        except Exception:
            with self.lock:
                self.running = False
            raise
        return True

    def check(self, now=None):
        now = time.time() if now is None else now
        with self.check_lock:
            saved = self.store.get("updates", {})
            saved["attempted_at"] = now
            for key, url in (("panel", PANEL_URL), ("core", CORE_URL)):
                previous = saved.get(key, {})
                try:
                    data = fetch(url)
                    latest = data.get("tag_name")
                    if not version(latest) or data.get("prerelease") or data.get("draft"):
                        raise ValueError("Invalid stable release")
                    saved[key] = {"latest": latest.lstrip("v"), "checked_at": now, "error": ""}
                except Exception:
                    # Keep last known version; network failure never means up to date.
                    saved[key] = {**previous, "error": "Could not check for updates. Sign in or reopen the panel to try again."}
            self.store.set("updates", saved)
            return saved

    def status(self, installed_core):
        saved = self.store.get("updates", {})
        with self.lock:
            checking = self.running
        result = {"attempted_at": saved.get("attempted_at"), "trigger": "panel_entry", "checking": checking}
        for key, installed, url in (("panel", __version__, "https://github.com/kevinzakarian/Nara-Panel"),
                                    ("core", installed_core, "https://github.com/SagerNet/sing-box/releases")):
            item = saved.get(key, {})
            current, latest = version(installed), version(item.get("latest", ""))
            result[key] = {**item, "installed": installed, "available": bool(current and latest and latest > current),
                           "known": bool(current and latest), "url": url}
        return result
