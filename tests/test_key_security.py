import os
import tempfile
import unittest

from sni_proxy import certs


class LegacyKeyDisposalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_legacy = certs.config.LEGACY_DIR
        certs.config.LEGACY_DIR = self.tmp.name
        with open(os.path.join(self.tmp.name, "old.key"), "wb") as f:
            f.write(b"secret" * 100)
        with open(os.path.join(self.tmp.name, "old.crt"), "wb") as f:
            f.write(b"public")

    def tearDown(self):
        certs.config.LEGACY_DIR = self.old_legacy
        self.tmp.cleanup()

    def test_legacy_private_keys_are_deleted(self):
        count = certs.dispose_legacy_private_keys()
        self.assertEqual(count, 1)
        self.assertFalse(os.path.exists(
            os.path.join(self.tmp.name, "old.key")))

    def test_legacy_certificates_are_kept_for_audit(self):
        certs.dispose_legacy_private_keys()
        self.assertTrue(os.path.exists(
            os.path.join(self.tmp.name, "old.crt")))

    @unittest.skipUnless(os.name == "nt", "Windows ACL test")
    def test_key_acl_is_hardened(self):
        path = os.path.join(self.tmp.name, "acl.key")
        with open(path, "wb") as f:
            f.write(b"key")
        self.assertTrue(certs.harden_key_acl(path))
        self.assertTrue(os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
