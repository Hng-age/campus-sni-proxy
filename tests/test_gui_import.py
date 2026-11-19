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
                     "gui.pages.diagnostics", "gui.pages.speedtest",
                     "gui.pages.logs", "gui.pages.certificates",
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
        self.assertEqual(win.stack.count(), 7)
        for i in range(win.stack.count()):
            win.sidebar.select(i)
            win._nav(i)
            self.assertIsNotNone(win.stack.widget(i))
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

        win.close()


if __name__ == "__main__":
    unittest.main()
