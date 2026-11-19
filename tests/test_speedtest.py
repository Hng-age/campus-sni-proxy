"""Unit tests for speed test service and GUI page."""

import unittest
from unittest.mock import MagicMock, patch

from services.speedtest_service import SpeedTester, get_network_info


class SpeedTestServiceTests(unittest.TestCase):
    def test_network_info(self):
        info = get_network_info()
        self.assertIn("local_ip", info)
        self.assertIn("hostname", info)
        self.assertIn("proxy_endpoint", info)

    def test_speed_tester_init(self):
        tester = SpeedTester(target_idx=0, use_proxy=False)
        self.assertFalse(tester._cancelled)
        tester.cancel()
        self.assertTrue(tester._cancelled)

    def test_mocked_speedtest_run(self):
        tester = SpeedTester(target_idx=0)
        with patch.object(tester, "measure_latency_and_jitter", return_value=(25.5, 3.2)), \
             patch.object(tester, "measure_download", return_value=85.2), \
             patch.object(tester, "measure_upload", return_value=12.4):
            progress_calls = []
            res = tester.run(on_progress=lambda p: progress_calls.append(p))
            self.assertIsNotNone(res)
            self.assertEqual(res["download_mbps"], 85.2)
            self.assertEqual(res["upload_mbps"], 12.4)
            self.assertEqual(res["ping_ms"], 25.5)
            self.assertEqual(res["jitter_ms"], 3.2)
            self.assertTrue(len(progress_calls) >= 2)


if __name__ == "__main__":
    unittest.main()
