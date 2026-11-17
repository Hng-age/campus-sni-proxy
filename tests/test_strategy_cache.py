import json
import os
import tempfile
import unittest

import sni_proxy.upstream as up


class StrategyCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_file = up.STRATEGY_FILE
        self.old_cache = up._strategy_cache
        up.STRATEGY_FILE = os.path.join(self.tmp.name, "strategies.json")
        up._strategy_cache = {}

    def tearDown(self):
        up.STRATEGY_FILE = self.old_file
        up._strategy_cache = self.old_cache
        self.tmp.cleanup()

    def test_save_and_load_endpoints(self):
        up._strategy_cache = {
            "a.com": {
                "endpoints": [("1.2.3.4", "a.com", "host")],
                "fail_ts": None,
            },
            "b.com": {
                "endpoints": [("5.6.7.8", "b.com", "chain")],
                "fail_ts": 123,
            },
        }
        up.save_strategy_cache()
        up._strategy_cache = {}
        up.load_strategy_cache()

        self.assertEqual(up._strategy_cache["a.com"]["endpoints"],
                         [("1.2.3.4", "a.com", "host")])
        self.assertIsNone(up._strategy_cache["a.com"]["fail_ts"])
        self.assertEqual(up._strategy_cache["b.com"]["endpoints"],
                         [("5.6.7.8", "b.com", "chain")])
        # fail_ts is intentionally dropped on load
        self.assertIsNone(up._strategy_cache["b.com"]["fail_ts"])

    def test_load_legacy_pairs_as_chain(self):
        with open(up.STRATEGY_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "c.com": {"endpoints": [["9.9.9.9", "c.com"]], "fail_ts": 1}
            }, f)
        up.load_strategy_cache()
        self.assertEqual(up._strategy_cache["c.com"]["endpoints"],
                         [("9.9.9.9", "c.com", "chain")])


if __name__ == "__main__":
    unittest.main()
