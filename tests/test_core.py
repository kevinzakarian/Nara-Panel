"""Loopback integration tests. Never changes routes, firewall, or host DNS."""
import copy
import json
import os
import socket
import socketserver
import ssl
import struct
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


def dns_answer(query):
    """Answer fixture names locally; tests never need public DNS or Internet."""
    end = 12
    while query[end]:
        end += query[end] + 1
    end += 5
    qtype = struct.unpack("!H", query[end-4:end-2])[0]
    answer = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 60, 4) + socket.inet_aton("127.0.0.1") if qtype == 1 else b""
    return query[:2] + struct.pack("!HHHHH", 0x8180, 1, bool(answer), 0, 0) + query[12:end] + answer


class BootstrapDNS(socketserver.BaseRequestHandler):
    def handle(self):
        query, sock = self.request
        sock.sendto(dns_answer(query), self.client_address)


class RemoteDNS(BaseHTTPRequestHandler):
    queries = []

    def do_POST(self):
        query = self.rfile.read(int(self.headers["Content-Length"]))
        self.queries.append(query)
        answer = dns_answer(query)
        self.send_response(200)
        self.send_header("Content-Type", "application/dns-message")
        self.send_header("Content-Length", str(len(answer)))
        self.end_headers()
        self.wfile.write(answer)

    def log_message(self, *args):
        pass


@unittest.skipUnless(CORE, "Set SING_BOX_TEST_BINARY for real-core integration tests")
class CoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = self_signed({"server_name": "127.0.0.1", "days": 1})
        cls.target = ThreadingHTTPServer(("127.0.0.1", 0), Target)
        threading.Thread(target=cls.target.serve_forever, daemon=True).start()
        cls.dns_temp = tempfile.TemporaryDirectory()
        cert, key = Path(cls.dns_temp.name)/"cert.pem", Path(cls.dns_temp.name)/"key.pem"
        atomic_write(cert, cls.profile["certificate"])
        atomic_write(key, cls.profile["private_key"])
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cert, key)
        cls.remote_dns = ThreadingHTTPServer(("127.0.0.1", 0), RemoteDNS)
        cls.remote_dns.socket = tls.wrap_socket(cls.remote_dns.socket, server_side=True)
        cls.bootstrap_dns = socketserver.ThreadingUDPServer(("127.0.0.1", 0), BootstrapDNS)
        for server in (cls.remote_dns, cls.bootstrap_dns):
            threading.Thread(target=server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.target.shutdown()
        cls.target.server_close()
        for server in (cls.remote_dns, cls.bootstrap_dns):
            server.shutdown()
            server.server_close()
        cls.dns_temp.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.runtime = Runtime(self.store, CORE, free_port())

    def tearDown(self):
        self.runtime.shutdown.set()
        with self.runtime.lock:
            self.runtime.stop()
        self.temp.cleanup()

    def local_client(self, state):
        config = client_config(state, state["clients"][0], {})
        # Exercise the proxy without creating a VPN or changing host routes.
        config["inbounds"] = [i for i in config["inbounds"] if i["type"] != "tun"]
        port = free_port()
        config["inbounds"][0]["listen_port"] = port
        config["dns"]["servers"][0].update(server="127.0.0.1", server_port=self.bootstrap_dns.server_address[1])
        config["dns"]["servers"][1].update(server="127.0.0.1", server_port=self.remote_dns.server_port,
                                          tls={"enabled": True, "server_name": "127.0.0.1", "certificate": [self.profile["certificate"]]})
        return port, config

    def transfer(self, state):
        port, config = self.local_client(state)
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

    def test_complete_vpn_profiles_pass_core_check(self):
        for protocol in ("vless", "vmess", "trojan", "hysteria2", "tuic", "anytls"):
            with self.subTest(protocol=protocol):
                state = example_state(protocol, self.profile)
                path = Path(self.temp.name)/"vpn-check.json"
                atomic_write(path, json.dumps(client_config(state, state["clients"][0], {})))
                checked = subprocess.run([CORE, "check", "-c", str(path)], capture_output=True, text=True)
                self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_hysteria2_salamander_client_hijacks_dns_through_proxy(self):
        state = example_state("hysteria2", self.profile)
        state["settings"]["block_private"] = False
        state["settings"]["server_address"] = "node.nara.test"
        state["inbounds"][0]["server_options"] = {"obfs": {"type": "salamander", "password": "fixture-obfs"}}
        self.runtime.apply(state)
        port, config = self.local_client(state)
        path = Path(self.temp.name)/"dns-client.json"
        atomic_write(path, json.dumps(config))
        process = subprocess.Popen([CORE, "run", "-c", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        query = b"\x12\x34" + struct.pack("!HHHHH", 0x100, 1, 0, 0, 0) + b"\x03vpn\x04nara\x04test\x00" + struct.pack("!HH", 1, 1)
        before = len(RemoteDNS.queries)
        try:
            deadline = time.monotonic()+8
            while True:
                try:
                    sock = socket.create_connection(("127.0.0.1", port), timeout=1)
                    break
                except OSError:
                    if time.monotonic()>deadline or process.poll() is not None:
                        self.fail("Client core did not start")
                    time.sleep(.1)
            with sock:
                sock.settimeout(8)
                sock.sendall(b"\x05\x01\x00")
                self.assertEqual(sock.recv(2), b"\x05\x00")
                sock.sendall(b"\x05\x01\x00\x01"+socket.inet_aton("1.1.1.1")+struct.pack("!H", 53))
                reply = sock.makefile("rb")
                self.assertEqual(reply.read(10)[:2], b"\x05\x00")
                sock.sendall(struct.pack("!H", len(query))+query)
                length = struct.unpack("!H", reply.read(2))[0]
                answer = reply.read(length)
                self.assertEqual(answer[:2], query[:2])
                self.assertEqual(answer[-4:], socket.inet_aton("127.0.0.1"))
                reply.close()
            self.assertGreater(len(RemoteDNS.queries), before)
            time.sleep(.2)
            self.runtime.collect()
            self.assertGreater(self.store.totals()["user1"]["upload"], 0)
        finally:
            process.terminate()
            process.wait(timeout=5)

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

    def test_protocol_specific_settings_transfer_and_account(self):
        cases = [
            ("vless", {"flow": "xtls-rprx-vision"}, {}, {}),
            ("vmess", {"alter_id": 0}, {"security": "chacha20-poly1305", "global_padding": True, "authenticated_length": True}, {"enabled": True, "padding": True, "protocol": "h2mux", "max_streams": 8}),
            ("trojan", {"fallback": {"server": "127.0.0.1", "server_port": self.target.server_port}}, {}, {}),
            ("hysteria2", {"obfs": {"type": "salamander", "password": "local-obfs-test"}, "up_mbps": 30, "down_mbps": 50, "masquerade": {"type": "string", "status_code": 404, "content": "Not found"}}, {}, {}),
            ("hysteria2", {"up_mbps": 30, "down_mbps": 50, "ignore_client_bandwidth": True}, {}, {}),
            ("hysteria2", {"obfs": {"type": "gecko", "password": "local-gecko-test", "min_packet_size": 512, "max_packet_size": 1200}, "bbr_profile": "standard", "idle_timeout": "30s", "stream_receive_window": "8 MB", "connection_receive_window": "20 MB"}, {}, {}),
            ("tuic", {"congestion_control": "bbr", "auth_timeout": "5s", "heartbeat": "1s"}, {"udp_relay_mode": "quic"}, {}),
            ("anytls", {"padding_scheme": ["stop=3", "0=30-30", "1=100-400", "2=400-500"]}, {"idle_session_check_interval": "5s", "idle_session_timeout": "10s", "min_idle_session": 1}, {})
        ]
        for protocol, server, client, multiplex in cases:
            with self.subTest(protocol=protocol, options=server):
                state = example_state(protocol, self.profile)
                state["settings"]["block_private"] = False
                state["inbounds"][0].update(server_options=server, client_options=client, multiplex=multiplex)
                self.runtime.apply(state)
                before = self.store.totals().get("user1", {}).get("download", 0)
                self.transfer(state)
                self.assertGreater(self.store.totals()["user1"]["download"], before + 1000)
                self.runtime.stop()

    def test_v2ray_transports_transfer(self):
        for kind, settings in (("ws", {"max_early_data": 2048, "early_data_header_name": "Sec-WebSocket-Protocol"}),
                               ("grpc", {"idle_timeout": "30s", "ping_timeout": "10s"}),
                               ("http", {"host": ["vpn.example.com"], "method": "POST"}),
                               ("httpupgrade", {"host": "vpn.example.com"}), ("quic", {})):
            with self.subTest(transport=kind):
                state = example_state("vless", self.profile)
                state["settings"]["block_private"] = False
                state["inbounds"][0].update(transport=kind, path="/nara-test", transport_options=settings)
                self.runtime.apply(state)
                self.transfer(state)
                self.runtime.stop()

    def test_dns_cache_rules_and_quic_resolvers_validate(self):
        state = example_state("vless", self.profile)
        state["settings"]["dns_options"] = {"strategy": "prefer_ipv4", "cache_capacity": 4096, "independent_cache": True, "reverse_mapping": True}
        state["dns_servers"] += [
            {"id": "doq", "tag": "doq", "type": "quic", "server": "1.1.1.1", "port": 853, "server_name": "cloudflare-dns.com"},
            {"id": "h3", "tag": "h3", "type": "h3", "server": "1.1.1.1", "port": 443, "path": "/dns-query", "server_name": "cloudflare-dns.com"}]
        state["dns_rules"] = [
            {"id": "r1", "match": "domain_regex", "values": [r"^ads\\."], "action": "reject", "options": {"invert": False}},
            {"id": "r2", "match": "query_type", "values": ["AAAA"], "action": "route", "server": "bootstrap", "options": {"ip_version": 6, "disable_cache": True, "rewrite_ttl": 60}}]
        directory, config = self.runtime.prepare(state)
        self.assertEqual(config["dns"]["cache_capacity"], 4096)
        self.assertEqual(config["dns"]["rules"][1]["rewrite_ttl"], 60)
        import shutil
        shutil.rmtree(directory)

    def test_unassigned_inbound_is_checked_by_core(self):
        state = example_state("anytls", self.profile)
        state["clients"] = []
        state["inbounds"][0].update(enabled=False, server_options={"padding_scheme": ["stop=not-a-number"]})
        with self.assertRaisesRegex(ValueError, "Sing-box rejected"):
            self.runtime.prepare(state)

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
