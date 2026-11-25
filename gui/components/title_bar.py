"""Minimalist frameless title bar with live status chip and hide-to-tray button."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class TitleBar(QWidget):
    """Slim title bar: app title, status indicator, hide-to-tray & window buttons."""

    tray_requested = Signal()
    minimize_requested = Signal()
    maximize_requested = Signal()
    close_requested = Signal()

    def __init__(self, version, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setFixedHeight(40)
        self._drag_pos = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 10, 0)
        lay.setSpacing(10)

        self.title_lab = QLabel(f"toci  v{version}")
        self.title_lab.setObjectName("TitleBarText")
        lay.addWidget(self.title_lab)
        lay.addStretch(1)

        # Clean status pill
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet(
            "color: #94A3B8; font-size: 9pt; background: transparent;")
        lay.addWidget(self.status_dot)

        self.status_text = QLabel("服务已停止")
        self.status_text.setStyleSheet(
            "color: #94A3B8; font-size: 9pt; font-weight: 600; background: transparent;")
        lay.addWidget(self.status_text)

        lay.addSpacing(8)

        btn_tray = QPushButton("托盘")
        btn_tray.setObjectName("SecondaryBtnSmall")
        btn_tray.setCursor(Qt.PointingHandCursor)
        btn_tray.setFixedHeight(24)
        btn_tray.setToolTip("隐藏主窗口到系统托盘后台运行")
        btn_tray.clicked.connect(self.tray_requested.emit)
        lay.addWidget(btn_tray)

        btn_min = QPushButton("—")
        btn_min.setObjectName("WinBtn")
        btn_min.setToolTip("最小化")
        btn_min.clicked.connect(self.minimize_requested.emit)

        btn_max = QPushButton("▢")
        btn_max.setObjectName("WinBtn")
        btn_max.setToolTip("最大化 / 还原")
        btn_max.clicked.connect(self.maximize_requested.emit)

        btn_close = QPushButton("✕")
        btn_close.setObjectName("WinBtnClose")
        btn_close.setToolTip("关闭（若开启托盘驻留则隐藏到托盘）")
        btn_close.clicked.connect(self.close_requested.emit)

        for b in (btn_min, btn_max, btn_close):
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedSize(32, 26)
            lay.addWidget(b)

    def set_palette(self, pal):
        text_col = pal.get("muted", "#64748B")
        self.title_lab.setStyleSheet(
            f"color: {text_col}; font-size: 9.5pt; background: transparent; font-weight: 500;")

    def set_chip(self, text, color):
        """Update system status text & dot color."""
        self.status_text.setText(text)
        self.status_text.setStyleSheet(
            f"color: {color}; font-size: 9pt; font-weight: 600; background: transparent;")
        self.status_dot.setStyleSheet(
            f"color: {color}; font-size: 9pt; background: transparent;")

    # ------------------------------------------------------ window drag
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            win = self.window()
            if win.isMaximized():
                return
            self._drag_pos = (e.globalPosition().toPoint(), win.frameGeometry().topLeft())
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() & Qt.LeftButton:
            gpos, origin = self._drag_pos
            self.window().move(origin + (e.globalPosition().toPoint() - gpos))
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag_pos = None
        e.accept()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.maximize_requested.emit()
