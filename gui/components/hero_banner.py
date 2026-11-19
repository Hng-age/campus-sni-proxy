"""Top Hero Status Banner matching the 2.0.0 mockup with glowing waves and live uptime."""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)


class HeroBanner(QFrame):
    """Large glass banner with glowing status check and live uptime capsule."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("HeroBanner")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._running = False
        self._pal = {}

        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 16, 22, 16)
        lay.setSpacing(18)

        # 1. Left glowing circle badge
        self.badge = QLabel("✔")
        self.badge.setFixedSize(62, 62)
        self.badge.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.badge)

        # 2. Middle status text
        mid = QVBoxLayout()
        mid.setSpacing(4)
        mid.setAlignment(Qt.AlignVCenter)
        self.title_lab = QLabel("代理服务运行正常")
        self.title_lab.setStyleSheet(
            "color: #FFFFFF; font-size: 20pt; font-weight: 700; background: transparent;")
        self.sub_lab = QLabel("校园网 SNI 代理已正常工作，网络连接稳定")
        self.sub_lab.setWordWrap(True)
        self.sub_lab.setMinimumWidth(0)
        self.sub_lab.setStyleSheet(
            "color: #94A3B8; font-size: 11pt; background: transparent;")
        mid.addWidget(self.title_lab)
        mid.addWidget(self.sub_lab)
        lay.addLayout(mid, 1)

        # 3. Right uptime capsule
        self.capsule = QFrame()
        self.capsule.setFixedSize(160, 68)
        self.capsule.setStyleSheet("""
            QFrame {
                background: rgba(15, 23, 42, 0.75);
                border: 1px solid rgba(56, 189, 248, 0.3);
                border-radius: 14px;
            }
        """)
        cap_lay = QHBoxLayout(self.capsule)
        cap_lay.setContentsMargins(12, 8, 12, 8)
        cap_lay.setSpacing(10)

        self.clock_icon = QLabel("🕒")
        self.clock_icon.setStyleSheet("""
            QLabel {
                background: rgba(37, 99, 235, 0.4);
                border-radius: 18px;
                font-size: 18px;
                color: #FFFFFF;
                border: 1px solid rgba(56, 189, 248, 0.3);
            }
        """)
        self.clock_icon.setFixedSize(36, 36)
        self.clock_icon.setAlignment(Qt.AlignCenter)
        cap_lay.addWidget(self.clock_icon)

        cap_col = QVBoxLayout()
        cap_col.setSpacing(1)
        self.cap_title = QLabel("运行时间")
        self.cap_title.setStyleSheet("color: #94A3B8; font-size: 9pt; border: none; background: transparent;")
        self.uptime_lab = QLabel("00:00:00")
        self.uptime_lab.setStyleSheet(
            "color: #F8FAFC; font-size: 14pt; font-weight: 700; border: none; background: transparent;")
        cap_col.addWidget(self.cap_title)
        cap_col.addWidget(self.uptime_lab)
        cap_lay.addLayout(cap_col)

        lay.addWidget(self.capsule)

        self.set_state(False)

    def set_palette(self, pal):
        self._pal = pal
        is_light = pal.get("id") == "light"
        text_col = "#0F172A" if is_light else "#FFFFFF"
        sub_col = "#475569" if is_light else "#94A3B8"
        cap_bg = "rgba(255, 255, 255, 0.90)" if is_light else "rgba(15, 23, 42, 0.75)"
        cap_border = "rgba(203, 213, 225, 0.9)" if is_light else "rgba(56, 189, 248, 0.3)"
        cap_title_col = "#64748B" if is_light else "#94A3B8"
        uptime_col = "#0F172A" if is_light else "#F8FAFC"

        self.title_lab.setStyleSheet(
            f"color: {text_col}; font-size: 20pt; font-weight: 700; background: transparent;")
        self.sub_lab.setStyleSheet(
            f"color: {sub_col}; font-size: 11pt; background: transparent;")
        self.capsule.setStyleSheet(f"""
            QFrame {{
                background: {cap_bg};
                border: 1px solid {cap_border};
                border-radius: 14px;
            }}
        """)
        self.cap_title.setStyleSheet(f"color: {cap_title_col}; font-size: 9pt; border: none; background: transparent;")
        self.uptime_lab.setStyleSheet(
            f"color: {uptime_col}; font-size: 14pt; font-weight: 700; border: none; background: transparent;")
        self.update()

    def set_state(self, running, uptime_str="--", custom_title=None, custom_sub=None):
        self._running = running
        self.uptime_lab.setText(uptime_str if running else "--:--:--")

        if running:
            # Active green theme
            self.badge.setText("✔")
            self.badge.setStyleSheet("""
                QLabel {
                    background: qradialgradient(cx:0.5, cy:0.5, radius:0.65,
                        fx:0.35, fy:0.35,
                        stop:0 #10B981, stop:0.8 #059669, stop:1 rgba(6, 78, 59, 0.9));
                    border: 2px solid rgba(52, 211, 153, 0.8);
                    border-radius: 31px;
                    font-size: 28px;
                    font-weight: bold;
                    color: #FFFFFF;
                }
            """)
            self.title_lab.setText(custom_title or "代理服务运行正常")
            self.sub_lab.setText(custom_sub or "校园网 SNI 代理已正常工作，网络连接稳定")
        else:
            # Stopped dark/red theme
            self.badge.setText("✕")
            self.badge.setStyleSheet("""
                QLabel {
                    background: qradialgradient(cx:0.5, cy:0.5, radius:0.65,
                        fx:0.35, fy:0.35,
                        stop:0 #DC2626, stop:0.8 #991B1B, stop:1 rgba(69, 10, 10, 0.9));
                    border: 2px solid rgba(248, 113, 113, 0.7);
                    border-radius: 31px;
                    font-size: 26px;
                    font-weight: bold;
                    color: #FFFFFF;
                }
            """)
            self.title_lab.setText(custom_title or "代理服务已停止")
            self.sub_lab.setText(custom_sub or "代理未启动，点击右侧「启动服务」开始代理")

        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = float(self.width()), float(self.height())
        rect = QRectF(0, 0, w, h)
        is_light = self._pal.get("id") == "light"

        # 1. Base card background gradient
        bg = QLinearGradient(0, 0, w, h)
        if is_light:
            bg.setColorAt(0.0, QColor("#EFF6FF"))
            bg.setColorAt(0.5, QColor("#E0E7FF"))
            bg.setColorAt(1.0, QColor("#DBEAFE"))
            p.setBrush(QBrush(bg))
            p.setPen(QPen(QColor(191, 219, 254, 220), 1.2))
        else:
            bg.setColorAt(0.0, QColor(14, 25, 52, 210))
            bg.setColorAt(0.5, QColor(18, 32, 66, 190))
            bg.setColorAt(1.0, QColor(10, 18, 40, 220))
            p.setBrush(QBrush(bg))
            p.setPen(QPen(QColor(56, 189, 248, 70), 1.2))
        p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 16, 16)

        # 2. Glowing waves / luminous ribbon lines in the background
        p.save()
        p.setClipRect(rect.adjusted(1, 1, -1, -1))

        # Blue ribbon wave 1
        wave1 = QPainterPath()
        wave1.moveTo(0, h * 0.4)
        wave1.cubicTo(w * 0.3, h * 0.1, w * 0.6, h * 0.9, w, h * 0.3)
        wave1.lineTo(w, h)
        wave1.lineTo(0, h)
        wave1.closeSubpath()
        grad1 = QLinearGradient(0, 0, w, h)
        if is_light:
            grad1.setColorAt(0.0, QColor(59, 130, 246, 30))
            grad1.setColorAt(0.5, QColor(99, 102, 241, 25))
            grad1.setColorAt(1.0, QColor(147, 51, 234, 20))
        else:
            grad1.setColorAt(0.0, QColor(37, 99, 235, 45))
            grad1.setColorAt(0.5, QColor(56, 189, 248, 30))
            grad1.setColorAt(1.0, QColor(139, 92, 246, 25))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad1))
        p.drawPath(wave1)

        # Cyan ribbon wave 2
        pen2 = QPen(QColor(37, 99, 235, 80) if is_light else QColor(56, 189, 248, 80), 1.5)
        p.setPen(pen2)
        p.setBrush(Qt.NoBrush)
        wave2 = QPainterPath()
        wave2.moveTo(w * 0.2, h)
        wave2.cubicTo(w * 0.45, h * 0.2, w * 0.75, h * 0.8, w, h * 0.25)
        p.drawPath(wave2)

        # Violet ribbon line 3
        pen3 = QPen(QColor(124, 58, 237, 70) if is_light else QColor(139, 92, 246, 70), 1.2)
        p.setPen(pen3)
        wave3 = QPainterPath()
        wave3.moveTo(w * 0.1, h * 0.9)
        wave3.cubicTo(w * 0.4, h * 0.15, w * 0.7, h * 0.85, w, h * 0.4)
        p.drawPath(wave3)

        p.restore()
        p.end()
