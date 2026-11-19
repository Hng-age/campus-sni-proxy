"""Log center page: live tail of logs/proxy.log with filters and export."""

import os
import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from gui.components.glass_panel import GlassPanel
from gui.components.log_viewer import LEVEL_FILTERS, LogViewer
from sni_proxy import config
from .base import Page

LOG_FILE = config.LOG_FILE
TAIL_LINES_ON_OPEN = 300


class LogsPage(Page):
    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 18)
        outer.setSpacing(12)

        head = QHBoxLayout()
        meta = QLabel(f"{LOG_FILE}")
        meta.setObjectName("TinyLabel")
        head.addWidget(meta)
        head.addStretch(1)
        self.btn_reload = QPushButton("重新加载")
        self.btn_reload.setToolTip("从文件末尾重新加载最近日志")
        self.btn_reload.clicked.connect(self._reload)
        self.btn_cleanup = QPushButton("清理过期日志")
        self.btn_cleanup.setToolTip(
            "按设置中的保留天数删除过期的轮转日志（proxy.log.1…）")
        self.btn_cleanup.clicked.connect(self._cleanup)
        head.addWidget(self.btn_reload)
        head.addWidget(self.btn_cleanup)
        outer.addLayout(head)

        self.viewer = LogViewer()
        if isinstance(self.viewer.level_combo, QWidget):
            self.viewer.level_combo.setToolTip("按日志级别筛选")
        outer.addWidget(self.viewer, 1)

        self._offset = 0
        self._stat = (0, 0)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._poll)
        self.timer.start()
        self._reload()

    # ------------------------------------------------------------- tail
    def activate(self):
        self._reload()

    def on_settings_changed(self, settings):
        try:
            idx = int(settings.get("log_level_filter", 0))
        except (TypeError, ValueError):
            idx = 0
        if 0 <= idx < len(LEVEL_FILTERS):
            self.viewer.level_combo.setCurrentIndex(idx)

    def _reload(self):
        self._offset = 0
        self.viewer.clear_view()
        self._stat = (0, 0)
        self._poll(force=True)

    def _poll(self, force=False):
        try:
            exists = os.path.exists(LOG_FILE)
        except OSError:
            return
        if not exists:
            return
        try:
            st = os.stat(LOG_FILE)
        except OSError:
            return
        key = (st.st_size, st.st_mtime_ns)
        if not force and key == self._stat:
            return
        self._stat = key
        size = st.st_size
        try:
            if size < self._offset:
                # rotated / truncated: reload the fresh file from the start
                self.viewer.clear_view()
                self._offset = 0
            with open(LOG_FILE, "rb") as f:
                if self._offset == 0:
                    # first load: only the tail
                    if size > 512 * 1024:
                        f.seek(size - 512 * 1024)
                        f.readline()
                    self._offset = f.tell()
                f.seek(self._offset)
                data = f.read(4 * 1024 * 1024)
                self._offset = f.tell()
        except OSError:
            return
        if data:
            if not data.endswith(b"\n"):
                # partial last line: keep it for the next poll
                idx = data.rfind(b"\n")
                keep = data if idx == -1 else data[:idx + 1]
                self._offset -= len(data) - len(keep)
                data = keep
            if data:
                text = data.decode("utf-8", errors="replace")
                lines = [ln for ln in text.splitlines() if ln]
                self.viewer.append_lines(lines)

    # ---------------------------------------------------------- cleanup
    def _cleanup(self):
        days = int(self.ctx.settings.get("log_retention_days", 14))
        removed = 0
        cutoff = time.time() - days * 86400
        log_dir = os.path.dirname(LOG_FILE)
        try:
            for name in os.listdir(log_dir):
                if not name.startswith("proxy.log."):
                    continue
                path = os.path.join(log_dir, name)
                try:
                    if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                        os.remove(path)
                        removed += 1
                except OSError:
                    pass
        except OSError:
            pass
        if removed:
            self.viewer.status_lab.setText(
                f"已清理 {removed} 个超过 {days} 天的轮转日志文件")
            self._reload()
        else:
            self.viewer.status_lab.setText(
                f"没有超过 {days} 天的轮转日志文件")
