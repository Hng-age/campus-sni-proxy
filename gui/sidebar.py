"""Clean minimalist navigation sidebar."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QVBoxLayout,
)

NAV_ITEMS = [
    ("🏠", "仪表盘", "Dashboard"),
    ("⚙", "运行管理", "Service Manager"),
    ("📋", "规则管理", "Rules & Probe"),
    ("🌐", "网络诊断", "Network Diagnostics"),
    ("⚡", "网络测速", "Speed Test"),
    ("📄", "日志中心", "Log Center"),
    ("🛰", "TUN / VPN", "Virtual NIC Proxy"),
    ("🛡", "证书管理", "Certificate Manager"),
    ("🔧", "设置中心", "Settings"),
]


class NavButton(QPushButton):
    """Single-line clean navigation item."""

    def __init__(self, glyph, title_cn, title_en="", parent=None):
        super().__init__(f"  {glyph}   {title_cn}", parent)
        self.setObjectName("NavButton")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(35)
        self.glyph = glyph
        self.title_cn = title_cn
        self.title_en = title_en

    def set_palette(self, _pal):
        # Styled cleanly via QSS #NavButton
        self.update()


class Sidebar(QFrame):
    """Minimalist translucent/flat sidebar with brand header, nav items and footer."""

    nav_changed = Signal(int)
    about_clicked = Signal()
    help_clicked = Signal()

    def __init__(self, version, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedWidth(168)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        v = QVBoxLayout(self)
        v.setContentsMargins(10, 14, 10, 10)
        v.setSpacing(4)

        # Clean header
        head = QVBoxLayout()
        head.setContentsMargins(8, 2, 8, 8)
        head.setSpacing(2)
        self.name_lab = QLabel("toci")
        self.name_lab.setObjectName("BrandName")
        self.ver_lab = QLabel(f"v{version}")
        self.ver_lab.setObjectName("BrandVersion")
        head.addWidget(self.name_lab)
        head.addWidget(self.ver_lab)
        v.addLayout(head)

        hline = QFrame()
        hline.setObjectName("HLine")
        hline.setFixedHeight(1)
        v.addWidget(hline)
        v.addSpacing(4)

        # Nav buttons
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

        # Compact footer
        bottom = QHBoxLayout()
        bottom.setContentsMargins(4, 4, 4, 0)
        self.btn_about = QPushButton("关于")
        self.btn_about.setObjectName("SecondaryBtnSmall")
        self.btn_about.setCursor(Qt.PointingHandCursor)
        self.btn_about.clicked.connect(self.about_clicked.emit)

        self.btn_help = QPushButton("帮助")
        self.btn_help.setObjectName("SecondaryBtnSmall")
        self.btn_help.setCursor(Qt.PointingHandCursor)
        self.btn_help.clicked.connect(self.help_clicked.emit)

        bottom.addWidget(self.btn_about, 1)
        bottom.addSpacing(6)
        bottom.addWidget(self.btn_help, 1)
        v.addLayout(bottom)

    def set_palette(self, pal):
        for b in self.buttons:
            b.set_palette(pal)
        self.update()

    def select(self, index):
        if 0 <= index < len(self.buttons):
            self.buttons[index].setChecked(True)
            self.update()
