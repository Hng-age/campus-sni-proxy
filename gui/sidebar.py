"""Modern glassmorphism navigation sidebar matching the 2.0.0 mockup."""

import time

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QVBoxLayout, QWidget,
)

NAV_ITEMS = [
    ("🏠", "仪表盘", "Dashboard"),
    ("⚙", "运行管理", "Service Manager"),
    ("🌐", "网络诊断", "Network Diagnostics"),
    ("⚡", "网络测速", "Speed Test"),
    ("📄", "日志中心", "Log Center"),
    ("🛡", "证书管理", "Certificate Manager"),
    ("⚙", "设置中心", "Settings"),
]


class BrandLogoWidget(QWidget):
    """Glowing Shield + Globe logo badge."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setFixedSize(56, 56)
        self._is_light = False

    def set_palette(self, pal):
        self._is_light = pal.get("id") == "light"
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())
        cx, cy = w / 2.0, h / 2.0

        if self._is_light:
            # Light mode blue glow ring
            glow = QRadialGradient(cx, cy, 32)
            glow.setColorAt(0.0, QColor(37, 99, 235, 45))
            glow.setColorAt(0.6, QColor(147, 197, 253, 25))
            glow.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.setBrush(QBrush(glow))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(cx, cy), 32, 32)

            # Shield outline
            shield = QPainterPath()
            shield.moveTo(cx, cy - 24)
            shield.lineTo(cx + 20, cy - 14)
            shield.lineTo(cx + 17, cy + 8)
            shield.cubicTo(cx + 14, cy + 18, cx, cy + 25, cx, cy + 25)
            shield.cubicTo(cx, cy + 25, cx - 14, cy + 18, cx - 17, cy + 8)
            shield.lineTo(cx - 20, cy - 14)
            shield.closeSubpath()

            # Shield fill
            sh_grad = QLinearGradient(cx - 20, cy - 24, cx + 20, cy + 25)
            sh_grad.setColorAt(0.0, QColor(239, 246, 255))
            sh_grad.setColorAt(1.0, QColor(219, 234, 254))
            p.setBrush(QBrush(sh_grad))
            p.setPen(QPen(QColor(37, 99, 235, 200), 1.8))
            p.drawPath(shield)

            # Globe mesh inside shield
            r_inner = 13.0
            p.setPen(QPen(QColor(37, 99, 235, 170), 1.2))
            p.drawEllipse(QPointF(cx, cy - 1), r_inner, r_inner)
            p.drawEllipse(QPointF(cx, cy - 1), r_inner * 0.45, r_inner)
            p.drawLine(QPointF(cx - r_inner, cy - 1), QPointF(cx + r_inner, cy - 1))
        else:
            # Outer cyan glow ring
            glow = QRadialGradient(cx, cy, 32)
            glow.setColorAt(0.0, QColor(6, 182, 212, 100))
            glow.setColorAt(0.6, QColor(37, 99, 235, 40))
            glow.setColorAt(1.0, QColor(10, 15, 29, 0))
            p.setBrush(QBrush(glow))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(cx, cy), 32, 32)

            # Shield outline
            shield = QPainterPath()
            shield.moveTo(cx, cy - 24)
            shield.lineTo(cx + 20, cy - 14)
            shield.lineTo(cx + 17, cy + 8)
            shield.cubicTo(cx + 14, cy + 18, cx, cy + 25, cx, cy + 25)
            shield.cubicTo(cx, cy + 25, cx - 14, cy + 18, cx - 17, cy + 8)
            shield.lineTo(cx - 20, cy - 14)
            shield.closeSubpath()

            # Shield fill
            sh_grad = QLinearGradient(cx - 20, cy - 24, cx + 20, cy + 25)
            sh_grad.setColorAt(0.0, QColor(15, 30, 66))
            sh_grad.setColorAt(1.0, QColor(6, 18, 45))
            p.setBrush(QBrush(sh_grad))
            p.setPen(QPen(QColor(56, 189, 248, 220), 1.8))
            p.drawPath(shield)

            # Globe mesh inside shield
            r_inner = 13.0
            p.setPen(QPen(QColor(56, 189, 248, 160), 1.2))
            p.drawEllipse(QPointF(cx, cy - 1), r_inner, r_inner)
            # Meridian & equator lines
            p.drawEllipse(QPointF(cx, cy - 1), r_inner * 0.45, r_inner)
            p.drawLine(QPointF(cx - r_inner, cy - 1), QPointF(cx + r_inner, cy - 1))

        p.end()


class NavButton(QPushButton):
    """Sidebar navigation item with icon, Chinese title and English subtitle."""

    def __init__(self, glyph, title_cn, title_en, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(42)
        self.glyph = glyph
        self.title_cn = title_cn
        self.title_en = title_en
        self._is_light = False

    def set_palette(self, pal):
        self._is_light = pal.get("id") == "light"
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())
        rect = QRectF(0, 0, w, h)
        is_active = self.isChecked()
        is_hover = self.underMouse()

        # 1. Background
        if is_active:
            grad = QLinearGradient(0, 0, w, 0)
            grad.setColorAt(0.0, QColor(30, 64, 175))
            grad.setColorAt(1.0, QColor(59, 130, 246))
            p.setBrush(QBrush(grad))
            p.setPen(QPen(QColor(147, 197, 253, 180) if self._is_light else QColor(56, 189, 248, 160), 1.2))
            p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 12, 12)
        elif is_hover:
            if self._is_light:
                p.setBrush(QColor(37, 99, 235, 25))
                p.setPen(QPen(QColor(37, 99, 235, 70), 1.0))
            else:
                p.setBrush(QColor(30, 58, 138, 80))
                p.setPen(QPen(QColor(59, 130, 246, 70), 1.0))
            p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 12, 12)
        else:
            p.setBrush(Qt.NoBrush)
            p.setPen(Qt.NoPen)

        # 2. Icon glyph
        p.setFont(QFont("Segoe UI Emoji", 14))
        if is_active:
            glyph_col = QColor("#FFFFFF")
        elif self._is_light:
            glyph_col = QColor("#2563EB")
        else:
            glyph_col = QColor("#94A3B8")
        p.setPen(glyph_col)
        p.drawText(QRectF(14, 0, 28, h), Qt.AlignCenter, self.glyph)

        # 3. Text lines
        p.setFont(QFont("Microsoft YaHei UI", 9.5, QFont.Bold if is_active else QFont.Normal))
        if is_active:
            title_col = QColor("#FFFFFF")
        elif self._is_light:
            title_col = QColor("#0F172A")
        else:
            title_col = QColor("#E2E8F0")
        p.setPen(title_col)
        p.drawText(QRectF(44, 4, w - 50, 18), Qt.AlignLeft | Qt.AlignVCenter, self.title_cn)

        p.setFont(QFont("Segoe UI", 8))
        if is_active:
            sub_col = QColor("#DBEAFE")
        elif self._is_light:
            sub_col = QColor("#64748B")
        else:
            sub_col = QColor("#64748B")
        p.setPen(sub_col)
        p.drawText(QRectF(44, 22, w - 50, 15), Qt.AlignLeft | Qt.AlignVCenter, self.title_en)

        p.end()


class Sidebar(QFrame):
    """Modern translucent sidebar with Brand logo, 6 nav buttons, and bottom cards."""

    nav_changed = Signal(int)
    about_clicked = Signal()
    help_clicked = Signal()

    def __init__(self, version, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(200)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 8)
        v.setSpacing(3)

        # 1. Top Brand Logo & Name
        brand = QVBoxLayout()
        brand.setAlignment(Qt.AlignCenter)
        brand.setSpacing(2)

        self.logo = BrandLogoWidget()
        brand.addWidget(self.logo, 0, Qt.AlignCenter)

        self.name_lab = QLabel("SNI Proxy\nDesktop")
        self.name_lab.setAlignment(Qt.AlignCenter)
        self.name_lab.setStyleSheet(
            "color: #FFFFFF; font-size: 13pt; font-weight: 700; line-height: 1.1; background: transparent;")
        self.ver_lab = QLabel(f"v{version}")
        self.ver_lab.setAlignment(Qt.AlignCenter)
        self.ver_lab.setStyleSheet(
            "color: #38BDF8; font-size: 8.5pt; font-weight: 600; margin-bottom: 2px; background: transparent;")

        brand.addWidget(self.name_lab)
        brand.addWidget(self.ver_lab)
        v.addLayout(brand)
        v.addSpacing(6)

        # 2. Nav buttons
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons = []
        for i, (glyph, cn, en) in enumerate(NAV_ITEMS):
            btn = NavButton(glyph, cn, en)
            btn.clicked.connect(lambda _=False, idx=i: self.nav_changed.emit(idx))
            self.group.addButton(btn, i)
            self.buttons.append(btn)
            v.addWidget(btn)
        self.buttons[0].setChecked(True)

        v.addStretch(1)

        # 3. Bottom Tool Card (🎓 校园网络工具 / 安全 · 稳定 · 便捷)
        self.tool_card = QFrame()
        self.tool_card.setStyleSheet("""
            QFrame {
                background: rgba(15, 23, 42, 0.7);
                border: 1px solid rgba(56, 189, 248, 0.2);
                border-radius: 12px;
            }
        """)
        tc_lay = QHBoxLayout(self.tool_card)
        tc_lay.setContentsMargins(12, 10, 12, 10)
        tc_lay.setSpacing(10)

        self.cap_icon = QLabel("🎓")
        self.cap_icon.setStyleSheet(
            "font-size: 20px; color: #38BDF8; background: transparent; border: none;")
        tc_lay.addWidget(self.cap_icon)

        tc_col = QVBoxLayout()
        tc_col.setSpacing(1)
        self.tc_title = QLabel("校园网络工具")
        self.tc_title.setStyleSheet(
            "color: #FFFFFF; font-size: 10pt; font-weight: 600; border: none; background: transparent;")
        self.tc_sub = QLabel("安全 · 稳定 · 便捷")
        self.tc_sub.setStyleSheet(
            "color: #64748B; font-size: 8pt; border: none; background: transparent;")
        tc_col.addWidget(self.tc_title)
        tc_col.addWidget(self.tc_sub)
        tc_lay.addLayout(tc_col)
        v.addWidget(self.tool_card)

        # 4. About & Help links
        bottom = QHBoxLayout()
        bottom.setContentsMargins(4, 4, 4, 0)
        self.btn_about = QPushButton("⚙ 关于")
        self.btn_about.setCursor(Qt.PointingHandCursor)
        self.btn_about.setStyleSheet("""
            QPushButton {
                color: #94A3B8; background: transparent; border: none; font-size: 9pt;
            }
            QPushButton:hover { color: #38BDF8; }
        """)
        self.btn_about.clicked.connect(self.about_clicked.emit)

        self.btn_help = QPushButton("✪ 帮助")
        self.btn_help.setCursor(Qt.PointingHandCursor)
        self.btn_help.setStyleSheet("""
            QPushButton {
                color: #94A3B8; background: transparent; border: none; font-size: 9pt;
            }
            QPushButton:hover { color: #38BDF8; }
        """)
        self.btn_help.clicked.connect(self.help_clicked.emit)

        bottom.addWidget(self.btn_about)
        bottom.addStretch(1)
        bottom.addWidget(self.btn_help)
        v.addLayout(bottom)

    def set_palette(self, pal):
        is_light = pal.get("id") == "light"
        self.logo.set_palette(pal)
        for b in self.buttons:
            b.set_palette(pal)
        if is_light:
            self.name_lab.setStyleSheet(
                "color: #0F172A; font-size: 13pt; font-weight: 700; line-height: 1.1; background: transparent;")
            self.ver_lab.setStyleSheet(
                "color: #2563EB; font-size: 8.5pt; font-weight: 600; margin-bottom: 2px; background: transparent;")
            self.tool_card.setStyleSheet("""
                QFrame {
                    background: rgba(255, 255, 255, 0.85);
                    border: 1px solid rgba(203, 213, 225, 0.85);
                    border-radius: 12px;
                }
            """)
            self.cap_icon.setStyleSheet(
                "font-size: 20px; color: #2563EB; background: transparent; border: none;")
            self.tc_title.setStyleSheet(
                "color: #0F172A; font-size: 10pt; font-weight: 600; border: none; background: transparent;")
            self.tc_sub.setStyleSheet(
                "color: #64748B; font-size: 8pt; border: none; background: transparent;")
            self.btn_about.setStyleSheet("""
                QPushButton {
                    color: #475569; background: transparent; border: none; font-size: 9pt;
                }
                QPushButton:hover { color: #2563EB; }
            """)
            self.btn_help.setStyleSheet("""
                QPushButton {
                    color: #475569; background: transparent; border: none; font-size: 9pt;
                }
                QPushButton:hover { color: #2563EB; }
            """)
        else:
            self.name_lab.setStyleSheet(
                "color: #FFFFFF; font-size: 13pt; font-weight: 700; line-height: 1.1; background: transparent;")
            self.ver_lab.setStyleSheet(
                "color: #38BDF8; font-size: 8.5pt; font-weight: 600; margin-bottom: 2px; background: transparent;")
            self.tool_card.setStyleSheet("""
                QFrame {
                    background: rgba(15, 23, 42, 0.7);
                    border: 1px solid rgba(56, 189, 248, 0.2);
                    border-radius: 12px;
                }
            """)
            self.cap_icon.setStyleSheet(
                "font-size: 20px; color: #38BDF8; background: transparent; border: none;")
            self.tc_title.setStyleSheet(
                "color: #FFFFFF; font-size: 10pt; font-weight: 600; border: none; background: transparent;")
            self.tc_sub.setStyleSheet(
                "color: #64748B; font-size: 8pt; border: none; background: transparent;")
            self.btn_about.setStyleSheet("""
                QPushButton {
                    color: #94A3B8; background: transparent; border: none; font-size: 9pt;
                }
                QPushButton:hover { color: #38BDF8; }
            """)
            self.btn_help.setStyleSheet("""
                QPushButton {
                    color: #94A3B8; background: transparent; border: none; font-size: 9pt;
                }
                QPushButton:hover { color: #38BDF8; }
            """)
        self.update()

        self.updated_lab = QLabel("")

    def select(self, index):
        if 0 <= index < len(self.buttons):
            self.buttons[index].setChecked(True)
            self.update()

    def mark_refresh(self):
        # Refresh hook
        pass
