import os
import unittest


class VersionTests(unittest.TestCase):
    """Version and layout checks; deliberately does not import PySide6."""

    def test_version_is_351(self):
        from sni_proxy import config
        self.assertEqual(config.VERSION, "3.5.1")

    def test_version_consistent_across_entry_files(self):
        import json
        import re
        from sni_proxy import config, rules_manager
        from services import util

        root = util.BASE_DIR
        self.assertEqual(rules_manager.DEFAULT_RULES["version"], config.VERSION)

        with open(os.path.join(root, "rules.json"), "r", encoding="utf-8") as f:
            self.assertEqual(json.load(f)["version"], config.VERSION)

        with open(os.path.join(root, "proxy_manager.ps1"), "r", encoding="utf-8") as f:
            ps1 = f.read()
        m = re.search(r'\$Version\s*=\s*"([0-9]+(?:\.[0-9]+)+)"', ps1)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), config.VERSION)

        with open(os.path.join(root, "启动桌面版.bat"), "r", encoding="utf-8") as f:
            bat = f.read()
        self.assertIn(config.VERSION, bat)

    def test_services_util_base_dir_is_project_root(self):
        from services import util
        # services/util.py lives in <root>/services -> BASE_DIR is the root
        self.assertTrue(os.path.isdir(os.path.join(util.BASE_DIR, "gui")))
        self.assertTrue(os.path.isdir(os.path.join(util.BASE_DIR, "sni_proxy")))


if __name__ == "__main__":
    unittest.main()
