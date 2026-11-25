"""Clean minimalist metric summary card."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout,
)


class MetricCard(QFrame):
    """Compact flat metric card with subtle tinted icon pill and value."""

    def __init__(self, icon_kind, title, value, badge_color="#2563EB",
                 chart_type="wave", chart_color="#22C58B", parent=None):
        super().__init__(parent)
        self.setObjectName("MetricCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(74)

        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(0)

        head = QHBoxLayout()
        head.setSpacing(10)

        self.badge = QLabel()
        self.badge.setFixedSize(34, 34)
        self.badge.setAlignment(Qt.AlignCenter)
        self._set_badge_style(icon_kind, badge_color)
        head.addWidget(self.badge)

        col = QVBoxLayout()
        col.setSpacing(2)
        self.title_lab = QLabel(title)
        self.title_lab.setObjectName("MetricTitle")
        self.title_lab.setMinimumWidth(0)
        self.title_lab.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        self.value_lab = QLabel(value)
        self.value_lab.setObjectName("MetricValue")
        self.value_lab.setMinimumWidth(0)
        self.value_lab.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        col.addWidget(self.title_lab)
        col.addWidget(self.value_lab)
        head.addLayout(col, 1)

        v.addLayout(head)

    def _set_badge_style(self, icon_kind, color_hex):
        icons = {
            "pulse": "●",
            "port": "⇄",
            "shield": "✓",
            "globe": "⊕",
            "clock": "◔",
        }
        glyph = icons.get(icon_kind, "●")
        self.badge.setText(glyph)
        self.badge.setStyleSheet(f"""
            QLabel {{
                background: rgba(37, 99, 235, 0.10);
                border: 1px solid rgba(148, 163, 184, 0.25);
                border-radius: 10px;
                font-size: 13px;
                font-weight: 700;
                color: {color_hex};
            }}
        """)

    def set_value(self, val, color=None):
        self.value_lab.setText(val)
        if color:
            self.value_lab.setStyleSheet(
                f"color: {color}; font-size: 13pt; font-weight: 700; background: transparent;")
        else:
            self.value_lab.setStyleSheet("")
