import json
import os
import tempfile
import unittest

from sni_proxy import config, rules_manager


class RulesManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.orig_rules_file = rules_manager.RULES_FILE
        self.orig_pac_file = rules_manager.PAC_FILE
        self.orig_strat_file = config.STRATEGY_FILE

        rules_manager.RULES_FILE = os.path.join(self.tmp_dir, "rules.json")
        rules_manager.PAC_FILE = os.path.join(self.tmp_dir, "proxy.pac")
        config.STRATEGY_FILE = os.path.join(self.tmp_dir, "strategies.json")

    def tearDown(self):
        rules_manager.RULES_FILE = self.orig_rules_file
        rules_manager.PAC_FILE = self.orig_pac_file
        config.STRATEGY_FILE = self.orig_strat_file
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_default_rules_creation_and_pac(self):
        rules_manager.ensure_rules_file()
        self.assertTrue(os.path.exists(rules_manager.RULES_FILE))
        self.assertTrue(os.path.exists(rules_manager.PAC_FILE))

        rules = rules_manager.load_rules()
        self.assertIn("douyin.com", rules["blocked_suffixes"])
        self.assertEqual(rules.get("proxy_mode"), "pac")

        pac_content = rules_manager.generate_pac_script(port=8888)
        self.assertIn("FindProxyForURL", pac_content)
        self.assertIn("PROXY 127.0.0.1:8888", pac_content)
        self.assertIn("douyin.com", pac_content)

    def test_add_and_remove_suffix(self):
        rules_manager.ensure_rules_file()
        added = rules_manager.add_blocked_suffix("custom-test-domain.com")
        self.assertTrue(added)
        self.assertIn("custom-test-domain.com", config.BLOCKED_SUFFIXES)

        # Adding duplicate should return False
        dup = rules_manager.add_blocked_suffix("custom-test-domain.com")
        self.assertFalse(dup)

        # Remove
        removed = rules_manager.remove_blocked_suffix("custom-test-domain.com")
        self.assertTrue(removed)
        self.assertNotIn("custom-test-domain.com", config.BLOCKED_SUFFIXES)

    def test_add_and_remove_sni_rewrite(self):
        rules_manager.ensure_rules_file()
        added = rules_manager.add_sni_rewrite("test.blocked.com", "allowed.com")
        self.assertTrue(added)
        self.assertEqual(config.SNI_REWRITE.get("test.blocked.com"), "allowed.com")

        removed = rules_manager.remove_sni_rewrite("test.blocked.com")
        self.assertTrue(removed)
        self.assertNotIn("test.blocked.com", config.SNI_REWRITE)

    def test_add_and_remove_upstream_port_override(self):
        rules_manager.ensure_rules_file()
        added = rules_manager.add_upstream_port_override(
            "chat.example.com", "8443")
        self.assertTrue(added)
        self.assertEqual(
            config.UPSTREAM_PORT_OVERRIDES.get("chat.example.com"), 8443)

        # invalid ports are rejected
        bad = rules_manager.add_upstream_port_override("bad.example.com", 0)
        self.assertFalse(bad)
        bad = rules_manager.add_upstream_port_override("bad.example.com", 70000)
        self.assertFalse(bad)
        self.assertNotIn("bad.example.com", config.UPSTREAM_PORT_OVERRIDES)

        removed = rules_manager.remove_upstream_port_override("chat.example.com")
        self.assertTrue(removed)
        self.assertNotIn("chat.example.com", config.UPSTREAM_PORT_OVERRIDES)

    def test_add_and_remove_upstream_cert_pin(self):
        pin = "ab" * 32
        rules_manager.ensure_rules_file()
        added = rules_manager.add_upstream_cert_pin("chat.example.com", pin)
        self.assertTrue(added)
        self.assertEqual(
            config.UPSTREAM_CERT_PINS.get("chat.example.com"), pin)

        # 'sha256:' prefix and colons are normalized, not rejected
        added2 = rules_manager.add_upstream_cert_pin(
            "chat2.example.com", "sha256:" + ":".join(
                pin[i:i + 4] for i in range(0, 64, 4)))
        self.assertTrue(added2)
        self.assertEqual(
            config.UPSTREAM_CERT_PINS.get("chat2.example.com"), pin)

        # invalid fingerprints are rejected
        bad = rules_manager.add_upstream_cert_pin("bad.example.com", "zz" * 32)
        self.assertFalse(bad)
        bad = rules_manager.add_upstream_cert_pin("bad.example.com", "ab" * 31)
        self.assertFalse(bad)
        self.assertNotIn("bad.example.com", config.UPSTREAM_CERT_PINS)

        removed = rules_manager.remove_upstream_cert_pin("chat.example.com")
        self.assertTrue(removed)
        self.assertNotIn("chat.example.com", config.UPSTREAM_CERT_PINS)
        self.assertTrue(
            rules_manager.remove_upstream_cert_pin("chat2.example.com"))

    def test_set_proxy_mode(self):
        rules_manager.ensure_rules_file()
        rules_manager.set_proxy_mode("global")
        self.assertEqual(config.PROXY_MODE, "global")
        rules_manager.set_proxy_mode("pac")
        self.assertEqual(config.PROXY_MODE, "pac")

    def test_strategy_cache_operations(self):
        data = {
            "test.com": {"endpoints": [["1.2.3.4", "sni.com", "chain"]], "fail_ts": None},
            "other.com": {"endpoints": [["5.6.7.8", "other.com", "host"]], "fail_ts": None},
        }
        with open(config.STRATEGY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)

        cache = rules_manager.get_strategy_cache()
        self.assertEqual(len(cache), 2)

        # Delete single entry
        deleted = rules_manager.delete_strategy_cache_entry("test.com")
        self.assertTrue(deleted)
        cache_after = rules_manager.get_strategy_cache()
        self.assertNotIn("test.com", cache_after)
        self.assertIn("other.com", cache_after)

        # Clear all
        rules_manager.clear_strategy_cache()
        self.assertEqual(rules_manager.get_strategy_cache(), {})


if __name__ == "__main__":
    unittest.main()
