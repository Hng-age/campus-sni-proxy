"""Futuristic 3D wireframe globe widget with glowing nodes and connection arcs."""

import math
from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import (
    QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget


class GlobeWidget(QWidget):
    """Luminous 3D network globe with longitude/latitude mesh and connection arcs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setMinimumSize(140, 140)
        self._angle = 0.0
        self._is_light = False

        # Subtle continuous rotation animation
        self._timer = QTimer(self)
        self._timer.setInterval(40)  # ~25 fps
        self._timer.timeout.connect(self._rotate)
        self._timer.start()

        # Fixed node points on a sphere (lat, lon in radians)
        self._nodes = [
            (0.3, 0.5), (-0.2, 1.2), (0.6, -0.8), (-0.5, -0.4),
            (0.1, 2.1), (0.4, 2.8), (-0.3, 3.4), (0.7, 4.0),
            (-0.1, -1.8), (0.5, -2.5), (-0.4, 1.8), (0.2, -0.2),
        ]
        self._arcs = [
            (0, 1), (1, 10), (0, 11), (2, 3), (2, 8),
            (4, 5), (5, 6), (6, 7), (8, 9), (10, 4)
        ]

    def set_palette(self, pal):
        self._is_light = pal.get("id") == "light"
        self.update()

    def _rotate(self):
        self._angle = (self._angle + 0.008) % (2 * math.pi)
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2.0, h / 2.0
        r = min(w, h) * 0.44
        if r <= 10:
            return

        is_light = self._is_light

        # 1. Outer glow aura
        aura = QRadialGradient(cx, cy, r * 1.35)
        if is_light:
            aura.setColorAt(0.0, QColor(37, 99, 235, 30))
            aura.setColorAt(0.7, QColor(147, 197, 253, 15))
            aura.setColorAt(1.0, QColor(255, 255, 255, 0))
        else:
            aura.setColorAt(0.0, QColor(6, 182, 212, 35))
            aura.setColorAt(0.7, QColor(37, 99, 235, 20))
            aura.setColorAt(1.0, QColor(10, 15, 29, 0))
        p.setBrush(QBrush(aura))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(cx, cy), r * 1.35, r * 1.35)

        # 2. Sphere body
        sphere = QRadialGradient(cx - r * 0.35, cy - r * 0.35, r * 1.3)
        if is_light:
            sphere.setColorAt(0.0, QColor(239, 246, 255))
            sphere.setColorAt(0.6, QColor(219, 234, 254))
            sphere.setColorAt(1.0, QColor(191, 219, 254))
            p.setBrush(QBrush(sphere))
            p.setPen(QPen(QColor(59, 130, 246, 140), 1.5))
        else:
            sphere.setColorAt(0.0, QColor(15, 30, 60))
            sphere.setColorAt(0.6, QColor(8, 16, 34))
            sphere.setColorAt(1.0, QColor(4, 8, 20))
            p.setBrush(QBrush(sphere))
            p.setPen(QPen(QColor(56, 189, 248, 120), 1.5))
        p.drawEllipse(QPointF(cx, cy), r, r)

        # Clip inside the sphere for grid and nodes
        clip = QPainterPath()
        clip.addEllipse(QPointF(cx, cy), r, r)
        p.save()
        p.setClipPath(clip)

        # 3. Latitudes (horizontal ellipses)
        if is_light:
            p.setPen(QPen(QColor(59, 130, 246, 50), 1, Qt.DashLine))
        else:
            p.setPen(QPen(QColor(56, 189, 248, 40), 1, Qt.DashLine))
        for lat in (-0.6, -0.3, 0.0, 0.3, 0.6):
            y_offset = math.sin(lat) * r
            rad_lat = math.cos(lat) * r
            p.drawEllipse(QPointF(cx, cy + y_offset), rad_lat, rad_lat * 0.28)

        # 4. Longitudes (rotated meridians)
        if is_light:
            p.setPen(QPen(QColor(37, 99, 235, 60), 1))
        else:
            p.setPen(QPen(QColor(59, 130, 246, 50), 1))
        for i in range(8):
            lon = i * (math.pi / 4.0) + self._angle
            w_meridian = math.sin(lon) * r
            if abs(w_meridian) > 1:
                p.drawEllipse(QPointF(cx, cy), abs(w_meridian), r)

        # 5. Project nodes onto 2D
        screen_nodes = []
        for lat, lon in self._nodes:
            curr_lon = lon + self._angle
            # 3D coords
            x3 = math.cos(lat) * math.sin(curr_lon)
            y3 = -math.sin(lat)
            z3 = math.cos(lat) * math.cos(curr_lon)

            # Only visible on front hemisphere (z3 > 0)
            alpha = max(0.0, min(1.0, (z3 + 0.2) / 1.2))
            sx = cx + x3 * r
            sy = cy + y3 * r
            screen_nodes.append((sx, sy, z3, alpha))

        # 6. Draw connection arcs between front nodes
        for i1, i2 in self._arcs:
            n1 = screen_nodes[i1]
            n2 = screen_nodes[i2]
            if n1[2] > -0.1 and n2[2] > -0.1:
                arc_alpha = int(min(n1[3], n2[3]) * 180)
                if arc_alpha > 15:
                    if is_light:
                        pen = QPen(QColor(29, 78, 216, arc_alpha), 1.2)
                    else:
                        pen = QPen(QColor(56, 189, 248, arc_alpha), 1.2)
                    p.setPen(pen)
                    # Quadratic curve with elevated control point
                    mid_x = (n1[0] + n2[0]) / 2.0
                    mid_y = (n1[1] + n2[1]) / 2.0
                    # pull slightly outward from center
                    dx = mid_x - cx
                    dy = mid_y - cy
                    ctrl_x = mid_x + dx * 0.25
                    ctrl_y = mid_y + dy * 0.25
                    path = QPainterPath()
                    path.moveTo(n1[0], n1[1])
                    path.quadTo(ctrl_x, ctrl_y, n2[0], n2[1])
                    p.strokePath(path, pen)

        # 7. Draw nodes
        p.setPen(Qt.NoPen)
        for sx, sy, z3, alpha in screen_nodes:
            if z3 > -0.1:
                a_int = int(alpha * 255)
                if is_light:
                    p.setBrush(QColor(37, 99, 235, int(a_int * 0.35)))
                    p.drawEllipse(QPointF(sx, sy), 5.0, 5.0)
                    p.setBrush(QColor(29, 78, 216, a_int))
                    p.drawEllipse(QPointF(sx, sy), 2.2, 2.2)
                else:
                    p.setBrush(QColor(56, 189, 248, int(a_int * 0.35)))
                    p.drawEllipse(QPointF(sx, sy), 5.0, 5.0)
                    p.setBrush(QColor(240, 249, 255, a_int))
                    p.drawEllipse(QPointF(sx, sy), 2.2, 2.2)

        p.restore()

        # 8. Glass reflection highlight at top left
        p.setPen(Qt.NoPen)
        hl = QLinearGradient(cx - r, cy - r, cx + r, cy + r)
        hl.setColorAt(0.0, QColor(255, 255, 255, 70 if is_light else 50))
        hl.setColorAt(0.35, QColor(255, 255, 255, 15 if is_light else 10))
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(hl))
        p.drawEllipse(QPointF(cx - r * 0.2, cy - r * 0.25), r * 0.75, r * 0.5)

        p.end()
