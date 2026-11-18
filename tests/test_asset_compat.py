import os
import unittest

from sni_proxy import upstream


class AssetCompatTests(unittest.TestCase):
    @unittest.skipIf(os.environ.get("SNI_STRICT_UPSTREAM") == "0",
                     "global compat mode")
    @unittest.skipIf(os.environ.get("SNI_ASSET_COMPAT") == "0",
                     "asset compat disabled")
    def test_static_assets_may_use_chain(self):
        self.assertTrue(upstream.allow_chain_route(
            "lf-douyin-pc-web.douyinstatic.com"))
        self.assertTrue(upstream.allow_chain_route("s1.hdslb.com"))
        self.assertTrue(upstream.allow_chain_route(
            "p3-pc-sign.douyinpic.com"))

    @unittest.skipIf(os.environ.get("SNI_STRICT_UPSTREAM") == "0",
                     "global compat mode")
    def test_api_domains_stay_strict(self):
        self.assertFalse(upstream.allow_chain_route("www.douyin.com"))
        self.assertFalse(upstream.allow_chain_route("api.bilibili.com"))


if __name__ == "__main__":
    unittest.main()
