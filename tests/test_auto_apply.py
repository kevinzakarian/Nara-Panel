"""Exercise saves through the HTTP API against the real local Sing-box core."""
import copy
import socket
import unittest
from unittest import mock
from nara.server import self_signed
from tests import test_api
from tests.test_core import CORE
from tests.helpers import example_state, free_port


@unittest.skipUnless(CORE, "Set SING_BOX_TEST_BINARY for auto-apply integration")
class AutoApplyTests(unittest.TestCase):
    real_core = True
    web_path = ""
    request = test_api.APITests.request
    login = test_api.APITests.login

    def setUp(self):
        test_api.APITests.setUp(self)
        self.runtime.binary = CORE
        self.runtime.stats_port = free_port()
        self.login()

    def tearDown(self):
        self.runtime.shutdown.set()
        self.runtime.stop()
        test_api.APITests.tearDown(self)

    def seed(self):
        state = example_state("vless", self_signed({"server_name": "127.0.0.1", "days": 1}))
        self.runtime.apply(state, save=True)
        return state

    def test_complete_dns_and_routing_save_without_apply_and_invalid_route_rolls_back(self):
        state = self.seed()
        result = self.request('/api/core-options', {'revision': state['revision'], 'section': 'dns',
                              'options': {'timeout': '3s', 'cache_capacity': 2048}, 'default_resolver': 'bootstrap'})
        self.assertEqual(result[0], 200, result[1])
        state = self.store.get('state')
        rule = {'action': 'reject', 'domain_suffix': ['blocked.example.com']}
        result = self.save(state, 'route_rules', {'config': rule})
        self.assertEqual(result[0], 200, result[1])
        state = self.store.get('state')
        import json
        config = json.loads((self.runtime.generation/'config.json').read_text())
        self.assertEqual(config['dns']['cache_capacity'], 2048)
        self.assertEqual(config['route']['rules'][-1], rule)
        result = self.save(state, 'route_rules', {'config': {'domain_suffix': ['example.com'], 'action': 'route', 'outbound': 'missing-outbound'}})
        self.assertEqual(result[0], 400, result[1])
        self.assertEqual(self.store.get('state'), state)
        self.assertEqual(self.runtime.active, state)
        self.assertTrue(self.runtime.running)

    def save(self, state, collection, record):
        return self.request("/api/save", {"revision": state["revision"], "collection": collection, "record": record})

    def test_saving_client_starts_listener_without_apply_request(self):
        state = self.seed()
        record = {**state["clients"][0], "enabled": False}
        result = self.save(state, "clients", record)
        self.assertEqual(result[0], 200, result[1])
        self.assertEqual(self.runtime.active, self.store.get("state"))
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", state["inbounds"][0]["port"]), timeout=1)
        state = self.store.get("state")
        result = self.save(state, "clients", {**record, "enabled": True})
        self.assertEqual(result[0], 200, result[1])
        with socket.create_connection(("127.0.0.1", state["inbounds"][0]["port"]), timeout=1):
            pass

    def test_failed_bind_keeps_saved_and_active_state(self):
        state = self.seed()
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            result = self.save(state, "inbounds", {**state["inbounds"][0], "port": occupied.getsockname()[1]})
        self.assertEqual(result[0], 400, result[1])
        self.assertEqual(self.store.get("state"), state)
        self.assertEqual(self.runtime.active, state)
        self.assertEqual(self.store.get("active"), state)
        self.assertTrue(self.runtime.running)

    def test_metadata_and_token_changes_do_not_restart_core(self):
        state = self.seed()
        process = self.runtime.process.pid
        for path, payload in (("rotate-token", {"id": "user1"}),
                              ("settings", {"settings": {**state["settings"], "public_url": "https://panel.example.com/AbCdEfGh/"}})):
            current = self.store.get("state")
            result = self.request("/api/" + path, {"revision": current["revision"], **payload})
            self.assertEqual(result[0], 200, result[1])
            self.assertFalse(result[1]["restarted"])
            self.assertEqual(self.runtime.process.pid, process)
            self.assertEqual(self.runtime.active, self.store.get("state"))
        old_token = state["clients"][0]["token"]
        self.assertEqual(self.request("/sub/" + old_token)[0], 404)

    def test_invalid_unassigned_inbound_is_not_saved(self):
        state = self.store.get("state")
        result = self.save(state, "inbounds", {"tag": "bad", "type": "vless", "port": free_port(),
            "listen": "127.0.0.1", "enabled": False, "transport": "ws", "path": "/",
            "transport_options": {"early_data_header_name": "\r\nInjected"}})
        self.assertEqual(result[0], 400, result[1])
        self.assertEqual(self.store.get("state"), state)
        self.assertFalse(self.runtime.running)

    def test_failed_usage_reset_preserves_usage_and_account_limits(self):
        state = self.seed()
        self.store.add_traffic([("user1", "download", 1234)])
        with mock.patch.object(self.runtime, "launch", side_effect=ValueError("Simulated startup failure")):
            result = self.request("/api/reset-traffic", {"revision": state["revision"], "id": "user1"})
        self.assertEqual(result[0], 400)
        self.assertEqual(self.store.totals()["user1"]["download"], 1234)
        self.assertEqual(self.store.get("state"), state)

    def test_usage_reset_reactivates_exhausted_account_automatically(self):
        state = self.seed()
        state["clients"][0]["quota_bytes"] = 100
        self.store.add_traffic([("user1", "download", 200)])
        self.runtime.apply(state, save=True)
        self.assertEqual(self.runtime.active["clients"][0]["quota_bytes"], 100)
        result = self.request("/api/reset-traffic", {"revision": state["revision"], "id": "user1"})
        self.assertEqual(result[0], 200, result[1])
        self.assertEqual(self.store.totals().get("user1", {}).get("download", 0), 0)
        with socket.create_connection(("127.0.0.1", state["inbounds"][0]["port"]), timeout=1):
            pass

    def test_certificate_generation_applies_insecure_to_exports_only(self):
        state = self.seed()
        profile = copy.deepcopy(state["tls"][0])
        profile["insecure"] = True
        result = self.save(state, "tls", profile)
        self.assertEqual(result[0], 200, result[1])
        token = state["clients"][0]["token"]
        result = self.request("/sub/" + token)
        self.assertEqual(result[0], 200, result[1])
        self.assertTrue(result[1]["outbounds"][1]["tls"]["insecure"])
        import json
        server = json.loads((self.runtime.generation / "config.json").read_text())
        self.assertNotIn("insecure", server["inbounds"][0]["tls"])

    def test_missing_core_does_not_save_a_draft(self):
        state = self.store.get("state")
        self.runtime.binary = "/nonexistent"
        result = self.request("/api/settings", {"revision": 0, "settings": state["settings"]})
        self.assertEqual(result[0], 400)
        self.assertEqual(self.store.get("state"), state)

    def test_persistence_failure_restores_previous_core_and_model(self):
        state = self.seed()
        with mock.patch.object(self.store, "commit_configuration", side_effect=OSError("Simulated persistence failure")):
            result = self.save(state, "inbounds", {**state["inbounds"][0], "port": free_port()})
        self.assertEqual(result[0], 400, result[1])
        self.assertEqual(self.store.get("state"), state)
        self.assertEqual(self.store.get("active"), state)
        self.assertEqual(self.runtime.active, state)
        with socket.create_connection(("127.0.0.1", state["inbounds"][0]["port"]), timeout=1):
            pass
