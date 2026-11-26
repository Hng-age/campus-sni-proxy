import os
import unittest


class VersionTests(unittest.TestCase):
    """Version and layout checks; deliberately does not import PySide6."""

    def test_version_is_350(self):
        from sni_proxy import config
        self.assertEqual(config.VERSION, "3.5.0")

    def test_services_util_base_dir_is_project_root(self):
        from services import util
        # services/util.py lives in <root>/services -> BASE_DIR is the root
        self.assertTrue(os.path.isdir(os.path.join(util.BASE_DIR, "gui")))
        self.assertTrue(os.path.isdir(os.path.join(util.BASE_DIR, "sni_proxy")))


if __name__ == "__main__":
    unittest.main()
