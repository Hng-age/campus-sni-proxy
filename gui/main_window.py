"""Frameless glassmorphism main window: sidebar + pages + background jobs.

Threading rules (design doc §5.4):
- every slow operation (status collection, lifecycle actions, diagnostics)
  runs in a FuncWorker QThread and reports back via signals only;
- the GUI never blocks; overlapping mutations are refused while busy.
"""

import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import (
    QBrush, QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen,
    QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QMainWindow, QMenu, QMessageBox,
    QStackedWidget, QSystemTrayIcon, QVBoxLayout, QWidget,
)

from gui import theme
from gui.components.title_bar import TitleBar
from gui.pages.certificates import CertificatesPage
from gui.pages.dashboard import DashboardPage
from gui.pages.diagnostics import DiagnosticsPage
from gui.pages.logs import LogsPage
from gui.pages.rules import RulesPage
from gui.pages.service import ServicePage
from gui.pages.settings import SettingsPage
from gui.pages.speedtest import SpeedTestPage
from gui.pages.tun import TunPage
from gui.settings_store import SettingsStore
from gui.sidebar import Sidebar
from gui.workers import FuncWorker
from services import process_manager
from services.config_manager import APP_NAME
from services.status_monitor import collect_snapshot
from sni_proxy.config import VERSION

POLL_MS = 3000


class BackgroundWidget(QWidget):
    """Clean minimalist flat background canvas with crisp 1px outer frame."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pal = None
        self._cache = None
        self.setAttribute(Qt.WA_StyledBackground, False)

    def set_palette(self, pal):
        if self._pal is not pal:
            self._pal = pal
            self._cache = None
            self.update()

    def paintEvent(self, _e):
        if not self._pal:
            return
        if self._cache is None or self._cache.size() != self.size():
            self._build()
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._cache)

    def _build(self):
        pm = QPixmap(self.size())
        pm.fill(QColor(self._pal["bg_top"]))
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())
        is_light = self._pal.get("id") == "light"
        border_col = QColor("#CBD5E1") if is_light else QColor("#232D3F")
        p.setPen(QPen(border_col, 1.0))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0), 10, 10)
        p.end()
        self._cache = pm


class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} v{VERSION}")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setMinimumSize(860, 560)
        self.setMouseTracking(True)
        self._init_window_size()

        self.settings = SettingsStore(self)
        self.last_snapshot = {}
        self._busy = False
        self._action_stalled = False
        self._snap_worker = None
        self._action_worker = None
        self._workers = []

        # 操作超时兜底：后台动作卡死时也要解锁界面，避免按钮永久置灰
        self._action_watchdog = QTimer(self)
        self._action_watchdog.setSingleShot(True)
        self._action_watchdog.setInterval(180000)
        self._action_watchdog.timeout.connect(self._on_action_stall)

        # ------- central layout over painted background
        self.bg = BackgroundWidget()
        self.setCentralWidget(self.bg)
        root = QVBoxLayout(self.bg)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.title_bar = TitleBar(VERSION, self.bg)
        self.title_bar.tray_requested.connect(self._hide_to_tray)
        self.title_bar.minimize_requested.connect(self.showMinimized)
        self.title_bar.maximize_requested.connect(self._toggle_maximize)
        self.title_bar.close_requested.connect(self.close)
        root.addWidget(self.title_bar)

        body = QHBoxLayout()
        body.setContentsMargins(12, 10, 12, 12)
        body.setSpacing(12)
        root.addLayout(body, 1)

        self.sidebar = Sidebar(VERSION, self.bg)
        self.sidebar.nav_changed.connect(self._nav)
        self.sidebar.about_clicked.connect(self._show_about)
        self.sidebar.help_clicked.connect(self._show_help)
        body.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        self.stack.setAttribute(Qt.WA_StyledBackground, False)
        body.addWidget(self.stack, 1)

        # ------- pages (order matches sidebar NAV_ITEMS)
        self.dash_page = DashboardPage(self)
        self.service_page = ServicePage(self)
        self.rules_page = RulesPage(self)
        self.diag_page = DiagnosticsPage(self)
        self.speed_page = SpeedTestPage(self)
        self.logs_page = LogsPage(self)
        self.tun_page = TunPage(self)
        self.cert_page = CertificatesPage(self)
        self.settings_page = SettingsPage(self)
        for p in (self.dash_page, self.service_page, self.rules_page, self.diag_page,
                  self.speed_page, self.logs_page, self.tun_page, self.cert_page, self.settings_page):
            self.stack.addWidget(p)
            p.request_action.connect(self._run_action)

        # ------- theme + tray
        snap = self.settings.snapshot()
        self._apply_current_theme(snap)
        self.settings.changed.connect(self._on_settings_changed)
        self._build_tray()

        # ------- system theme listener (real-time follow system color)
        app = QApplication.instance()
        if app and hasattr(app.styleHints(), "colorSchemeChanged"):
            app.styleHints().colorSchemeChanged.connect(self._on_sys_theme_changed)

        # ------- status polling
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(POLL_MS)
        self.poll_timer.timeout.connect(self.refresh_now)
        self.poll_timer.start()
        self.refresh_now()

    # ------------------------------------------------------------ window
    def _init_window_size(self):
        screen = QApplication.primaryScreen()
        if screen:
            g = screen.availableGeometry()
            # 自动适配屏幕大小：取屏幕 88% 空间，在 880x560 与 1160x730 之间弹性适配
            target_w = min(1160, max(880, int(g.width() * 0.88)))
            target_h = min(730, max(560, int(g.height() * 0.88)))
            self.resize(target_w, target_h)
            self.move(g.center().x() - target_w // 2,
                      g.center().y() - target_h // 2)
        else:
            self.resize(1024, 640)

    def _center(self):
        screen = QApplication.primaryScreen()
        if not screen:
            return
        g = screen.availableGeometry()
        self.move(g.center().x() - self.width() // 2,
                  g.center().y() - self.height() // 2)

    def _toggle_maximize(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def showEvent(self, event):
        super().showEvent(event)
        self._ensure_win32_taskbar_toggle()

    def _ensure_win32_taskbar_toggle(self):
        """Allow Windows taskbar icon click to minimize and restore the frameless window."""
        import os
        if os.name != "nt":
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            GWL_STYLE = -16
            WS_MINIMIZEBOX = 0x00020000
            WS_MAXIMIZEBOX = 0x00010000
            WS_SYSMENU = 0x00080000
            cur = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
            want = cur | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_SYSMENU
            if cur != want:
                ctypes.windll.user32.SetWindowLongW(hwnd, GWL_STYLE, want)
        except Exception:
            pass

    # frameless edge resize (empty margins propagate mouse events here)
    _EDGE = 6

    def _edge_at(self, pos):
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        left = x <= self._EDGE
        right = x >= w - self._EDGE
        top = y <= self._EDGE
        bottom = y >= h - self._EDGE
        if top and left:
            return Qt.TopLeftCorner
        if top and right:
            return Qt.TopRightCorner
        if bottom and left:
            return Qt.BottomLeftCorner
        if bottom and right:
            return Qt.BottomRightCorner
        if left:
            return Qt.LeftEdge
        if right:
            return Qt.RightEdge
        if top:
            return Qt.TopEdge
        if bottom:
            return Qt.BottomEdge
        return None

    _CURSORS = {
        Qt.TopLeftCorner: Qt.SizeFDiagCursor,
        Qt.BottomRightCorner: Qt.SizeFDiagCursor,
        Qt.TopRightCorner: Qt.SizeBDiagCursor,
        Qt.BottomLeftCorner: Qt.SizeBDiagCursor,
        Qt.LeftEdge: Qt.SizeHorCursor,
        Qt.RightEdge: Qt.SizeHorCursor,
        Qt.TopEdge: Qt.SizeVerCursor,
        Qt.BottomEdge: Qt.SizeVerCursor,
    }

    def _start_geo(self, g, edge):
        x, y, w, h = g.x(), g.y(), g.width(), g.height()
        return {"x": x, "y": y, "w": w, "h": h, "edge": edge}

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and not self.isMaximized():
            edge = self._edge_at(e.position().toPoint())
            if edge:
                self._resize_state = self._start_geo(self.frameGeometry(),
                                                      edge)
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        edge = self._edge_at(e.position().toPoint())
        cursor = self._CURSORS.get(edge) if edge and not self.isMaximized() \
            else None
        if cursor:
            self.setCursor(cursor)
        state = getattr(self, "_resize_state", None)
        if state and e.buttons() & Qt.LeftButton:
            self._apply_resize(state, e.globalPosition().toPoint())
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._resize_state = None
        self.unsetCursor()
        super().mouseReleaseEvent(e)

    def _apply_resize(self, state, gpos):
        dx = gpos.x() - state["x"]
        dy = gpos.y() - state["y"]
        x, y = state["x"], state["y"]
        w, h = state["w"], state["h"]
        edge = state["edge"]
        if edge in (Qt.RightEdge, Qt.TopRightCorner, Qt.BottomRightCorner):
            w = max(self.minimumWidth(), state["w"] + dx)
        if edge in (Qt.BottomEdge, Qt.BottomLeftCorner, Qt.BottomRightCorner):
            h = max(self.minimumHeight(), state["h"] + dy)
        if edge in (Qt.LeftEdge, Qt.TopLeftCorner, Qt.BottomLeftCorner):
            dx2 = min(dx, w - self.minimumWidth())
            x = state["x"] + dx2
            w = state["w"] - dx2
        if edge in (Qt.TopEdge, Qt.TopLeftCorner, Qt.TopRightCorner):
            dy2 = min(dy, h - self.minimumHeight())
            y = state["y"] + dy2
            h = state["h"] - dy2
        self.setGeometry(x, y, w, h)

    # ------------------------------------------------------------- nav
    def _nav(self, index):
        self.stack.setCurrentIndex(index)
        page = self.stack.widget(index)
        if page:
            page.activate()

    def _show_about(self):
        from services.config_manager import env_info
        info = env_info()
        QMessageBox.about(
            self, "关于",
            f"<b>{APP_NAME} v{VERSION}</b><br><br>"
            f"本地网络代理管理、证书状态管理与授权环境下的网络诊断工具。<br><br>"
            f"Python {info['python']}<br>"
            f"OpenSSL {info['openssl_version']}<br>"
            f"本地监听 {info['listen']}<br><br>"
            f"命令行入口保留（SNI代理_一键启动.bat / start.bat）。")

    def _show_help(self):
        QMessageBox.information(
            self, "使用帮助",
            "・运行管理：启动/停止/重启代理，并接管或恢复系统代理。\n"
            "・规则管理：一键智能探测阻断域名，自动学习可用的伪装 SNI 与边缘 IP。\n"
            "・网络诊断：一键检查网络接口、DNS、端口、系统代理与证书状态。\n"
            "・网络测速：对比直连与本地代理通道的带宽、延迟和抖动。\n"
            "・日志中心：实时查看运行日志并导出。\n"
            "・TUN / VPN：填写共享代理 IP/端口/账号密码，创建虚拟网卡接管整机 App，支持规则/全局切换。\n"
            "・证书管理：查看设备 CA、安装或移除根证书。\n"
            "・设置中心：主题、玻璃效果、字体、托盘行为与诊断脱敏。\n\n"
            "如遇异常，可用 SNI代理_一键启动.bat / start.bat 命令行入口恢复环境。")

    # --------------------------------------------------------- settings
    def _apply_current_theme(self, settings):
        pal = theme.palette(settings)
        theme.apply_theme(QApplication.instance(), settings)
        self.bg.set_palette(pal)
        self.title_bar.set_palette(pal)
        self.sidebar.set_palette(pal)
        self.dash_page.set_palette(pal)
        if hasattr(self, "rules_page") and hasattr(self.rules_page, "set_palette"):
            self.rules_page.set_palette(pal)
        if hasattr(self, "tun_page") and hasattr(self.tun_page, "set_palette"):
            self.tun_page.set_palette(pal)
        if hasattr(self, "speed_page") and hasattr(self.speed_page, "set_palette"):
            self.speed_page.set_palette(pal)
        if hasattr(self.service_page, "log") and hasattr(self.service_page.log, "set_palette"):
            self.service_page.log.set_palette(pal)
        if hasattr(self.logs_page, "viewer") and hasattr(self.logs_page.viewer, "set_palette"):
            self.logs_page.viewer.set_palette(pal)

    def _on_sys_theme_changed(self):
        snap = self.settings.snapshot()
        if snap.get("theme", "system") == "system":
            self._apply_current_theme(snap)

    def _on_settings_changed(self, settings):
        self._apply_current_theme(settings)
        for i in range(self.stack.count()):
            page = self.stack.widget(i)
            if page is not self:
                try:
                    page.on_settings_changed(settings)
                except AttributeError:
                    pass

    # -------------------------------------------------------- tray icon
    def _build_tray(self):
        self._tray_tip_shown = False
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        menu = QMenu()
        self._act_toggle = menu.addAction("显示 / 隐藏主窗口")
        self._act_toggle.triggered.connect(self._tray_toggle)
        menu.addSeparator()

        act_start_sni = menu.addAction("▶ 启动 SNI 代理")
        act_start_sni.triggered.connect(lambda: self._run_action("start"))
        act_stop_sni = menu.addAction("■ 停止 SNI 代理")
        act_stop_sni.triggered.connect(lambda: self._run_action("stop"))
        menu.addSeparator()

        act_start_tun = menu.addAction("🛰 启动 TUN / VPN")
        act_start_tun.triggered.connect(lambda: self._run_action("start-tun"))
        act_stop_tun = menu.addAction("■ 停止 TUN / VPN")
        act_stop_tun.triggered.connect(lambda: self._run_action("stop-tun"))
        menu.addSeparator()

        act_settings = menu.addAction("⚙ 打开设置中心")
        act_settings.triggered.connect(self._tray_open_settings)
        act_refresh = menu.addAction("🔄 立即刷新状态")
        act_refresh.triggered.connect(self.refresh_now)
        menu.addSeparator()

        act_quit = menu.addAction("完全退出")
        act_quit.triggered.connect(self._quit_app)
        self.tray_menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.setToolTip(f"{APP_NAME} v{VERSION}")
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()

    def _tray_show(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _tray_toggle(self):
        """单击托盘/任务栏图标：显示窗口；再次单击最小化。"""
        if self.isVisible() and not self.isMinimized():
            self.showMinimized()
        else:
            self._tray_show()

    def reveal_window(self):
        """从托盘、最小化或后台状态唤回唯一窗口（供第二实例唤起调用）。"""
        self._tray_show()

    def _tray_open_settings(self):
        self._tray_show()
        idx = self.stack.indexOf(self.settings_page)
        if idx >= 0:
            self.sidebar.select(idx)
            self._nav(idx)

    def _hide_to_tray(self):
        self.hide()
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
            if not getattr(self, "_tray_tip_shown", False):
                self._tray_tip_shown = True
                self.tray.showMessage(
                    f"{APP_NAME} 已在后台运行",
                    "窗口已隐藏至系统托盘，单击托盘图标可随时恢复。"
                )

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._tray_toggle()

    def _quit_app(self):
        self._really_quit = True
        self.close()
        app = QApplication.instance()
        if app:
            app.quit()

    # --------------------------------------------------- status polling
    def _track_worker(self, worker, attr):
        """Register a worker and release it after it finishes.

        QThread objects are parented to the window, so without deleteLater
        every 3s poll would leave a finished QThread alive forever.
        """
        self._workers.append(worker)

        def _finish():
            try:
                self._workers.remove(worker)
            except ValueError:
                pass
            if getattr(self, attr, None) is worker:
                setattr(self, attr, None)
            worker.deleteLater()

        worker.finished.connect(_finish)
        return worker

    def refresh_now(self):
        w = self._snap_worker
        if w is not None:
            try:
                if w.isRunning():
                    return
            except RuntimeError:
                self._snap_worker = None
        self._snap_worker = self._track_worker(
            FuncWorker(lambda _progress: collect_snapshot(), parent=self),
            "_snap_worker")
        self._snap_worker.done.connect(self._on_snapshot)
        self._snap_worker.start()

    def _on_snapshot(self, snap, error):
        if error or not snap:
            self.title_bar.set_chip("状态读取失败", "#EF6464")
            return
        self.last_snapshot = snap
        if snap["running"]:
            if not snap["proxy"]["enabled"] or not snap["proxy_points_at_us"]:
                self.title_bar.set_chip("系统正常 · 代理未生效", "#EAB54A")
            else:
                self.title_bar.set_chip("系统正常", "#10B981")
        elif snap["listener_pid"]:
            self.title_bar.set_chip("端口被占用", "#EF6464")
        else:
            self.title_bar.set_chip("服务已停止", "#94A3B8")
        self.dash_page.update_snapshot(snap)
        self.service_page.update_snapshot(snap)
        self.cert_page.update_snapshot(snap)

    # ------------------------------------------------------- lifecycle
    def confirm_and_run(self, action, title, body, confirm_btn="确定"):
        """Show impact description, then run one lifecycle action."""
        if self._busy:
            QMessageBox.information(
                self, "操作进行中", "已有操作正在执行，请等待完成后再试。")
            return
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(body)
        box.setIcon(QMessageBox.Question)
        box.addButton("取消", QMessageBox.RejectRole)
        go = box.addButton(confirm_btn, QMessageBox.AcceptRole)
        box.setDefaultButton(go)
        box.exec()
        if box.clickedButton() is go:
            self._run_action(action)

    def _run_action(self, action):
        if self._busy:
            return
        self._busy = True
        self._action_stalled = False
        self._action_watchdog.start()
        for i in range(self.stack.count()):
            page = self.stack.widget(i)
            try:
                page.on_action_started(action)
            except AttributeError:
                pass

        def job(on_progress):
            run = process_manager.ActionRun(action, on_line=on_progress)
            self._action_run = run
            return run.run()

        self._action_tail = []
        self._action_worker = self._track_worker(
            FuncWorker(job, parent=self), "_action_worker")
        # 两个接收者都是 QObject 绑定方法，Qt 会自动排队到 GUI 线程执行；
        # 不能用普通函数闭包直接更新界面（会在 worker 线程里动控件）
        self._action_worker.progress.connect(
            self.service_page.append_action_line)
        self._action_worker.progress.connect(self._record_action_line)
        self._action_worker.done.connect(self._action_done)
        self._action_worker.start()

    def _record_action_line(self, line):
        """GUI 线程内记录最近的操作输出，供失败弹窗展示。"""
        self._action_tail.append(line)
        if len(self._action_tail) > 200:
            del self._action_tail[:-200]

    def _action_done(self, result, error):
        worker = self.sender()
        if worker is not None and worker is not self._action_worker:
            return      # 已被超时兜底解锁的旧操作，忽略迟到的回调
        self._action_watchdog.stop()
        self._busy = False
        ok = bool(result and result[0])
        if error:
            ok = False
        for i in range(self.stack.count()):
            page = self.stack.widget(i)
            try:
                page.on_action_finished(ok)
            except AttributeError:
                pass
        if not ok:
            if getattr(self, "_action_stalled", False):
                self._action_stalled = False
                self.refresh_now()
                return
            detail = "操作失败或被取消，详见“运行管理”页的操作输出。"
            tail = [ln for ln in getattr(self, "_action_tail", []) if ln.strip()]
            if error:
                detail += f"\n\n执行异常：{error}"
            if tail:
                detail += "\n\n最近输出：\n" + "\n".join(tail[-8:])
            detail += "\n（若弹出的 UAC 提权窗口被取消，也会视为未完成）"
            QMessageBox.warning(self, "操作未完成", detail)
        self._action_stalled = False
        self.refresh_now()

    def _on_action_stall(self):
        """后台动作超过 3 分钟没有结果：先解锁界面，避免按钮永久不可用。"""
        if not self._busy:
            return
        self._busy = False
        self._action_stalled = True
        for i in range(self.stack.count()):
            page = self.stack.widget(i)
            try:
                page.on_action_finished(False)
            except AttributeError:
                pass
        QMessageBox.information(
            self, "操作超时",
            "后台操作超过 3 分钟仍未返回，已先解除界面锁定。\n"
            "请稍后在页面上查看实际状态；若仍未生效，可重新点击对应按钮重试。")
        self.refresh_now()

    # ------------------------------------------------------- close/quit
    def closeEvent(self, event):
        to_tray = bool(self.settings.get("minimize_to_tray", True))
        if (to_tray and not getattr(self, "_really_quit", False)
                and QSystemTrayIcon.isSystemTrayAvailable()):
            event.ignore()
            self._hide_to_tray()
            return
        self.poll_timer.stop()
        if hasattr(self, "tun_page") and hasattr(self.tun_page, "poll_timer"):
            self.tun_page.poll_timer.stop()
        try:
            self.tray.hide()
        except Exception:
            pass
        # let in-flight workers settle so QThreads are not destroyed running
        all_workers = list(self._workers)
        if hasattr(self, "tun_page"):
            all_workers.extend(getattr(self.tun_page, "_workers", []))
        for w in all_workers:
            try:
                if w.isRunning():
                    w.wait(1500)
            except RuntimeError:
                pass
        event.accept()
