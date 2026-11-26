import os
import tempfile
import unittest

from services import update_service


class VersionParseTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(update_service.parse_version("v3.5.0"), (3, 5, 0))
        self.assertEqual(update_service.parse_version("3.10.1"), (3, 10, 1))
        self.assertEqual(update_service.parse_version(""), ())

    def test_is_newer(self):
        self.assertTrue(update_service.is_newer("3.5.0", "3.4.9"))
        self.assertFalse(update_service.is_newer("3.5.0", "3.5.0"))
        self.assertTrue(update_service.is_newer("3.10.0", "3.9.9"))


class AssetPickTests(unittest.TestCase):
    def test_prefers_exact_match(self):
        assets = [
            {"name": "source.zip"},
            {"name": "toci-3.5.0-portable.zip"},
            {"name": "toci-3.4.0-portable.zip"},
        ]
        picked = update_service.pick_asset(assets, "3.5.0")
        self.assertEqual(picked["name"], "toci-3.5.0-portable.zip")

    def test_falls_back_to_portable(self):
        assets = [{"name": "toci-3.4.0-portable.zip"}]
        picked = update_service.pick_asset(assets, "3.5.0")
        self.assertEqual(picked["name"], "toci-3.4.0-portable.zip")

    def test_none_when_no_zip(self):
        self.assertIsNone(update_service.pick_asset([{"name": "a.exe"}], "3.5.0"))


class AppRootTests(unittest.TestCase):
    def test_flat_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "toci.exe"), "wb").close()
            self.assertEqual(update_service.find_app_root(tmp), tmp)

    def test_wrapped_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            inner = os.path.join(tmp, "toci")
            os.makedirs(inner)
            open(os.path.join(inner, "toci.exe"), "wb").close()
            self.assertEqual(update_service.find_app_root(tmp), inner)

    def test_missing_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(update_service.find_app_root(tmp))


if __name__ == "__main__":
    unittest.main()
