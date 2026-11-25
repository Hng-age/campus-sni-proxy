import json
import os
import tempfile
import unittest

from services import probe_service
from sni_proxy import config, rules_manager


class ProbeServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.orig_rules_file = rules_manager.RULES_FILE
        self.orig_pac_file = rules_manager.PAC_FILE
        self.orig_strat_file = config.STRATEGY_FILE

        rules_manager.RULES_FILE = os.path.join(self.tmp_dir, "rules.json")
        rules_manager.PAC_FILE = os.path.join(self.tmp_dir, "proxy.pac")
        config.STRATEGY_FILE = os.path.join(self.tmp_dir, "strategies.json")
        rules_manager.ensure_rules_file()

    def tearDown(self):
        rules_manager.RULES_FILE = self.orig_rules_file
        rules_manager.PAC_FILE = self.orig_pac_file
        config.STRATEGY_FILE = self.orig_strat_file
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_apply_probe_result(self):
        # v1 兼容：无 strategy 字段走老路径
        probe_res = {
            "success": True,
            "domain": "video.test.com",
            "bare_domain": "test.com",
            "recommended_suffix": "test.com",
            "best_ip": "1.1.1.1",
            "best_sni": "www.zhihu.com",
            "latency_ms": 35.0,
            "verify_level": "chain",
            "is_blocked": True,
        }

        ok, msg = probe_service.apply_probe_result(probe_res)
        self.assertTrue(ok)
        self.assertIn("video.test.com", msg)

        # Suffix must be in config.BLOCKED_SUFFIXES
        self.assertIn("test.com", config.BLOCKED_SUFFIXES)

        # Cache must have video.test.com
        cache = rules_manager.get_strategy_cache()
        self.assertIn("video.test.com", cache)
        endpoints = cache["video.test.com"]["endpoints"]
        self.assertEqual(endpoints[0][0], "1.1.1.1")
        self.assertEqual(endpoints[0][1], "www.zhihu.com")

    def test_apply_probe_result_direct(self):
        ok, msg = probe_service.apply_probe_result({
            "success": True,
            "strategy": "direct",
            "domain": "ok.test.com",
            "best_ip": "2.2.2.2",
            "best_sni": "ok.test.com",
        })
        self.assertTrue(ok)
        self.assertIn("直连正常", msg)
        self.assertNotIn("ok.test.com", config.BLOCKED_SUFFIXES)

    def test_apply_probe_result_port_override_with_pin(self):
        pin = "ab" * 32
        probe_res = {
            "success": True,
            "strategy": "port_override_pin",
            "domain": "chat.example.com",
            "bare_domain": "example.com",
            "recommended_suffix": "chat.example.com",
            "best_ip": "116.205.40.113",
            "best_sni": "chat.example.com",
            "port": 8443,
            "cert_pin": pin,
            "latency_ms": 120.0,
            "verify_level": "pin",
            "http_status": 200,
        }

        ok, msg = probe_service.apply_probe_result(probe_res)
        self.assertTrue(ok)

        # 精确主机后缀进入 MITM 列表；裸域不被裹挟
        self.assertIn("chat.example.com", config.BLOCKED_SUFFIXES)
        self.assertNotIn("example.com", config.BLOCKED_SUFFIXES)

        # 端口改写 + 证书指纹锁定生效
        self.assertEqual(
            config.UPSTREAM_PORT_OVERRIDES.get("chat.example.com"), 8443)
        self.assertEqual(
            config.UPSTREAM_CERT_PINS.get("chat.example.com"), pin)

        # 策略缓存写入实测端点（真实 SNI）
        cache = rules_manager.get_strategy_cache()
        self.assertIn("chat.example.com", cache)
        endpoints = cache["chat.example.com"]["endpoints"]
        self.assertEqual(
            endpoints[0], ["116.205.40.113", "chat.example.com", "host"])

    def test_apply_probe_result_port_override_strict(self):
        probe_res = {
            "success": True,
            "strategy": "port_override",
            "domain": "cdn.example.org",
            "bare_domain": "example.org",
            "recommended_suffix": "cdn.example.org",
            "best_ip": "36.249.95.100",
            "best_sni": "cdn.example.org",
            "port": 8443,
            "cert_pin": None,
            "latency_ms": 80.0,
            "verify_level": "host",
            "http_status": 200,
        }
        ok, msg = probe_service.apply_probe_result(probe_res)
        self.assertTrue(ok)
        self.assertIn("cdn.example.org", config.BLOCKED_SUFFIXES)
        self.assertEqual(
            config.UPSTREAM_PORT_OVERRIDES.get("cdn.example.org"), 8443)
        self.assertNotIn("cdn.example.org", config.UPSTREAM_CERT_PINS)

    def test_looks_real_rejects_teapot_and_bare_responses(self):
        # 418 Teapot：边缘拒绝伪装 SNI 的标志，必须判为不可用
        self.assertFalse(probe_service._looks_real({"status": 418}))
        # 5xx：可能是错误页兜底，保守拒绝
        self.assertFalse(probe_service._looks_real({"status": 502}))
        # 裸 GET / 不该出现的 204/304 一律拒绝（无内容证据）
        self.assertFalse(probe_service._looks_real(
            {"status": 204, "body_len": 0, "content_type": ""}))
        self.assertFalse(probe_service._looks_real(
            {"status": 304, "body_len": 0, "content_type": ""}))
        # 跳转必须有 Location
        self.assertFalse(probe_service._looks_real({"status": 302}))
        self.assertTrue(probe_service._looks_real(
            {"status": 302, "location": "/x"}))
        # 200 必须有内容证据
        self.assertFalse(probe_service._looks_real(
            {"status": 200, "body_len": 0, "content_type": ""}))
        self.assertTrue(probe_service._looks_real(
            {"status": 200, "body_len": 512}))
        # 真实边缘的 4xx：带服务端特征头即判真
        # （harness.deepseek.com 的裸 404：Content-Length: 0 + Server: CW）
        self.assertTrue(probe_service._looks_real(
            {"status": 404, "body_len": 0, "content_type": "",
             "content_length": "0", "server": "CW"}))
        self.assertTrue(probe_service._looks_real(
            {"status": 401, "body_len": 90, "content_type": "application/json"}))
        # 没有任何特征头的 4xx 仍然拒绝
        self.assertFalse(probe_service._looks_real(
            {"status": 404, "body_len": 0, "content_type": ""}))
        # 空证据直接拒绝，不抛 KeyError
        self.assertFalse(probe_service._looks_real(None))
        self.assertFalse(probe_service._looks_real({}))

    def test_norm_domain(self):
        self.assertEqual(
            probe_service._norm_domain("https://Chat.Example.com/a/b"), "chat.example.com")
        self.assertEqual(
            probe_service._norm_domain("  douyin.com "), "douyin.com")
        self.assertEqual(probe_service._norm_domain("v.qq.com:443"), "v.qq.com")
        self.assertEqual(probe_service._norm_domain(""), "")
        # 带路径但不带协议头的输入也必须截断
        self.assertEqual(
            probe_service._norm_domain("chat.deepseek.com/a/b?x=1"), "chat.deepseek.com")
        self.assertEqual(
            probe_service._norm_domain("https://x.com:8443/a"), "x.com")
        self.assertEqual(probe_service._norm_domain("example.com."), "example.com")


if __name__ == "__main__":
    unittest.main()
