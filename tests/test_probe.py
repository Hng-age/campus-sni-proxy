import unittest

import sni_proxy.upstream as up


class DummySock:
    def __init__(self):
        self.closed = False

    def settimeout(self, value):
        pass

    def close(self):
        self.closed = True


class ProbeFirstTests(unittest.TestCase):
    def setUp(self):
        self.old_try = up.try_tls
        self.good = ("10.0.0.1", "good.com")

        def fake(ip, sni, timeout=None, verify_host=None):
            if (ip, sni) == self.good:
                return DummySock()
            return None

        up.try_tls = fake

    def tearDown(self):
        up.try_tls = self.old_try

    def test_empty_candidates(self):
        self.assertEqual(up.probe_first([]),
                         (None, None, None, None))

    def test_returns_winning_candidate(self):
        candidates = [
            ("9.9.9.9", "bad.com", "own+map"),
            ("10.0.0.1", "good.com", "own+map"),
        ]
        ssock, ip, sni, how = up.probe_first(
            candidates, workers=2, deadline=3)
        self.assertIsNotNone(ssock)
        self.assertEqual((ip, sni, how), ("10.0.0.1", "good.com", "own+map"))
        self.assertFalse(ssock.closed)


if __name__ == "__main__":
    unittest.main()
