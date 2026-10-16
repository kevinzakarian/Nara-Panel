import copy
import datetime as dt
import tempfile
import unittest
import ssl
import subprocess
from unittest import mock
from pathlib import Path
from nara.config import build_config, client_config, eligible, initial_state, validate
from nara.server import certificate_info, self_signed
from nara.store import Store, password_hash, password_matches
from nara.stats import decode_stats
from tests.helpers import example_state


class ConfigTests(unittest.TestCase):
    def test_empty_config_has_no_listeners(self):
        self.assertEqual(build_config(initial_state(), {}, Path("/tmp"))["inbounds"], [])

    def test_expired_and_exhausted_clients_are_excluded(self):
        state = example_state()
        client = state["clients"][0]
        client["quota_bytes"] = 100
        self.assertFalse(eligible(client, {"user1": {"upload": 70, "download": 30}}))
        self.assertEqual(build_config(state, {"user1": {"upload": 100}}, Path("/tmp"))["inbounds"], [])
        client["expires_at"] = "2000-01-01T00:00:00Z"
        self.assertFalse(eligible(client, {}))

    def test_disabled_client_cannot_export(self):
        state = example_state()
        state["clients"][0]["enabled"] = False
        with self.assertRaises(ValueError):
            client_config(state, state["clients"][0], {})

    def test_no_users_does_not_create_open_proxy(self):
        state = example_state()
        state["clients"] = []
        self.assertEqual(build_config(state, {}, Path("/tmp"))["inbounds"], [])

    def test_tls_required_protocols(self):
        for protocol in ("trojan", "hysteria2", "tuic", "anytls"):
            with self.subTest(protocol=protocol), self.assertRaises(ValueError):
                validate(example_state(protocol))

    def test_deleted_references_rejected(self):
        state = example_state()
        state["inbounds"] = []
        with self.assertRaises(ValueError):
            validate(state)

    def test_bootstrap_cycle_rejected(self):
        state = initial_state()
        state["dns_servers"] = [dict(id="a", tag="a", type="https", server="dns.a.test", domain_resolver="b"),
                                dict(id="b", tag="b", type="https", server="dns.b.test", domain_resolver="a")]
        state["settings"]["dns_final"] = "a"
        with self.assertRaises(ValueError):
            validate(state)

    def test_duplicate_port_rejected(self):
        state = example_state()
        state["inbounds"].append({**state["inbounds"][0], "id": "in2", "tag": "two"})
        with self.assertRaises(ValueError):
            validate(state)

    def test_private_networks_blocked_by_default(self):
        self.assertEqual(build_config(initial_state(), {}, Path("/tmp"))["route"]["rules"], [{"ip_is_private": True, "action": "reject"}])

    def test_public_port_mapping_in_export(self):
        state = example_state()
        state["inbounds"][0]["public_port"] = 443
        self.assertEqual(client_config(state, state["clients"][0], {})["outbounds"][1]["server_port"], 443)

    def test_rulesets_and_dns_rules(self):
        state = initial_state()
        state["rule_sets"] = [{"id": "rs", "tag": "test", "type": "inline", "rules": [{"domain_suffix": ["example.com"]}]}]
        state["dns_rules"] = [{"id": "rule", "match": "rule_set", "values": ["test"], "action": "reject"}]
        config = build_config(state, {}, Path("/tmp"))
        self.assertEqual(config["dns"]["rules"], [{"rule_set": ["test"], "action": "reject"}])
        self.assertNotIn("id", config["route"]["rule_set"][0])

    def test_expiry_must_be_aware(self):
        state = example_state()
        state["clients"][0]["expires_at"] = "2030-01-01T00:00:00"
        with self.assertRaises(ValueError):
            validate(state)

    def test_self_signed_export_keeps_tls_verification(self):
        profile = self_signed({"server_name": "127.0.0.1", "days": 1})
        info = certificate_info(profile)
        self.assertGreater(info["expires"], dt.datetime.now().timestamp())
        state = example_state("trojan", profile)
        config = client_config(state, state["clients"][0], {})
        self.assertEqual(config["outbounds"][1]["tls"]["certificate"], [profile["certificate"]])
        self.assertNotIn("insecure", config["outbounds"][1]["tls"])
        self.assertNotIn(profile["private_key"], str(config))

    def test_certificate_name_mismatch_rejected(self):
        profile = self_signed({"server_name": "example.com", "days": 1})
        profile["server_name"] = "other.example.com"
        with self.assertRaises(ValueError):
            certificate_info(profile)

    def test_certificate_generation_without_removed_python_ssl_helper(self):
        # Reproduce Python 3.12's removed API even when running on older Python.
        with mock.patch.object(ssl, "match_hostname", None, create=True):
            for address in ("127.0.0.1", "example.com", "2001:db8::1"):
                with self.subTest(address=address):
                    profile = self_signed({"server_name": address, "days": 1})
                    self.assertGreater(certificate_info(profile)["expires"], dt.datetime.now().timestamp())

    def test_certificate_ip_mismatch_and_wrong_private_key_rejected(self):
        profile = self_signed({"server_name": "127.0.0.1", "days": 1})
        profile["server_name"] = "127.0.0.2"
        with self.assertRaisesRegex(ValueError, "does not match"):
            certificate_info(profile)
        profile["server_name"] = "127.0.0.1"
        profile["private_key"] = self_signed({"server_name": "127.0.0.1", "days": 1})["private_key"]
        with self.assertRaisesRegex(ValueError, "private key"):
            certificate_info(profile)

    def test_old_openssl_zero_exit_on_name_mismatch_is_rejected(self):
        profile = self_signed({"server_name": "example.com", "days": 1})
        with mock.patch("nara.server.run_openssl", return_value=subprocess.CompletedProcess(
                [], 0, b"Hostname other.example.com does NOT match certificate\n", b"")):
            with self.assertRaisesRegex(ValueError, "does not match"):
                certificate_info(profile)

    def test_missing_openssl_has_actionable_error(self):
        with mock.patch("nara.server.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(ValueError, "OpenSSL executable was not found"):
                self_signed({"server_name": "example.com", "days": 1})

    def test_password_hash_and_persistent_usage(self):
        encoded = password_hash("a secure password")
        self.assertTrue(password_matches("a secure password", encoded))
        self.assertFalse(password_matches("wrong", encoded))
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            store.add_traffic([("a", "upload", 4), ("a", "download", 12)])
            self.assertEqual(Store(directory).totals()["a"], {"upload": 4, "download": 12})

    def test_stats_protobuf(self):
        name = b"user>>>client-a>>>traffic>>>uplink"
        stat = b"\x0a" + bytes([len(name)]) + name + b"\x10\x64"
        self.assertEqual(decode_stats(b"\x0a" + bytes([len(stat)]) + stat), {name.decode(): 100})
        with self.assertRaises(ValueError):
            decode_stats(b"\x0a\x7f")
