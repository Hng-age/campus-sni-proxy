"""Worker thread bridge: run service-layer functions off the GUI thread."""

from PySide6.QtCore import QThread, Signal


class FuncWorker(QThread):
    """Run fn(on_progress) in a QThread; results land on the GUI thread.

    fn receives a callable `on_progress(text)` which is re-emitted as the
    `progress` signal (thread-safe). The return value (or raised error) is
    delivered via `done(result, error)`.
    """

    progress = Signal(object)
    done = Signal(object, object)
    failed = Signal(object)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            result = self._fn(self.progress.emit)
        except Exception as e:      # noqa: BLE001 - report, never crash
            self.failed.emit(e)
            self.done.emit(None, str(e))
            return
        self.done.emit(result, None)
