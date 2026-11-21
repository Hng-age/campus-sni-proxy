import json
import os
import tempfile
import unittest

from services import probe_service
from sni_proxy import config, rules_manager


class ProbeServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.orig_rules_file = rules_manager.RULES_FILE
        self.orig_pac_file = rules_manager.PAC_FILE
        self.orig_strat_file = config.STRATEGY_FILE

        rules_manager.RULES_FILE = os.path.join(self.tmp_dir, "rules.json")
        rules_manager.PAC_FILE = os.path.join(self.tmp_dir, "proxy.pac")
        config.STRATEGY_FILE = os.path.join(self.tmp_dir, "strategies.json")
        rules_manager.ensure_rules_file()

    def tearDown(self):
        rules_manager.RULES_FILE = self.orig_rules_file
        rules_manager.PAC_FILE = self.orig_pac_file
        config.STRATEGY_FILE = self.orig_strat_file
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_apply_probe_result(self):
        probe_res = {
            "success": True,
            "domain": "video.test.com",
            "bare_domain": "test.com",
            "recommended_suffix": "test.com",
            "best_ip": "1.1.1.1",
            "best_sni": "www.zhihu.com",
            "latency_ms": 35.0,
            "verify_level": "chain",
            "is_blocked": True,
        }

        ok, msg = probe_service.apply_probe_result(probe_res)
        self.assertTrue(ok)
        self.assertIn("video.test.com", msg)

        # Suffix must be in config.BLOCKED_SUFFIXES
        self.assertIn("test.com", config.BLOCKED_SUFFIXES)

        # Cache must have video.test.com
        cache = rules_manager.get_strategy_cache()
        self.assertIn("video.test.com", cache)
        endpoints = cache["video.test.com"]["endpoints"]
        self.assertEqual(endpoints[0][0], "1.1.1.1")
        self.assertEqual(endpoints[0][1], "www.zhihu.com")


if __name__ == "__main__":
    unittest.main()
