"""GUI import smoke tests: the whole module skips without PySide6."""

import importlib
import unittest

try:
    import PySide6  # noqa: F401
    HAS_PYSIDE = True
except ImportError:
    HAS_PYSIDE = False


@unittest.skipUnless(HAS_PYSIDE, "PySide6 未安装：pip install -r requirements.txt")
class GuiImportTests(unittest.TestCase):
    def _import(self, name):
        importlib.import_module(name)

    def test_core_gui_modules_import(self):
        for name in ("gui.theme", "gui.workers", "gui.settings_store"):
            with self.subTest(module=name):
                self._import(name)

    def test_main_window_import(self):
        # gui.main_window 尚未合入时跳过；文件出现后此断言自动生效
        try:
            self._import("gui.main_window")
        except ModuleNotFoundError as e:
            if e.name == "gui.main_window":
                self.skipTest("gui.main_window 尚不存在（开发中）")
            raise

    def test_pages_import(self):
        for name in ("gui.pages.dashboard", "gui.pages.service",
                     "gui.pages.rules", "gui.pages.diagnostics",
                     "gui.pages.speedtest", "gui.pages.logs",
                     "gui.pages.tun", "gui.pages.certificates",
                     "gui.pages.settings"):
            with self.subTest(module=name):
                self._import(name)

    def test_offscreen_main_window_lifecycle(self):
        import os
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PySide6.QtWidgets import QApplication
        from gui.main_window import MainWindow
        app = QApplication.instance() or QApplication([])
        win = MainWindow()
        self.assertEqual(win.stack.count(), 9)
        for i in range(win.stack.count()):
            win.sidebar.select(i)
            win._nav(i)
            self.assertIsNotNone(win.stack.widget(i))
        win._really_quit = True
        win.close()

    def test_probe_worker_delivers_result(self):
        """回归测试：点击“开始智能探测”后必须正常返回结果而不是退出程序。"""
        import os
        import time
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PySide6.QtWidgets import QApplication
        from gui.main_window import MainWindow
        from services import probe_service

        app = QApplication.instance() or QApplication([])
        win = MainWindow()
        page = win.stack.widget(2)
        original = probe_service.probe_domain_smart

        def fake_probe(domain, on_progress=None):
            if on_progress:
                on_progress("fake progress")
            return {
                "success": True,
                "domain": domain,
                "bare_domain": domain,
                "best_ip": "1.2.3.4",
                "best_sni": "www.zhihu.com",
                "latency_ms": 1.0,
                "verify_level": "chain",
                "recommended_suffix": domain,
            }

        try:
            probe_service.probe_domain_smart = fake_probe
            page.inp_probe_domain.setText("example.com")
            page._start_probe()
            deadline = time.time() + 5
            while page._probing and time.time() < deadline:
                app.processEvents()
                time.sleep(0.01)
            self.assertFalse(page._probing, "探测线程未在超时前结束")
            self.assertIsNotNone(page._current_probe_result)
            self.assertTrue(page._current_probe_result["success"])
            self.assertTrue(page.btn_start_probe.isEnabled())
        finally:
            probe_service.probe_domain_smart = original
            win._really_quit = True
            win.close()

    def test_build_qss_contains_glass_panel(self):
        from gui.theme import build_qss
        qss = build_qss({"theme": "dark", "glass": True,
                         "glass_strength": 60, "font_scale": 0})
        self.assertIsInstance(qss, str)
        self.assertIn("GlassPanel", qss)

    def test_theme_resolution_and_switching(self):
        import os
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PySide6.QtWidgets import QApplication
        from gui.theme import resolve_theme_id, palette, build_qss
        from gui.main_window import MainWindow

        self.assertIn(resolve_theme_id({"theme": "system"}), ("dark", "light"))
        self.assertEqual(resolve_theme_id({"theme": "dark"}), "dark")
        self.assertEqual(resolve_theme_id({"theme": "light"}), "light")

        app = QApplication.instance() or QApplication([])
        win = MainWindow()

        # Switch to light
        win.settings.set("theme", "light")
        self.assertEqual(win.settings_page.combo_theme.currentIndex(), 2)

        # Switch to dark
        win.settings.set("theme", "dark")
        self.assertEqual(win.settings_page.combo_theme.currentIndex(), 1)

        # Switch to system
        win.settings.set("theme", "system")
        self.assertEqual(win.settings_page.combo_theme.currentIndex(), 0)

        # Tray hide & settings autostart widget existence
        self.assertTrue(hasattr(win.settings_page, "check_autostart"))
        self.assertTrue(hasattr(win.settings_page, "btn_hide_tray"))
        win._hide_to_tray()
        self.assertFalse(win.isVisible())
        win._tray_show()

        # TunPage saved profiles table & ProfileEditorDialog smoke check
        from gui.pages.tun import ProfileEditorDialog
        dlg = ProfileEditorDialog(profile={
            "id": "p1", "name": "测试线路", "protocol": "socks5",
            "server": "127.0.0.1", "port": 18081, "username": "u", "password": "p",
        }, parent=win)
        d = dlg.profile_data()
        self.assertEqual(d["name"], "测试线路")
        self.assertEqual(d["server"], "127.0.0.1")
        dlg.close()

        win._really_quit = True
        win.close()


if __name__ == "__main__":
    unittest.main()
