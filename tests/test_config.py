import unittest

from sni_proxy import config


class ConfigTests(unittest.TestCase):
    def test_wildcard_bases_cover_all_blocked_suffixes(self):
        for suffix in config.BLOCKED_SUFFIXES:
            self.assertIn(suffix.lower(), config.WILDCARD_BASES)

    def test_no_duplicate_wildcard_bases(self):
        self.assertEqual(len(config.WILDCARD_BASES),
                         len(set(config.WILDCARD_BASES)))

    def test_version_is_210(self):
        self.assertEqual(config.VERSION, "2.1.0")

    def test_strict_upstream_default(self):
        self.assertTrue(config.STRICT_UPSTREAM)


if __name__ == "__main__":
    unittest.main()
