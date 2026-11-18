import os
import unittest

from sni_proxy import upstream
from sni_proxy.netutil import is_blocked_domain


class DomainBoundaryTests(unittest.TestCase):
    def test_exact_and_subdomain_match(self):
        self.assertTrue(is_blocked_domain("douyin.com"))
        self.assertTrue(is_blocked_domain("www.douyin.com"))
        self.assertTrue(is_blocked_domain("api.bilibili.com"))

    def test_lookalike_domains_do_not_match(self):
        self.assertFalse(is_blocked_domain("notdouyin.com"))
        self.assertFalse(is_blocked_domain("evilbilibili.com"))
        self.assertFalse(is_blocked_domain("douyin.com.evil.com"))

    @unittest.skipIf(os.environ.get("SNI_STRICT_UPSTREAM") == "0",
                     "global compat mode")
    @unittest.skipIf(os.environ.get("SNI_ASSET_COMPAT") == "0",
                     "asset compat disabled")
    def test_asset_suffix_boundary(self):
        self.assertTrue(upstream.allow_chain_route(
            "lf-douyin-pc-web.douyinstatic.com"))
        self.assertFalse(upstream.allow_chain_route("notdouyinstatic.com"))


if __name__ == "__main__":
    unittest.main()
