import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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

        cfg["server"] = "192.168.1.10"
        cfg["port"] = 18081
        cfg["username"] = "tester"
        cfg["password"] = 'p@ss:"word#1'
        cfg["mode"] = "global"
        saved = tun_service.save_tun_config(cfg)
        self.assertEqual(saved["server"], "192.168.1.10")
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
            "server": "192.168.1.10",
            "port": 18081,
            "protocol": "socks5",
            "username": "tester",
            "password": "pw1",
        })
        self.assertEqual(len(cfg["profiles"]), 1)
        first_id = cfg["profiles"][0]["id"]
        self.assertEqual(cfg["active_profile_id"], first_id)

        # Add a second profile
        cfg, p2 = tun_service.upsert_profile(cfg, {
            "name": "HTTP 备用线路",
            "protocol": "http",
            "server": "192.168.1.11",
            "port": 18080,
            "username": "u2",
            "password": "pw2",
        }, activate=False)
        self.assertEqual(len(cfg["profiles"]), 2)
        self.assertEqual(cfg["active_profile_id"], first_id)
        self.assertEqual(cfg["server"], "192.168.1.10")

        # Select second profile -> top-level server/port/auth sync immediately
        cfg = tun_service.select_profile(cfg, p2["id"])
        self.assertEqual(cfg["active_profile_id"], p2["id"])
        self.assertEqual(cfg["server"], "192.168.1.11")
        self.assertEqual(cfg["port"], 18080)
        self.assertEqual(cfg["protocol"], "http")

        # Edit second profile in place
        cfg, p2_edited = tun_service.upsert_profile(cfg, {
            "id": p2["id"],
            "name": "HTTP 备用线路(已改)",
            "protocol": "http",
            "server": "192.168.1.12",
            "port": 18888,
            "username": "u2_new",
            "password": "pw2_new",
        })
        self.assertEqual(len(cfg["profiles"]), 2)
        self.assertEqual(cfg["server"], "192.168.1.12")
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
        self.assertEqual(cfg["server"], "192.168.1.10")

    def test_yaml_generation_and_mihomo_validation(self):
        cfg = tun_service.load_tun_config()
        cfg["server"] = "192.168.1.10"
        cfg["port"] = 18081
        cfg["protocol"] = "socks5"
        cfg["username"] = "tester"
        cfg["password"] = "HzbwbNVYZFS"
        cfg["rules"] = [
            {"enabled": True, "type": "DOMAIN-SUFFIX", "value": "edu.cn", "policy": "DIRECT"},
            {"enabled": False, "type": "DOMAIN", "value": "disabled.example.com", "policy": "PROXY"},
            {"enabled": True, "type": "PROCESS-NAME", "value": "WeChat.exe", "policy": "PROXY"},
            {"enabled": True, "type": "IP-CIDR", "value": "198.51.100.0/24", "policy": "DIRECT"},
        ]

        yaml_text = tun_service.generate_mihomo_yaml(cfg)
        self.assertIn('server: "192.168.1.10"', yaml_text)
        self.assertIn("port: 18081", yaml_text)
        self.assertIn("type: socks5", yaml_text)
        self.assertIn("udp: true", yaml_text)
        self.assertIn('"192.168.1.10/32"', yaml_text)
        self.assertIn("IP-CIDR,192.168.1.10/32,DIRECT,no-resolve", yaml_text)
        self.assertIn("IP-CIDR,198.51.100.0/24,DIRECT,no-resolve", yaml_text)
        self.assertIn("PROCESS-NAME,WeChat.exe,PROXY", yaml_text)
        self.assertNotIn("disabled.example.com", yaml_text)

        yaml_path = tun_service.export_mihomo_yaml(cfg)
        if tun_service.find_mihomo_exe():
            ok, msg = tun_service.validate_mihomo_yaml(yaml_path)
            self.assertTrue(ok, f"Mihomo YAML validation failed: {msg}")

    def test_fallback_to_direct_yaml_modes(self):
        # Enabled (default): PROXY must be fallback -> [LAN-PROXY, DIRECT], GLOBAL exposes PROXY first
        cfg = tun_service.load_tun_config()
        self.assertTrue(cfg["fallback_to_direct"])
        cfg["server"] = "192.168.1.10"
        cfg["port"] = 18081
        cfg["fallback_interval"] = 7
        yaml_on = tun_service.generate_mihomo_yaml(cfg)
        self.assertIn("type: fallback", yaml_on)
        self.assertIn('- "LAN-PROXY"\n      - "DIRECT"', yaml_on)
        self.assertIn("interval: 7", yaml_on)
        self.assertIn('  - name: "GLOBAL"\n    type: select\n    proxies:\n      - "PROXY"', yaml_on)
        yaml_path = tun_service.export_mihomo_yaml(cfg)
        if tun_service.find_mihomo_exe():
            ok, msg = tun_service.validate_mihomo_yaml(yaml_path)
            self.assertTrue(ok, f"Mihomo YAML (fallback=True) failed: {msg}")

        # Disabled: PROXY reverts to select without DIRECT fallback
        cfg["fallback_to_direct"] = False
        yaml_off = tun_service.generate_mihomo_yaml(cfg)
        self.assertNotIn("type: fallback", yaml_off)
        yaml_path_off = tun_service.export_mihomo_yaml(cfg)
        if tun_service.find_mihomo_exe():
            ok, msg = tun_service.validate_mihomo_yaml(yaml_path_off)
            self.assertTrue(ok, f"Mihomo YAML (fallback=False) failed: {msg}")

    def test_mihomo_live_fallback_when_upstream_proxy_drops(self):
        exe = tun_service.find_mihomo_exe()
        if not exe:
            self.skipTest("mihomo.exe not present")

        # 1. Local 204 health-check HTTP target
        class _204Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(204)
                self.end_headers()

            def log_message(self, *_args):
                pass

        target_srv = ThreadingHTTPServer(("127.0.0.1", 0), _204Handler)
        target_port = target_srv.server_address[1]
        threading.Thread(target=target_srv.serve_forever, daemon=True).start()

        # 2. Local HTTP CONNECT proxy forwarding tunnel to 127.0.0.1:target_port
        proxy_srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        proxy_srv.bind(("127.0.0.1", 0))
        proxy_srv.listen(16)
        proxy_srv.settimeout(0.3)
        proxy_port = proxy_srv.getsockname()[1]
        stop_proxy = threading.Event()
        active_conns = []

        def _pipe(src, dst):
            try:
                while not stop_proxy.is_set():
                    data = src.recv(4096)
                    if not data:
                        break
                    dst.sendall(data)
            except OSError:
                pass

        def _handle_client(cli):
            up = None
            try:
                req = cli.recv(4096)
                if not req:
                    return
                first = req.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")
                up = socket.create_connection(("127.0.0.1", target_port), timeout=2)
                if first.startswith("CONNECT "):
                    cli.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                else:
                    up.sendall(req)
                t1 = threading.Thread(target=_pipe, args=(cli, up), daemon=True)
                t2 = threading.Thread(target=_pipe, args=(up, cli), daemon=True)
                t1.start(); t2.start()
                t1.join(timeout=3); t2.join(timeout=3)
            except OSError:
                pass
            finally:
                for s in (cli, up):
                    try:
                        if s:
                            s.close()
                    except OSError:
                        pass

        def _serve_proxy():
            while not stop_proxy.is_set():
                try:
                    cli, _ = proxy_srv.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                active_conns.append(cli)
                threading.Thread(target=_handle_client, args=(cli,), daemon=True).start()

        proxy_thread = threading.Thread(target=_serve_proxy, daemon=True)
        proxy_thread.start()

        s1 = socket.socket(); s1.bind(("127.0.0.1", 0)); mixed_port = s1.getsockname()[1]; s1.close()
        s2 = socket.socket(); s2.bind(("127.0.0.1", 0)); api_port = s2.getsockname()[1]; s2.close()

        cfg = tun_service.load_tun_config()
        cfg.update({
            "server": "127.0.0.1",
            "port": proxy_port,
            "protocol": "http",
            "username": "",
            "password": "",
            "mixed_port": mixed_port,
            "api_port": api_port,
            "fallback_to_direct": True,
            "fallback_interval": 5,
            "fallback_url": f"http://127.0.0.1:{target_port}/generate_204",
        })
        yaml_txt = tun_service.generate_mihomo_yaml(cfg)
        # Disable TUN NIC creation in unit test so it runs without admin privileges
        yaml_no_tun = yaml_txt.replace("tun:\n  enable: true", "tun:\n  enable: false")
        yp = os.path.join(self.tmp_dir, "live_fallback.yaml")
        with open(yp, "w", encoding="utf-8") as f:
            f.write(yaml_no_tun)
        os.makedirs(tun_service.TUN_STATE_DIR, exist_ok=True)

        proc = subprocess.Popen(
            [exe, "-d", tun_service.TUN_STATE_DIR, "-f", yp],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        try:
            # Phase 1: upstream alive -> PROXY should select LAN-PROXY
            saw_proxy = False
            for _ in range(20):
                time.sleep(0.3)
                try:
                    p = tun_service._api_request(api_port, "/proxies/PROXY", timeout=0.5)
                    if p.get("now") == "LAN-PROXY":
                        saw_proxy = True
                        break
                except Exception:
                    pass
            self.assertTrue(saw_proxy, "Expected PROXY to select LAN-PROXY while upstream is alive")

            # Phase 2: upstream drops -> PROXY must automatically fall back to DIRECT
            stop_proxy.set()
            proxy_srv.close()
            for c in active_conns:
                try:
                    c.close()
                except OSError:
                    pass
            saw_direct = False
            for _ in range(30):
                time.sleep(0.5)
                try:
                    p = tun_service._api_request(api_port, "/proxies/PROXY", timeout=0.5)
                    if p.get("now") == "DIRECT":
                        saw_direct = True
                        break
                except Exception:
                    pass
            self.assertTrue(saw_direct, "Expected PROXY to automatically fall back to DIRECT after upstream dropped")
            # Also verify get_tun_status() reflects fallback_active=True
            saved = tun_service.save_tun_config(cfg)
            self.assertTrue(saved["fallback_to_direct"])
            st = tun_service.get_tun_status()
            self.assertTrue(st["running"])
            self.assertEqual(st["active_outbound"], "DIRECT")
            self.assertTrue(st["fallback_active"])
        finally:
            stop_proxy.set()
            try:
                proxy_srv.close()
            except OSError:
                pass
            target_srv.shutdown()
            target_srv.server_close()
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
            if proc.stdout:
                proc.stdout.close()

    def test_tun_page_fallback_checkbox_sync(self):
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PySide6.QtWidgets import QApplication
        from gui.pages.tun import TunPage

        app = QApplication.instance() or QApplication(sys.argv)
        _ = app

        class _DummyCtx:
            def confirm_and_run(self, *_a, **_kw):
                pass

        tun_service.save_tun_config({"server": "192.168.1.10", "port": 18081, "fallback_to_direct": True})
        page = TunPage(_DummyCtx())
        self.assertTrue(page.chk_fallback_direct.isChecked())
        self.assertIn("已开启", page.lbl_fallback_rule.text())

        page.chk_fallback_direct.setChecked(False)
        collected = page._collect_ui_config()
        self.assertFalse(collected["fallback_to_direct"])
        page.poll_timer.stop()
        page.close()

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
                        if user == "tester" and pw == "secret":
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
                "username": "tester", "password": "secret",
            })
            self.assertTrue(ok_res["ok"])
            self.assertTrue(ok_res["auth_ok"])

            bad_res = tun_service.test_upstream_proxy({
                "server": "127.0.0.1", "port": port, "protocol": "socks5",
                "username": "tester", "password": "wrong",
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
                    if "dGVzdGVyOnNlY3JldA==" in data:
                        c.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                    else:
                        c.sendall(b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n")

        t = threading.Thread(target=_serve, daemon=True)
        t.start()
        try:
            ok_res = tun_service.test_upstream_proxy({
                "server": "127.0.0.1", "port": port, "protocol": "http",
                "username": "tester", "password": "secret",
            })
            self.assertTrue(ok_res["ok"])

            bad_res = tun_service.test_upstream_proxy({
                "server": "127.0.0.1", "port": port, "protocol": "http",
                "username": "tester", "password": "wrong",
            })
            self.assertFalse(bad_res["ok"])
            self.assertIn("407", bad_res["message"])
        finally:
            srv.close()


if __name__ == "__main__":
    unittest.main()
