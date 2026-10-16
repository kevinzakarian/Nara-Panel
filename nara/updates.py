"""Daily, read-only release checks. Never installs or executes downloaded data."""
import json
import re
import threading
import time
import urllib.request
from . import __version__

PANEL_URL = "https://api.github.com/repos/kevinzakarian/Nara-Panel/contents/release.json?ref=main"
CORE_URL = "https://api.github.com/repos/SagerNet/sing-box/releases/latest"
DAY = 86400
MAX_RESPONSE = 2_000_000  # Official releases can contain hundreds of assets.


def version(value):
    match = re.search(r"(?:^|\s|v)(\d+)\.(\d+)\.(\d+)(?:$|\s)", str(value))
    return tuple(map(int, match.groups())) if match else None


def fetch(url):
    accept = "application/vnd.github.raw+json" if url == PANEL_URL else "application/json"
    request = urllib.request.Request(url, headers={"User-Agent": "Nara-Panel/" + __version__, "Accept": accept})
    with urllib.request.urlopen(request, timeout=10) as response:
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
        self.shutdown = threading.Event()

    def check(self, now=None):
        now = time.time() if now is None else now
        with self.lock:
            saved = self.store.get("updates", {})
            if saved.get("attempted_at") and now - saved["attempted_at"] < DAY:
                return saved
            saved["attempted_at"] = now
            for key, url in (("panel", PANEL_URL), ("core", CORE_URL)):
                previous = saved.get(key, {})
                try:
                    data = fetch(url)
                    latest = data.get("version") if key == "panel" else data.get("tag_name")
                    if not version(latest) or data.get("prerelease") or data.get("draft"):
                        raise ValueError("Invalid stable release")
                    saved[key] = {"latest": latest.lstrip("v"), "checked_at": now, "error": ""}
                except Exception:
                    # Keep last known version; network failure never means up to date.
                    saved[key] = {**previous, "error": "Could not check for updates. Next automatic check is within 24 hours."}
            self.store.set("updates", saved)
            return saved

    def status(self, installed_core):
        saved = self.store.get("updates", {})
        result = {"attempted_at": saved.get("attempted_at"), "interval_hours": 24}
        for key, installed, url in (("panel", __version__, "https://github.com/kevinzakarian/Nara-Panel"),
                                    ("core", installed_core, "https://github.com/SagerNet/sing-box/releases")):
            item = saved.get(key, {})
            current, latest = version(installed), version(item.get("latest", ""))
            result[key] = {**item, "installed": installed, "available": bool(current and latest and latest > current),
                           "known": bool(current and latest), "url": url}
        return result

    def worker(self):
        while not self.shutdown.is_set():
            self.check()
            self.shutdown.wait(60)
