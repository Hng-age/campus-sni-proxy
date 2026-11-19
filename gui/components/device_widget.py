"""Stylized high-tech laptop/monitor illustration widget for System Info card."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget


class DeviceWidget(QWidget):
    """Futuristic display illustration showing a glowing Windows desktop screen."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setMinimumSize(120, 100)
        self._is_light = False

    def set_palette(self, pal):
        self._is_light = pal.get("id") == "light"
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w * 0.52, h * 0.46

        # Scale based on available space
        scale = min(w / 160.0, h / 130.0)
        scale = max(0.6, min(1.3, scale))

        p.save()
        p.translate(cx, cy)
        p.scale(scale, scale)

        is_light = self._is_light

        # 1. Soft screen glow behind
        glow = QRadialGradient(0, -10, 70)
        if is_light:
            glow.setColorAt(0.0, QColor(37, 99, 235, 35))
            glow.setColorAt(0.7, QColor(147, 197, 253, 15))
            glow.setColorAt(1.0, QColor(255, 255, 255, 0))
        else:
            glow.setColorAt(0.0, QColor(37, 99, 235, 70))
            glow.setColorAt(0.7, QColor(6, 182, 212, 25))
            glow.setColorAt(1.0, QColor(10, 15, 29, 0))
        p.setBrush(QBrush(glow))
        p.setPen(Qt.NoPen)
        p.drawEllipse(-70, -70, 140, 120)

        # 2. Stand & base
        # Stand pillar
        if is_light:
            p.setBrush(QColor(226, 232, 240))
            p.setPen(QPen(QColor(148, 163, 184), 1))
        else:
            p.setBrush(QColor(30, 41, 59))
            p.setPen(QPen(QColor(71, 85, 105), 1))
        pillar = QPainterPath()
        pillar.moveTo(-8, 30)
        pillar.lineTo(8, 30)
        pillar.lineTo(12, 48)
        pillar.lineTo(-12, 48)
        pillar.closeSubpath()
        p.drawPath(pillar)

        # Stand base plate (ellipse in perspective)
        base_grad = QLinearGradient(0, 46, 0, 54)
        if is_light:
            base_grad.setColorAt(0.0, QColor(241, 245, 249))
            base_grad.setColorAt(1.0, QColor(203, 213, 225))
            p.setBrush(QBrush(base_grad))
            p.setPen(QPen(QColor(148, 163, 184), 1))
        else:
            base_grad.setColorAt(0.0, QColor(51, 65, 85))
            base_grad.setColorAt(1.0, QColor(15, 23, 42))
            p.setBrush(QBrush(base_grad))
            p.setPen(QPen(QColor(100, 116, 139), 1))
        p.drawEllipse(QRectF(-32, 46, 64, 10))

        # 3. Monitor bezel (metallic)
        frame_rect = QRectF(-56, -42, 112, 74)
        frame_grad = QLinearGradient(-56, -42, 56, 32)
        if is_light:
            frame_grad.setColorAt(0.0, QColor(248, 250, 252))
            frame_grad.setColorAt(1.0, QColor(226, 232, 240))
            p.setBrush(QBrush(frame_grad))
            p.setPen(QPen(QColor(148, 163, 184), 1.2))
        else:
            frame_grad.setColorAt(0.0, QColor(30, 41, 59))
            frame_grad.setColorAt(1.0, QColor(15, 23, 42))
            p.setBrush(QBrush(frame_grad))
            p.setPen(QPen(QColor(56, 189, 248, 80), 1.2))
        p.drawRoundedRect(frame_rect, 6, 6)

        # 4. Display screen area
        screen_rect = QRectF(-51, -37, 102, 64)
        p.setClipRect(screen_rect)

        # Screen background: light bloom gradient vs dark indigo
        scr_bg = QLinearGradient(-51, -37, 51, 27)
        if is_light:
            scr_bg.setColorAt(0.0, QColor(241, 245, 249))
            scr_bg.setColorAt(0.6, QColor(219, 234, 254))
            scr_bg.setColorAt(1.0, QColor(191, 219, 254))
        else:
            scr_bg.setColorAt(0.0, QColor(10, 18, 38))
            scr_bg.setColorAt(0.6, QColor(15, 30, 66))
            scr_bg.setColorAt(1.0, QColor(2, 6, 23))
        p.fillRect(screen_rect, QBrush(scr_bg))

        # Windows 11 signature blue bloom/ribbon wave
        wave1 = QPainterPath()
        wave1.moveTo(-51, 10)
        wave1.cubicTo(-20, -35, 10, 20, 51, -15)
        wave1.lineTo(51, 27)
        wave1.lineTo(-51, 27)
        wave1.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(37, 99, 235, 140 if is_light else 160))
        p.drawPath(wave1)

        wave2 = QPainterPath()
        wave2.moveTo(-35, 20)
        wave2.cubicTo(-5, -25, 25, 10, 51, -5)
        wave2.lineTo(51, 27)
        wave2.lineTo(-35, 27)
        wave2.closeSubpath()
        p.setBrush(QColor(59, 130, 246, 120) if is_light else QColor(6, 182, 212, 140))
        p.drawPath(wave2)

        # Screen reflection gloss
        gloss = QLinearGradient(-51, -37, 51, 27)
        gloss.setColorAt(0.0, QColor(255, 255, 255, 60 if is_light else 40))
        gloss.setColorAt(0.35, QColor(255, 255, 255, 10 if is_light else 5))
        gloss.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillRect(screen_rect, QBrush(gloss))

        p.restore()
        p.end()
