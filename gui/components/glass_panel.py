"""Reusable glass widgets: panels, status cards, key/value rows."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout, QSizePolicy, QVBoxLayout,
    QWidget,
)


class GlassPanel(QFrame):
    """A rounded translucent card with an optional section title."""

    def __init__(self, title=None, parent=None):
        super().__init__(parent)
        self.setObjectName("GlassPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(10)
        if title:
            lab = QLabel(title)
            lab.setObjectName("PanelTitle")
            outer.addWidget(lab)
        self.body = QVBoxLayout()
        self.body.setSpacing(6)
        outer.addLayout(self.body)

    def add(self, item, stretch=0, align=None):
        if isinstance(item, QLayout):
            self.body.addLayout(item, stretch)
            return item
        if align is None:
            self.body.addWidget(item, stretch)
        else:
            self.body.addWidget(item, stretch, align)
        return item

    def add_layout(self, layout, stretch=0):
        self.body.addLayout(layout, stretch)
        return layout

    def add_stretch(self, stretch=0):
        self.body.addStretch(stretch)


class StatusCard(QFrame):
    """Small metric card: glyph, title, big value, sub line, state color."""

    def __init__(self, glyph, title, value="--", sub="", parent=None):
        super().__init__(parent)
        self.setObjectName("StatusCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 13, 16, 13)
        v.setSpacing(4)

        head = QHBoxLayout()
        glyph_lab = QLabel(glyph)
        glyph_lab.setObjectName("CardGlyph")
        title_lab = QLabel(title)
        title_lab.setObjectName("CardTitle")
        head.addWidget(glyph_lab)
        head.addSpacing(4)
        head.addWidget(title_lab)
        head.addStretch(1)
        v.addLayout(head)

        self.value_lab = QLabel(value)
        self.value_lab.setObjectName("CardValue")
        self.value_lab.setWordWrap(True)
        v.addWidget(self.value_lab)

        self.sub_lab = QLabel(sub)
        self.sub_lab.setObjectName("CardSub")
        self.sub_lab.setWordWrap(True)
        self.sub_lab.setVisible(bool(sub))
        v.addWidget(self.sub_lab)

    def set_value(self, value):
        self.value_lab.setText(value)

    def set_sub(self, sub):
        self.sub_lab.setText(sub)
        self.sub_lab.setVisible(bool(sub))

    def set_state(self, state):
        """state: ok / warn / error / idle (colors the value)."""
        self.value_lab.setProperty("state", state if state else "")
        self.value_lab.style().unpolish(self.value_lab)
        self.value_lab.style().polish(self.value_lab)


class KVGrid(QWidget):
    """Two-column key/value grid used by info panels."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(18)
        self.grid.setVerticalSpacing(8)
        self.grid.setColumnStretch(0, 0)
        self.grid.setColumnStretch(1, 1)
        self._rows = 0
        self._value_labels = {}

    def add_row(self, key, value="--", name=None):
        k = QLabel(key)
        k.setObjectName("KVKey")
        v = QLabel(value)
        v.setObjectName("KVValue")
        v.setWordWrap(True)
        self.grid.addWidget(k, self._rows, 0, Qt.AlignTop)
        self.grid.addWidget(v, self._rows, 1)
        self._rows += 1
        if name:
            self._value_labels[name] = v
        return v

    def set_value(self, name, value):
        v = self._value_labels.get(name)
        if v is not None:
            v.setText(value)
