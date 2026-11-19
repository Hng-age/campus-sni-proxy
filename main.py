"""SNI Proxy Desktop - 校园网 SNI 代理 GUI 入口（v2.0.0）。

用法：
    python main.py              启动桌面 GUI
    python main.py --version   打印版本并退出

命令行管理入口保留：SNI代理_一键启动.bat / start.bat（原菜单）。
"""

import os
import sys


def _make_icon():
    """Programmatic app icon: gradient rounded square with an S."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import (
        QBrush, QColor, QFont, QIcon, QLinearGradient, QPainter, QPixmap,
    )
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QLinearGradient(0, 0, 64, 64)
    grad.setColorAt(0.0, QColor("#4779E8"))
    grad.setColorAt(1.0, QColor("#8B72D9"))
    p.setBrush(QBrush(grad))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(4, 4, 56, 56, 14, 14)
    p.setPen(QColor("#FFFFFF"))
    f = QFont("Segoe UI", 30, QFont.Bold)
    p.setFont(f)
    p.drawText(pm.rect(), Qt.AlignCenter, "S")
    p.end()
    return QIcon(pm)


def main():
    import traceback

    try:
        from sni_proxy.config import VERSION

        if "--version" in sys.argv:
            try:
                print(f"SNI Proxy Desktop v{VERSION}")
            except Exception:
                pass
            return 0

        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication

        from gui import theme
        from gui.main_window import MainWindow
        from gui.settings_store import SettingsStore
        from services.config_manager import APP_NAME

        app = QApplication(sys.argv)
        app.setApplicationName(APP_NAME)
        app.setApplicationVersion(VERSION)
        app.setOrganizationName("SNIProxy")

        from PySide6.QtGui import QIcon

        ico_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.ico")
        if os.path.exists(ico_path):
            app.setWindowIcon(QIcon(ico_path))
        else:
            app.setWindowIcon(_make_icon())

        store = SettingsStore()
        theme.apply_theme(app, store.snapshot())

        win = MainWindow()
        if not store.get("show_on_start", True):
            win.hide()
            win.tray.show()
        else:
            win.show()
        return app.exec()
    except Exception as e:
        err_msg = traceback.format_exc()
        try:
            if getattr(sys, "frozen", False):
                log_dir = os.path.dirname(os.path.abspath(sys.executable))
            else:
                log_dir = os.path.dirname(os.path.abspath(__file__))
            with open(os.path.join(log_dir, "launch_error.log"), "w",
                      encoding="utf-8") as f:
                f.write(err_msg)
        except Exception:
            pass
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "启动错误", f"程序启动发生异常：\n\n{err_msg}")
        except Exception:
            if sys.stderr is not None:
                print(err_msg, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
