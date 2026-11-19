"""Metric status card with glowing icon badge and decorative sparkline/chart."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)


class SparklineWidget(QWidget):
    """Mini decorative wave or equalizer chart at the bottom of metric cards."""

    def __init__(self, chart_type="wave", color="#22C58B", parent=None):
        super().__init__(parent)
        self.chart_type = chart_type  # 'wave', 'bars', 'wave_check', 'wave_signal'
        self.base_color = QColor(color)
        self.setFixedHeight(18)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        c = self.base_color

        if self.chart_type == "bars":
            # Purple equalizer bars
            p.setPen(Qt.NoPen)
            num_bars = 7
            bar_w = 4.0
            gap = 3.0
            total_w = num_bars * bar_w + (num_bars - 1) * gap
            start_x = w - total_w - 4
            heights = [0.35, 0.55, 0.4, 0.75, 0.9, 0.6, 1.0]
            for i, frac in enumerate(heights):
                bx = start_x + i * (bar_w + gap)
                bh = (h - 2) * frac
                by = h - bh - 1
                p.setBrush(QColor(c.red(), c.green(), c.blue(), int(140 + frac * 115)))
                p.drawRoundedRect(QRectF(bx, by, bar_w, bh), 1.5, 1.5)

        elif self.chart_type == "wave_signal":
            # Amber wave + 4 signal bars on the right
            pen = QPen(QColor(c.red(), c.green(), c.blue(), 180), 1.5)
            p.setPen(pen)
            path = QPainterPath()
            path.moveTo(4, h * 0.7)
            path.cubicTo(w * 0.2, h * 0.2, w * 0.4, h * 0.9, w * 0.65, h * 0.6)
            p.drawPath(path)
            # Signal bars
            p.setPen(Qt.NoPen)
            for i in range(4):
                bx = w - 24 + i * 5
                bh = 4 + i * 3
                by = h - bh - 2
                p.setBrush(QColor(c.red(), c.green(), c.blue(), 200))
                p.drawRoundedRect(QRectF(bx, by, 3, bh), 1, 1)

        else:
            # Default wave with dot
            pen = QPen(QColor(c.red(), c.green(), c.blue(), 180), 1.5)
            p.setPen(pen)
            path = QPainterPath()
            path.moveTo(4, h * 0.7)
            path.cubicTo(w * 0.25, h * 0.3, w * 0.55, h * 0.85, w * 0.85, h * 0.5)
            p.drawPath(path)
            # Status dot at the end
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawEllipse(QPointF(w * 0.88, h * 0.5), 3, 3)

        p.end()


class MetricCard(QFrame):
    """High-tech glass metric card matching the 2.0.0 design mockup."""

    def __init__(self, icon_kind, title, value, badge_color="#2563EB",
                 chart_type="wave", chart_color="#22C58B", parent=None):
        super().__init__(parent)
        self.setObjectName("MetricCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(94)

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 9, 12, 8)
        v.setSpacing(5)

        # Top row: Round icon badge + (Title & Value)
        head = QHBoxLayout()
        head.setSpacing(8)

        # Icon badge
        self.badge = QLabel()
        self.badge.setFixedSize(36, 36)
        self.badge.setAlignment(Qt.AlignCenter)
        self._set_badge_style(icon_kind, badge_color)
        head.addWidget(self.badge)

        # Text column
        col = QVBoxLayout()
        col.setSpacing(1)
        self.title_lab = QLabel(title)
        self.title_lab.setObjectName("MetricTitle")
        self.title_lab.setMinimumWidth(0)
        self.title_lab.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        self.value_lab = QLabel(value)
        self.value_lab.setObjectName("MetricValue")
        # 数值文本（如 "133.17 Mbps"）不能反过来决定卡片最小宽度，
        # 否则四张卡片会把窄窗口整页撑宽
        self.value_lab.setMinimumWidth(0)
        self.value_lab.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        col.addWidget(self.title_lab)
        col.addWidget(self.value_lab)
        head.addLayout(col, 1)

        v.addLayout(head)

        # Bottom row: Sparkline / mini-chart
        self.chart = SparklineWidget(chart_type, chart_color, self)
        v.addWidget(self.chart)

    def _set_badge_style(self, icon_kind, color_hex):
        icons = {
            "pulse": "📈",
            "port": "🖧",
            "shield": "🛡",
            "globe": "🌐",
            "clock": "🕒",
        }
        glyph = icons.get(icon_kind, "●")
        self.badge.setText(glyph)
        self.badge.setStyleSheet(f"""
            QLabel {{
                background: qradialgradient(cx:0.5, cy:0.5, radius:0.7,
                    fx:0.35, fy:0.35,
                    stop:0 {color_hex}, stop:1 rgba(15, 23, 42, 0.9));
                border: 1px solid rgba(255, 255, 255, 0.25);
                border-radius: 20px;
                font-size: 16px;
                color: #FFFFFF;
            }}
        """)

    def set_value(self, val, color=None):
        self.value_lab.setText(val)
        if color:
            self.value_lab.setStyleSheet(
                f"color: {color}; font-size: 16pt; font-weight: 700;")
        else:
            self.value_lab.setStyleSheet("")
