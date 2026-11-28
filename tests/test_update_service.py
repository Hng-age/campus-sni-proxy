import os
import tempfile
import unittest

from services import update_service


class VersionParseTests(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(update_service.parse_version("v3.5.1"), (3, 5, 1))
        self.assertEqual(update_service.parse_version("3.10.1"), (3, 10, 1))
        self.assertEqual(update_service.parse_version(""), ())

    def test_is_newer(self):
        self.assertTrue(update_service.is_newer("3.5.1", "3.5.0"))
        self.assertFalse(update_service.is_newer("3.5.1", "3.5.1"))
        self.assertTrue(update_service.is_newer("3.10.0", "3.9.9"))


class AssetPickTests(unittest.TestCase):
    def test_prefers_exact_match(self):
        assets = [
            {"name": "source.zip"},
            {"name": "toci-3.5.1-portable.zip"},
            {"name": "toci-3.5.0-portable.zip"},
        ]
        picked = update_service.pick_asset(assets, "3.5.1")
        self.assertEqual(picked["name"], "toci-3.5.1-portable.zip")

    def test_falls_back_to_portable(self):
        assets = [{"name": "toci-3.5.0-portable.zip"}]
        picked = update_service.pick_asset(assets, "3.5.1")
        self.assertEqual(picked["name"], "toci-3.5.0-portable.zip")

    def test_none_when_no_zip(self):
        self.assertIsNone(update_service.pick_asset([{"name": "a.exe"}], "3.5.1"))


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


class SecurityTests(unittest.TestCase):
    def test_rejects_untrusted_asset_url(self):
        with self.assertRaises(update_service.UpdateError):
            update_service._validate_asset_url("http://github.com/a/b.zip")
        with self.assertRaises(update_service.UpdateError):
            update_service._validate_asset_url("https://evil.example.com/toci.zip")
        update_service._validate_asset_url("https://github.com/Hng-age/campus-sni-proxy/releases/download/v3.5.1/toci-3.5.1-portable.zip")
        update_service._validate_asset_url("https://objects.githubusercontent.com/github-production-release-asset/123")

    def test_rejects_missing_or_bad_digest(self):
        orig = update_service._download_stream
        try:
            def fake_stream(_info, dest, _use_proxy, _on_p=None, _sc=None):
                with open(dest, "wb") as f:
                    f.write(b"payload")

            update_service._download_stream = fake_stream
            with tempfile.TemporaryDirectory() as tmp:
                dest = os.path.join(tmp, "pkg.zip")
                with self.assertRaises(update_service.UpdateError):
                    update_service.download({"asset_url": "https://github.com/x/y.zip", "asset_digest": ""}, dest)
                with self.assertRaises(update_service.UpdateError):
                    update_service.download({"asset_url": "https://github.com/x/y.zip", "asset_digest": "sha256:" + ("0" * 64)}, dest)
        finally:
            update_service._download_stream = orig


if __name__ == "__main__":
    unittest.main()
