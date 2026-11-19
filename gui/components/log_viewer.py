"""Log display widget: level filter, search, pause, auto-scroll, export."""

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

_LEVEL_RE = re.compile(r"\[(ERROR|WARNING|INFO|DEBUG)\]")
MAX_LINES = 10000

LEVEL_NAMES = ["全部", "INFO 及以上", "WARNING 及以上", "仅 ERROR", "含 DEBUG"]
LEVEL_FILTERS = [
    {"INFO", "WARNING", "ERROR", "DEBUG"},
    {"INFO", "WARNING", "ERROR"},
    {"WARNING", "ERROR"},
    {"ERROR"},
    {"INFO", "WARNING", "ERROR", "DEBUG"},
]


class LogViewer(QWidget):
    """Filtered, searchable, pausable log console."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)

        self._buffer = []       # (level, line)
        self._pending = []      # lines held while paused
        self._search = ""
        self._is_light = False

        bar = QHBoxLayout()
        bar.setSpacing(4)

        self.level_combo = QComboBox()
        self.level_combo.addItems(LEVEL_NAMES)
        self.level_combo.setToolTip("按日志级别筛选")
        self.level_combo.currentIndexChanged.connect(self._rerender)
        bar.addWidget(self.level_combo)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("搜索关键词…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._search_changed)
        self.search_box.setMinimumWidth(60)
        bar.addWidget(self.search_box, 1)

        self.pause_btn = QPushButton("暂停刷新")
        self.pause_btn.setCheckable(True)
        self.pause_btn.setToolTip("暂停显示新日志（后台继续缓冲，恢复后补齐）")
        self.pause_btn.toggled.connect(self._pause_toggled)
        bar.addWidget(self.pause_btn)

        self.autoscroll_cb = QCheckBox("自动滚动")
        self.autoscroll_cb.setChecked(True)
        self.autoscroll_cb.setToolTip("新日志到达时自动滚动到底部")
        bar.addWidget(self.autoscroll_cb)

        self.export_btn = QPushButton("导出")
        self.export_btn.setToolTip("导出当前筛选结果")
        self.export_btn.clicked.connect(self.export_view)
        bar.addWidget(self.export_btn)

        self.clear_btn = QPushButton("清空视图")
        self.clear_btn.setToolTip("只清空显示，不删除日志文件")
        self.clear_btn.clicked.connect(self.clear_view)
        bar.addWidget(self.clear_btn)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(MAX_LINES)
        self.view.setFont(QFont("Consolas"))
        self.view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.view.setStyleSheet("padding: 10px;")

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        v.addLayout(bar)
        v.addWidget(self.view, 1)

        self.status_lab = QLabel("")
        self.status_lab.setObjectName("TinyLabel")
        v.addWidget(self.status_lab)

    def set_palette(self, pal):
        new_is_light = pal.get("id") == "light"
        if self._is_light != new_is_light:
            self._is_light = new_is_light
            self._rerender()

    # ------------------------------------------------------------- input
    def append_lines(self, lines):
        if self.pause_btn.isChecked():
            self._pending.extend(lines)
            self._pending = self._pending[-MAX_LINES:]
            self._update_status()
            return
        self._append_now(lines)

    def _append_now(self, lines):
        fmt = {"INFO": self._fmt_info, "WARNING": self._fmt_warn,
               "ERROR": self._fmt_err, "DEBUG": self._fmt_debug}
        cursor = self.view.textCursor()
        at_end = (self.view.verticalScrollBar().value()
                  >= self.view.verticalScrollBar().maximum() - 4)
        for raw in lines:
            if not raw:
                continue
            level = None
            m = _LEVEL_RE.search(raw)
            if m:
                level = m.group(1)
            self._buffer.append((level, raw))
            if not self._passes(level, raw):
                continue
            color = fmt.get(level, self._fmt_info)
            self.view.appendHtml(color(raw))
        if len(self._buffer) > MAX_LINES:
            del self._buffer[:len(self._buffer) - MAX_LINES]
        if self.autoscroll_cb.isChecked() or at_end:
            self.view.moveCursor(QTextCursor.End)
        self._update_status()

    def _passes(self, level, line):
        allowed = LEVEL_FILTERS[self.level_combo.currentIndex()]
        if level not in allowed:
            return False
        if self._search and self._search.lower() not in line.lower():
            return False
        return True

    def _update_status(self):
        shown = self.view.blockCount()
        pending = len(self._pending)
        paused = "，暂停中待显示 %d 行" % pending if pending else ""
        self.status_lab.setText(
            f"显示 {shown} 行 / 缓冲 {len(self._buffer)} 行{paused}")

    # ------------------------------------------------------------- slots
    def _search_changed(self, text):
        self._search = text.strip()
        self._rerender()

    def _pause_toggled(self, paused):
        self.pause_btn.setText("暂停刷新" if not paused else "恢复刷新")
        if not paused and self._pending:
            held, self._pending = self._pending, []
            self._append_now(held)
        self._update_status()

    def _rerender(self):
        self.view.clear()
        self._buffer = self._buffer[-MAX_LINES:]
        fmt = {"INFO": self._fmt_info, "WARNING": self._fmt_warn,
               "ERROR": self._fmt_err, "DEBUG": self._fmt_debug}
        for level, line in self._buffer:
            if self._passes(level, line):
                color = fmt.get(level, self._fmt_info)
                self.view.appendHtml(color(line))
        if self.autoscroll_cb.isChecked():
            self.view.moveCursor(QTextCursor.End)
        self._update_status()

    # ------------------------------------------------------------- export
    def export_view(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "导出日志", "sni-proxy-log.txt", "文本文件 (*.txt);;所有文件 (*)")
        if not path:
            return
        text = "\n".join(line for level, line in self._buffer
                         if self._passes(level, line))
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        self.status_lab.setText(f"已导出 {text.count(chr(10)) + 1} 行到 {path}")

    def clear_view(self):
        self.view.clear()
        self._pending.clear()
        self._update_status()

    # -------------------------------------------------- level formatting
    @staticmethod
    def _esc(text):
        return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))

    def _fmt_info(self, line):
        col = "#1E40AF" if self._is_light else "#9DC1FF"
        return f'<span style="color:{col}">{self._esc(line)}</span>'

    def _fmt_warn(self, line):
        col = "#B45309" if self._is_light else "#EAB54A"
        return f'<span style="color:{col}">{self._esc(line)}</span>'

    def _fmt_err(self, line):
        col = "#DC2626" if self._is_light else "#EF6464"
        return f'<span style="color:{col}">{self._esc(line)}</span>'

    def _fmt_debug(self, line):
        col = "#64748B" if self._is_light else "#8C99AD"
        return f'<span style="color:{col}">{self._esc(line)}</span>'
