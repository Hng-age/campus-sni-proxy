import os
import shutil
import socket
import tempfile
import threading
import unittest

from services import tun_service


class TunServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.orig_cfg = tun_service.TUN_CONFIG_FILE
        self.orig_yaml = tun_service.TUN_YAML_FILE
        self.orig_state = tun_service.TUN_STATE_DIR

        tun_service.TUN_CONFIG_FILE = os.path.join(self.tmp_dir, "tun_config.json")
        tun_service.TUN_YAML_FILE = os.path.join(self.tmp_dir, "tun_mihomo.yaml")
        tun_service.TUN_STATE_DIR = os.path.join(self.tmp_dir, "tun_state")

    def tearDown(self):
        tun_service.TUN_CONFIG_FILE = self.orig_cfg
        tun_service.TUN_YAML_FILE = self.orig_yaml
        tun_service.TUN_STATE_DIR = self.orig_state
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_config_roundtrip_and_presets(self):
        cfg = tun_service.load_tun_config()
        self.assertEqual(cfg["mode"], "rule")
        self.assertEqual(cfg["protocol"], "socks5")

        cfg["server"] = "192.168.112.32"
        cfg["port"] = 18081
        cfg["username"] = "b404"
        cfg["password"] = 'p@ss:"word#1'
        cfg["mode"] = "global"
        saved = tun_service.save_tun_config(cfg)
        self.assertEqual(saved["server"], "192.168.112.32")
        self.assertTrue(os.path.exists(tun_service.TUN_YAML_FILE))

        reloaded = tun_service.load_tun_config()
        self.assertEqual(reloaded["password"], 'p@ss:"word#1')
        self.assertEqual(reloaded["mode"], "global")

        preset_cfg = tun_service.apply_rule_preset(reloaded, "whitelist_proxy")
        self.assertEqual(preset_cfg["final_policy"], "DIRECT")
        self.assertTrue(any(r["value"] == "douyin.com" for r in preset_cfg["rules"]))

    def test_saved_profiles_crud_and_legacy_migration(self):
        # Legacy single-server config auto-migrates into profiles list
        cfg = tun_service.save_tun_config({
            "server": "192.168.112.32",
            "port": 18081,
            "protocol": "socks5",
            "username": "b404",
            "password": "pw1",
        })
        self.assertEqual(len(cfg["profiles"]), 1)
        first_id = cfg["profiles"][0]["id"]
        self.assertEqual(cfg["active_profile_id"], first_id)

        # Add a second profile
        cfg, p2 = tun_service.upsert_profile(cfg, {
            "name": "HTTP 备用线路",
            "protocol": "http",
            "server": "192.168.112.50",
            "port": 18080,
            "username": "u2",
            "password": "pw2",
        }, activate=False)
        self.assertEqual(len(cfg["profiles"]), 2)
        self.assertEqual(cfg["active_profile_id"], first_id)
        self.assertEqual(cfg["server"], "192.168.112.32")

        # Select second profile -> top-level server/port/auth sync immediately
        cfg = tun_service.select_profile(cfg, p2["id"])
        self.assertEqual(cfg["active_profile_id"], p2["id"])
        self.assertEqual(cfg["server"], "192.168.112.50")
        self.assertEqual(cfg["port"], 18080)
        self.assertEqual(cfg["protocol"], "http")

        # Edit second profile in place
        cfg, p2_edited = tun_service.upsert_profile(cfg, {
            "id": p2["id"],
            "name": "HTTP 备用线路(已改)",
            "protocol": "http",
            "server": "192.168.112.55",
            "port": 18888,
            "username": "u2_new",
            "password": "pw2_new",
        })
        self.assertEqual(len(cfg["profiles"]), 2)
        self.assertEqual(cfg["server"], "192.168.112.55")
        self.assertEqual(cfg["port"], 18888)
        self.assertEqual(p2_edited["name"], "HTTP 备用线路(已改)")

        # Save test result onto profile
        cfg = tun_service.update_profile_test_result(cfg, p2["id"], {"ok": True, "latency_ms": 3.5})
        p2_after = next(p for p in cfg["profiles"] if p["id"] == p2["id"])
        self.assertIn("3.5 ms", p2_after["last_status"])

        # Delete active profile -> falls back to first profile
        cfg = tun_service.delete_profile(cfg, p2["id"])
        self.assertEqual(len(cfg["profiles"]), 1)
        self.assertEqual(cfg["active_profile_id"], first_id)
        self.assertEqual(cfg["server"], "192.168.112.32")

    def test_yaml_generation_and_mihomo_validation(self):
        cfg = tun_service.load_tun_config()
        cfg["server"] = "192.168.112.32"
        cfg["port"] = 18081
        cfg["protocol"] = "socks5"
        cfg["username"] = "b404"
        cfg["password"] = "HzbwbNVYZFS"
        cfg["rules"] = [
            {"enabled": True, "type": "DOMAIN-SUFFIX", "value": "edu.cn", "policy": "DIRECT"},
            {"enabled": False, "type": "DOMAIN", "value": "disabled.example.com", "policy": "PROXY"},
            {"enabled": True, "type": "PROCESS-NAME", "value": "WeChat.exe", "policy": "PROXY"},
            {"enabled": True, "type": "IP-CIDR", "value": "198.51.100.0/24", "policy": "DIRECT"},
        ]

        yaml_text = tun_service.generate_mihomo_yaml(cfg)
        self.assertIn('server: "192.168.112.32"', yaml_text)
        self.assertIn("port: 18081", yaml_text)
        self.assertIn("type: socks5", yaml_text)
        self.assertIn("udp: true", yaml_text)
        self.assertIn('"192.168.112.32/32"', yaml_text)
        self.assertIn("IP-CIDR,192.168.112.32/32,DIRECT,no-resolve", yaml_text)
        self.assertIn("IP-CIDR,198.51.100.0/24,DIRECT,no-resolve", yaml_text)
        self.assertIn("PROCESS-NAME,WeChat.exe,PROXY", yaml_text)
        self.assertNotIn("disabled.example.com", yaml_text)

        yaml_path = tun_service.export_mihomo_yaml(cfg)
        if tun_service.find_mihomo_exe():
            ok, msg = tun_service.validate_mihomo_yaml(yaml_path)
            self.assertTrue(ok, f"Mihomo YAML validation failed: {msg}")

    def test_upstream_socks5_auth_check_mock(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(4)
        port = srv.getsockname()[1]

        def _serve():
            for _ in range(2):
                try:
                    c, _ = srv.accept()
                except OSError:
                    break
                with c:
                    greet = c.recv(16)
                    if len(greet) >= 2 and greet[0] == 5:
                        c.sendall(b"\x05\x02")
                        auth = c.recv(256)
                        ulen = auth[1]
                        user = auth[2:2 + ulen].decode("utf-8")
                        plen = auth[2 + ulen]
                        pw = auth[3 + ulen:3 + ulen + plen].decode("utf-8")
                        if user == "b404" and pw == "secret":
                            c.sendall(b"\x01\x00")
                            req = c.recv(32)
                            if req:
                                c.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
                        else:
                            c.sendall(b"\x01\x01")

        t = threading.Thread(target=_serve, daemon=True)
        t.start()
        try:
            ok_res = tun_service.test_upstream_proxy({
                "server": "127.0.0.1", "port": port, "protocol": "socks5",
                "username": "b404", "password": "secret",
            })
            self.assertTrue(ok_res["ok"])
            self.assertTrue(ok_res["auth_ok"])

            bad_res = tun_service.test_upstream_proxy({
                "server": "127.0.0.1", "port": port, "protocol": "socks5",
                "username": "b404", "password": "wrong",
            })
            self.assertFalse(bad_res["ok"])
            self.assertFalse(bad_res["auth_ok"])
        finally:
            srv.close()

    def test_upstream_http_407_and_200_mock(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(4)
        port = srv.getsockname()[1]

        def _serve():
            for _ in range(2):
                try:
                    c, _ = srv.accept()
                except OSError:
                    break
                with c:
                    data = c.recv(2048).decode("latin-1", errors="replace")
                    if "YjQwNDpzZWNyZXQ=" in data:
                        c.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    else:
                        c.sendall(b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n")

        t = threading.Thread(target=_serve, daemon=True)
        t.start()
        try:
            ok_res = tun_service.test_upstream_proxy({
                "server": "127.0.0.1", "port": port, "protocol": "http",
                "username": "b404", "password": "secret",
            })
            self.assertTrue(ok_res["ok"])

            bad_res = tun_service.test_upstream_proxy({
                "server": "127.0.0.1", "port": port, "protocol": "http",
                "username": "b404", "password": "wrong",
            })
            self.assertFalse(bad_res["ok"])
            self.assertIn("407", bad_res["message"])
        finally:
            srv.close()


if __name__ == "__main__":
    unittest.main()
