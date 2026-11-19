"""Custom frameless title bar matching the 2.0.0 design with live ticking status."""

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class TitleBar(QWidget):
    """Brand + live ticking status (● 系统正常 | YYYY-MM-DD HH:MM:SS) + window buttons."""

    minimize_requested = Signal()
    maximize_requested = Signal()
    close_requested = Signal()

    def __init__(self, version, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setFixedHeight(48)
        self._drag_pos = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 0, 14, 0)
        lay.setSpacing(12)

        # Left subtle title
        self.title_lab = QLabel(
            f"SNI Proxy Desktop - 校园网 SNI 代理管理与诊断工具 v{version}")
        self.title_lab.setStyleSheet(
            "color: #94A3B8; font-size: 10pt; background: transparent; font-weight: 500;")
        lay.addWidget(self.title_lab)
        lay.addStretch(1)

        # Right live status indicator
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet(
            "color: #10B981; font-size: 11pt; background: transparent;")
        lay.addWidget(self.status_dot)

        self.status_text = QLabel("系统正常")
        self.status_text.setStyleSheet(
            "color: #10B981; font-size: 9.5pt; font-weight: 600; background: transparent;")
        lay.addWidget(self.status_text)

        self.sep_lab = QLabel("|")
        self.sep_lab.setStyleSheet("color: #475569; font-size: 9pt; background: transparent;")
        lay.addWidget(self.sep_lab)

        self.clock_lab = QLabel(time.strftime("%Y-%m-%d %H:%M:%S"))
        self.clock_lab.setStyleSheet(
            "color: #94A3B8; font-size: 9.5pt; background: transparent; font-family: monospace;")
        lay.addWidget(self.clock_lab)

        lay.addSpacing(14)

        # Window controls
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
        btn_close.setToolTip("关闭")
        btn_close.clicked.connect(self.close_requested.emit)

        for b in (btn_min, btn_max, btn_close):
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedSize(36, 28)
            lay.addWidget(b)

        # 1-second clock timer
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_palette(self, pal):
        is_light = pal.get("id") == "light"
        text_col = "#475569" if is_light else "#94A3B8"
        sep_col = "#CBD5E1" if is_light else "#475569"
        self.title_lab.setStyleSheet(
            f"color: {text_col}; font-size: 10pt; background: transparent; font-weight: 500;")
        self.clock_lab.setStyleSheet(
            f"color: {text_col}; font-size: 9.5pt; background: transparent; font-family: monospace;")
        self.sep_lab.setStyleSheet(
            f"color: {sep_col}; font-size: 9pt; background: transparent;")

    def _tick(self):
        self.clock_lab.setText(time.strftime("%Y-%m-%d %H:%M:%S"))

    def set_chip(self, text, color):
        """Update system status text & dot color."""
        self.status_text.setText(text)
        self.status_text.setStyleSheet(
            f"color: {color}; font-size: 9.5pt; font-weight: 600; background: transparent;")
        self.status_dot.setStyleSheet(
            f"color: {color}; font-size: 11pt; background: transparent;")

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
