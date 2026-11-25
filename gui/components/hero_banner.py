"""Minimalist status hero card with clean indicator and uptime pill."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout,
)


class HeroBanner(QFrame):
    """Clean minimalist status banner with subtle indicator and runtime readout."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("GlassPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(84)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._running = False
        self._pal = {}

        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(14)

        self.badge = QLabel("●")
        self.badge.setFixedSize(40, 40)
        self.badge.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.badge)

        mid = QVBoxLayout()
        mid.setSpacing(2)
        mid.setAlignment(Qt.AlignVCenter)
        self.title_lab = QLabel("代理服务已停止")
        self.title_lab.setStyleSheet(
            "font-size: 14pt; font-weight: 700; background: transparent;")
        self.sub_lab = QLabel("服务未启动，点击下方「启动服务」开始代理")
        self.sub_lab.setObjectName("MutedLabel")
        self.sub_lab.setWordWrap(True)
        self.sub_lab.setMinimumWidth(0)
        mid.addWidget(self.title_lab)
        mid.addWidget(self.sub_lab)
        lay.addLayout(mid, 1)

        self.capsule = QFrame()
        self.capsule.setObjectName("StatusCard")
        self.capsule.setFixedHeight(48)
        cap_lay = QVBoxLayout(self.capsule)
        cap_lay.setContentsMargins(14, 6, 14, 6)
        cap_lay.setSpacing(0)
        cap_lay.setAlignment(Qt.AlignCenter)

        self.cap_title = QLabel("运行时长")
        self.cap_title.setObjectName("TinyLabel")
        self.cap_title.setAlignment(Qt.AlignCenter)
        self.uptime_lab = QLabel("--:--:--")
        self.uptime_lab.setAlignment(Qt.AlignCenter)
        self.uptime_lab.setStyleSheet(
            "font-size: 11.5pt; font-weight: 700; font-family: Consolas, monospace; background: transparent;")
        cap_lay.addWidget(self.cap_title)
        cap_lay.addWidget(self.uptime_lab)
        lay.addWidget(self.capsule)

        self.set_state(False)

    def set_palette(self, pal):
        self._pal = pal
        text_col = pal.get("text", "#0F172A")
        self.title_lab.setStyleSheet(
            f"color: {text_col}; font-size: 14pt; font-weight: 700; background: transparent;")
        self.uptime_lab.setStyleSheet(
            f"color: {text_col}; font-size: 11.5pt; font-weight: 700; font-family: Consolas, monospace; background: transparent;")
        self.update()

    def set_state(self, running, uptime_str="--", custom_title=None, custom_sub=None):
        self._running = running
        self.uptime_lab.setText(uptime_str if running else "--:--:--")

        if running:
            self.badge.setText("✔")
            self.badge.setStyleSheet("""
                QLabel {
                    background: rgba(16, 185, 129, 0.16);
                    border: 1px solid rgba(16, 185, 129, 0.45);
                    border-radius: 20px;
                    font-size: 16px;
                    font-weight: bold;
                    color: #10B981;
                }
            """)
            self.title_lab.setText(custom_title or "代理服务运行正常")
            self.sub_lab.setText(custom_sub or "本地 SNI 代理已就绪，网络转发稳定")
        else:
            self.badge.setText("●")
            self.badge.setStyleSheet("""
                QLabel {
                    background: rgba(148, 163, 184, 0.14);
                    border: 1px solid rgba(148, 163, 184, 0.35);
                    border-radius: 20px;
                    font-size: 14px;
                    color: #94A3B8;
                }
            """)
            self.title_lab.setText(custom_title or "代理服务已停止")
            self.sub_lab.setText(custom_sub or "点击下方「启动服务」或前往「TUN / VPN」接管整机流量")
        self.update()
