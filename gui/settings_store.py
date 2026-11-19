"""QSettings-backed preference store with change notification."""

from PySide6.QtCore import QObject, QSettings, Signal

from services.config_manager import DEFAULTS, ORG_NAME, APP_NAME


class SettingsStore(QObject):
    changed = Signal(dict)     # full snapshot after every change

    def __init__(self, parent=None):
        super().__init__(parent)
        self._qs = QSettings(ORG_NAME, APP_NAME)

    def get(self, key, default=None):
        if key in DEFAULTS:
            default = DEFAULTS[key]
        value = self._qs.value(key, defaultValue=default)
        # QSettings returns strings for older values; normalize types
        if isinstance(default, bool):
            if isinstance(value, str):
                return value.lower() in ("1", "true", "yes", "on")
            return bool(value)
        if isinstance(default, int) and not isinstance(value, int):
            try:
                return int(value)
            except (TypeError, ValueError):
                return default
        if isinstance(default, list) and isinstance(value, str):
            return [v for v in value.split(",") if v]
        return value

    def set(self, key, value):
        self._qs.setValue(key, value)
        self._qs.sync()
        self.changed.emit(self.snapshot())

    def snapshot(self):
        return {k: self.get(k) for k in DEFAULTS}
