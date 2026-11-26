import unittest

from sni_proxy import config


class ConfigTests(unittest.TestCase):
    def test_wildcard_bases_cover_all_blocked_suffixes(self):
        for suffix in config.BLOCKED_SUFFIXES:
            self.assertIn(suffix.lower(), config.WILDCARD_BASES)

    def test_no_duplicate_wildcard_bases(self):
        self.assertEqual(len(config.WILDCARD_BASES),
                         len(set(config.WILDCARD_BASES)))

    def test_version_is_350(self):
        self.assertEqual(config.VERSION, "3.5.0")

    def test_strict_upstream_default(self):
        self.assertTrue(config.STRICT_UPSTREAM)

    def test_autostart_registry_roundtrip_isolated(self):
        import os
        if os.name != "nt":
            self.skipTest("Windows registry test")
        import winreg
        from services import config_manager

        test_subkey = r"Software\SNIProxyDesktop_UnitTest_Run"
        test_val = "SNIProxyTest"
        try:
            cmd = config_manager.autostart_command()
            self.assertIn("--minimized", cmd)
            self.assertFalse(config_manager.is_autostart_enabled(test_subkey, test_val))

            ok, err = config_manager.set_autostart_enabled(True, test_subkey, test_val)
            self.assertTrue(ok, err)
            self.assertTrue(config_manager.is_autostart_enabled(test_subkey, test_val))

            ok, err = config_manager.set_autostart_enabled(False, test_subkey, test_val)
            self.assertTrue(ok, err)
            self.assertFalse(config_manager.is_autostart_enabled(test_subkey, test_val))
        finally:
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, test_subkey)
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
