import unittest

from sni_proxy import config, upstream


class UpstreamOverrideLookupTests(unittest.TestCase):
    def tearDown(self):
        config.UPSTREAM_PORT_OVERRIDES = {}
        config.UPSTREAM_CERT_PINS = {}

    def test_port_override_longest_suffix(self):
        config.UPSTREAM_PORT_OVERRIDES = {
            "deepseek.com": 9443,
            "chat.deepseek.com": 8443,
        }
        self.assertEqual(upstream.port_override_for("chat.deepseek.com"), 8443)
        self.assertEqual(
            upstream.port_override_for("api.chat.deepseek.com"), 8443)
        self.assertEqual(upstream.port_override_for("deepseek.com"), 9443)
        self.assertEqual(upstream.port_override_for("www.deepseek.com"), 9443)
        self.assertIsNone(upstream.port_override_for("xdeepseek.com"))
        self.assertIsNone(upstream.port_override_for("example.com"))

    def test_port_override_validation(self):
        config.UPSTREAM_PORT_OVERRIDES = {
            "bad1.example.com": "not-a-port",
            "bad2.example.com": 0,
            "bad3.example.com": 70000,
            "*.ok.example.com": 8443,
        }
        self.assertIsNone(upstream.port_override_for("bad1.example.com"))
        self.assertIsNone(upstream.port_override_for("bad2.example.com"))
        self.assertIsNone(upstream.port_override_for("bad3.example.com"))
        # wildcard entries are treated as plain suffixes
        self.assertEqual(
            upstream.port_override_for("sub.ok.example.com"), 8443)

    def test_cert_pin_normalization(self):
        pin = "ab" * 32
        config.UPSTREAM_CERT_PINS = {
            "chat.example.com": pin.upper(),
            "colon.example.com": "sha256:" + ":".join(
                pin[i:i + 4] for i in range(0, 64, 4)),
            "bad.example.com": "zz" * 32,
            "short.example.com": "ab" * 31,
        }
        self.assertEqual(upstream.cert_pin_for("chat.example.com"), pin)
        self.assertEqual(upstream.cert_pin_for("colon.example.com"), pin)
        self.assertIsNone(upstream.cert_pin_for("bad.example.com"))
        self.assertIsNone(upstream.cert_pin_for("short.example.com"))
        self.assertIsNone(upstream.cert_pin_for("unrelated.com"))
        self.assertIsNone(upstream.cert_pin_for("example.com"))


if __name__ == "__main__":
    unittest.main()
