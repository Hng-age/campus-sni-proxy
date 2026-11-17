import unittest

from sni_proxy.netutil import (
    bare_domain,
    cert_covers,
    is_blocked_domain,
    wildcard_covers,
)


class NetutilTests(unittest.TestCase):
    def test_bare_domain(self):
        self.assertEqual(bare_domain("a.b.douyin.com"), "douyin.com")
        self.assertEqual(bare_domain("douyin.com"), "douyin.com")
        self.assertEqual(bare_domain("localhost"), "localhost")

    def test_wildcard_covers(self):
        self.assertTrue(wildcard_covers("new.douyin.com"))
        self.assertTrue(wildcard_covers("douyin.com"))
        self.assertFalse(wildcard_covers("a.b.douyin.com"))
        self.assertTrue(wildcard_covers("xy36x250x117x106xy.mcdn.bilivideo.cn"))
        self.assertFalse(wildcard_covers("example.com"))

    def test_cert_covers_wildcard(self):
        cert = {"subjectAltName": (
            ("DNS", "*.douyin.com"),
            ("DNS", "douyin.com"),
        )}
        self.assertTrue(cert_covers(cert, "live.douyin.com"))
        self.assertTrue(cert_covers(cert, "douyin.com"))
        self.assertFalse(cert_covers(cert, "a.live.douyin.com"))
        self.assertFalse(cert_covers(cert, "douyin.com.evil.com"))

    def test_cert_covers_exact_and_empty(self):
        cert = {"subjectAltName": (("DNS", "www.bilibili.com"),)}
        self.assertTrue(cert_covers(cert, "www.bilibili.com"))
        self.assertFalse(cert_covers(cert, "api.bilibili.com"))
        self.assertFalse(cert_covers({}, "x.com"))

    def test_is_blocked_domain(self):
        self.assertTrue(is_blocked_domain("www.douyin.com"))
        self.assertTrue(is_blocked_domain("v.qq.com"))
        self.assertTrue(is_blocked_domain("live.douyin.com"))
        self.assertFalse(is_blocked_domain("www.baidu.com"))
        self.assertFalse(is_blocked_domain("example.com"))


if __name__ == "__main__":
    unittest.main()
