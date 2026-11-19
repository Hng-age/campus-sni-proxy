"""Base class shared by all pages."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget


class Page(QWidget):
    """A workspace page.

    Pages receive `ctx` (the MainWindow) and may emit `request_action` for
    lifecycle operations after their own confirmation dialogs.
    """

    request_action = Signal(str)

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.ctx = ctx

    # optional hooks
    def update_snapshot(self, snap):           # noqa: D401 - hook
        pass

    def on_action_started(self, action):       # noqa: D401 - hook
        pass

    def on_action_finished(self, ok):          # noqa: D401 - hook
        pass

    def on_settings_changed(self, settings):   # noqa: D401 - hook
        pass

    def activate(self):
        pass
