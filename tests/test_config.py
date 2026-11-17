import unittest

from sni_proxy import config


class ConfigTests(unittest.TestCase):
    def test_wildcard_bases_cover_all_blocked_suffixes(self):
        for suffix in config.BLOCKED_SUFFIXES:
            self.assertIn(suffix.lower(), config.WILDCARD_BASES)

    def test_no_duplicate_wildcard_bases(self):
        self.assertEqual(len(config.WILDCARD_BASES),
                         len(set(config.WILDCARD_BASES)))

    def test_version_is_103(self):
        self.assertEqual(config.VERSION, "1.0.3")


if __name__ == "__main__":
    unittest.main()
