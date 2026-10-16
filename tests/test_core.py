"""Loopback integration tests. Never changes routes, firewall, or host DNS."""
import copy
import json
import os
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from nara.config import build_config, client_config
from nara.runtime import Runtime, atomic_write
from nara.server import self_signed
from nara.store import Store
from tests.helpers import example_state, free_port

CORE = os.environ.get("SING_BOX_TEST_BINARY")


class Target(BaseHTTPRequestHandler):
    def do_GET(self):
        payload = b"NARA traffic accounting test.\n" * 2048
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


@unittest.skipUnless(CORE, "Set SING_BOX_TEST_BINARY for real-core integration tests")
class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = self_signed({"server_name": "127.0.0.1", "days": 1})
        cls.target = ThreadingHTTPServer(("127.0.0.1", 0), Target)
        threading.Thread(target=cls.target.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.target.shutdown()
        cls.target.server_close()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.runtime = Runtime(self.store, CORE, free_port())

    def tearDown(self):
        self.runtime.shutdown.set()
        with self.runtime.lock:
            self.runtime.stop()
        self.temp.cleanup()

    def transfer(self, state):
        config = client_config(state, state["clients"][0], {})
        port = free_port()
        config["inbounds"][0]["listen_port"] = port
        path = Path(self.temp.name) / "client.json"
        atomic_write(path, json.dumps(config))
        process = subprocess.Popen([CORE, "run", "-c", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 8
            while True:
                try:
                    sock = socket.create_connection(("127.0.0.1", port), timeout=1)
                    break
                except OSError:
                    if time.monotonic() > deadline or process.poll() is not None:
                        self.fail("Client core did not start")
                    time.sleep(.1)
            with sock:
                sock.settimeout(8)
                request = "GET http://127.0.0.1:{}/ HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nConnection: close\r\n\r\n".format(self.target.server_port, self.target.server_port)
                sock.sendall(request.encode())
                data = b""
                while True:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    data += chunk
            self.assertIn(b"NARA traffic accounting test.", data)
        finally:
            process.terminate()
            process.wait(timeout=5)
        time.sleep(.2)
        self.runtime.collect()

    def test_all_protocols_transfer_and_account(self):
        for protocol in ("vless", "vmess", "trojan", "hysteria2", "tuic", "anytls"):
            with self.subTest(protocol=protocol):
                state = example_state(protocol, self.profile)
                state["settings"]["block_private"] = False
                self.runtime.apply(state)
                before = self.store.totals().get("user1", {}).get("download", 0)
                self.transfer(state)
                self.assertGreater(self.store.totals()["user1"]["download"], before + 1000)
                self.assertGreater(self.store.totals()["user1"]["upload"], 0)
                self.runtime.stop()

    def test_usage_persists_across_restarts_without_double_counting(self):
        state = example_state("vless", self.profile)
        state["settings"]["block_private"] = False
        state["settings"]["server_address"] = "localhost"
        self.runtime.apply(state)
        self.transfer(state)
        before = self.store.totals()
        self.runtime.collect()
        self.assertEqual(before, self.store.totals())
        self.runtime.apply(state)
        self.assertEqual(before, self.store.totals())
        self.transfer(state)
        self.assertGreater(self.store.totals()["user1"]["download"], before["user1"]["download"])

    def test_failed_start_restores_previous_core(self):
        state = example_state("vless", self.profile)
        self.runtime.apply(state)
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            changed = copy.deepcopy(state)
            changed["inbounds"][0]["port"] = occupied.getsockname()[1]
            with self.assertRaises(ValueError):
                self.runtime.apply(changed)
        self.assertTrue(self.runtime.running)
        self.assertEqual(self.runtime.active, state)

    def test_quota_worker_removes_listener(self):
        state = example_state("vless", self.profile)
        state["settings"]["block_private"] = False
        state["clients"][0]["quota_bytes"] = 1000
        self.runtime.apply(state)
        self.transfer(state)
        self.store.set("autostart", False)
        # Exercise periodic enforcement, without the worker's initial autostart path.
        thread = threading.Thread(target=self.runtime.worker, daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with self.runtime.lock:
                current = json.loads((self.runtime.generation / "config.json").read_text())
            if current["inbounds"] == []:
                break
            time.sleep(.2)
        self.assertEqual(current["inbounds"], [])
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", state["inbounds"][0]["port"]), timeout=1)
        self.runtime.shutdown.set()
        thread.join(timeout=5)

    def test_expiry_worker_removes_listener(self):
        import datetime as dt
        state = example_state("vless", self.profile)
        state["clients"][0]["expires_at"] = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=3)).isoformat()
        self.runtime.apply(state)
        self.store.set("autostart", False)
        thread = threading.Thread(target=self.runtime.worker, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                with self.runtime.lock:
                    current = json.loads((self.runtime.generation / "config.json").read_text())
                if not current["inbounds"]:
                    break
                time.sleep(.2)
            self.assertEqual(current["inbounds"], [])
        finally:
            self.runtime.shutdown.set()
            thread.join(timeout=5)
