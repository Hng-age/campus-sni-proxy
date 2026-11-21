import os
import shutil
import tempfile
import unittest

from sni_proxy import certs, config


class CryptographyCertsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.orig_cert_dir = config.CERT_DIR
        self.orig_ca_key = config.CA_KEY
        self.orig_ca_cert = config.CA_CERT
        self.orig_wc_key = config.WILDCARD_KEY
        self.orig_wc_cert = config.WILDCARD_CERT

        config.CERT_DIR = self.temp_dir
        config.CA_KEY = os.path.join(self.temp_dir, "ca.key")
        config.CA_CERT = os.path.join(self.temp_dir, "ca_cert.crt")
        config.WILDCARD_KEY = os.path.join(self.temp_dir, "_wildcard.key")
        config.WILDCARD_CERT = os.path.join(self.temp_dir, "_wildcard.crt")

    def tearDown(self):
        config.CERT_DIR = self.orig_cert_dir
        config.CA_KEY = self.orig_ca_key
        config.CA_CERT = self.orig_ca_cert
        config.WILDCARD_KEY = self.orig_wc_key
        config.WILDCARD_CERT = self.orig_wc_cert
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_pure_python_cert_generation(self):
        self.assertTrue(certs.HAVE_CRYPTOGRAPHY, "cryptography library must be available")
        # 1. Generate CA
        ca_k, ca_c = certs.generate_ca()
        self.assertTrue(os.path.exists(ca_k))
        self.assertTrue(os.path.exists(ca_c))
        self.assertGreater(os.path.getsize(ca_k), 500)
        self.assertGreater(os.path.getsize(ca_c), 500)

        # 2. Generate Wildcard
        ok = certs.generate_wildcard()
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(config.WILDCARD_KEY))
        self.assertTrue(os.path.exists(config.WILDCARD_CERT))

        # 3. Generate Site Cert
        cert_f, key_f = certs.generate_site_cert("test.special.domain.cn")
        self.assertIsNotNone(cert_f)
        self.assertIsNotNone(key_f)
        self.assertTrue(os.path.exists(cert_f))
        self.assertTrue(os.path.exists(key_f))


if __name__ == "__main__":
    unittest.main()
