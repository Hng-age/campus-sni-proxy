"""Network diagnostics page: one-click environment report with export."""

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from gui.components.glass_panel import GlassPanel
from gui.workers import FuncWorker
from services import diagnostics as diag_service
from .base import Page

LEVEL_CN = {"ok": "正常", "warn": "需要注意", "error": "异常"}
LEVEL_COLOR = {"ok": "#22C58B", "warn": "#EAB54A", "error": "#EF6464"}


class DiagnosticsPage(Page):
    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 18)
        outer.setSpacing(14)

        # header
        head = QHBoxLayout()
        self.btn_run = QPushButton("一键环境诊断")
        self.btn_run.setObjectName("Primary")
        self.btn_run.setCursor(Qt.PointingHandCursor)
        self.btn_run.setToolTip("检查网络接口、DNS、端口、系统代理、证书与运行环境")
        self.btn_run.clicked.connect(self._run)
        head.addWidget(self.btn_run)

        self.summary_lab = QLabel("尚未诊断")
        self.summary_lab.setObjectName("MutedLabel")
        head.addSpacing(12)
        head.addWidget(self.summary_lab)
        head.addStretch(1)

        self.btn_export = QPushButton("导出报告")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self._export)
        head.addWidget(self.btn_export)

        self.btn_clear = QPushButton("清除结果")
        self.btn_clear.setEnabled(False)
        self.btn_clear.clicked.connect(self._clear)
        head.addWidget(self.btn_clear)
        outer.addLayout(head)

        # summary chips
        chips = QHBoxLayout()
        chips.setSpacing(10)
        self.chip_ok = QLabel("正常 0")
        self.chip_ok.setStyleSheet("color:#22C58B; font-weight:600;")
        self.chip_warn = QLabel("需要注意 0")
        self.chip_warn.setStyleSheet("color:#EAB54A; font-weight:600;")
        self.chip_err = QLabel("异常 0")
        self.chip_err.setStyleSheet("color:#EF6464; font-weight:600;")
        for c in (self.chip_ok, self.chip_warn, self.chip_err):
            chips.addWidget(c)
        chips.addStretch(1)
        self.mask_note = QLabel("报告 IP 已脱敏 · 不含密码/令牌/私钥")
        self.mask_note.setObjectName("TinyLabel")
        chips.addWidget(self.mask_note)
        outer.addLayout(chips)

        # result rows
        self.panel = GlassPanel("检查结果")
        self.rows_host = QWidget()
        self.rows_host.setAttribute(Qt.WA_StyledBackground, False)
        self.rows = QVBoxLayout(self.rows_host)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(10)
        self.placeholder = QLabel("点击“一键环境诊断”开始检查本机网络环境。")
        self.placeholder.setObjectName("MutedLabel")
        self.rows.addWidget(self.placeholder)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(self.rows_host)
        self.rows_host.setAutoFillBackground(False)
        scroll.viewport().setAutoFillBackground(False)
        self.panel.add(scroll, 1)
        outer.addWidget(self.panel, 1)

        self.last_run_lab = QLabel("")
        self.last_run_lab.setObjectName("TinyLabel")
        outer.addWidget(self.last_run_lab)

        self.results = []
        self.report_text = ""
        self._worker = None

    # ------------------------------------------------------------- run
    def _run(self):
        if self._worker and self._worker.isRunning():
            return
        self._clear_rows()
        self.btn_run.setEnabled(False)
        self.btn_run.setText("诊断中…")
        mask = bool(self.ctx.settings.get("mask_diagnostics", True))
        self.mask_note.setText(
            "报告 IP 已脱敏 · 不含密码/令牌/私钥" if mask
            else "报告未脱敏（含本机 IP）· 不含密码/令牌/私钥")
        self.summary_lab.setText("正在检查…")

        def job(on_progress):
            return diag_service.run_all(
                mask=mask,
                on_check=lambda r: on_progress(r["name"]))
        self._worker = FuncWorker(job, parent=self)
        self._worker.progress.connect(self._check_started)
        self._worker.done.connect(self._done)
        self._worker.start()

    def _check_started(self, name):
        self.summary_lab.setText(f"正在检查：{name}…")

    def _done(self, result, error):
        self.btn_run.setEnabled(True)
        self.btn_run.setText("一键环境诊断")
        if error or not result:
            self.summary_lab.setText(f"诊断失败：{error}")
            return
        results, report, started, seconds = result
        self.results = results
        self.report_text = report
        self._render(results)
        counts = {"ok": 0, "warn": 0, "error": 0}
        for r in results:
            counts[r["level"]] += 1
        self.chip_ok.setText(f"正常 {counts['ok']}")
        self.chip_warn.setText(f"需要注意 {counts['warn']}")
        self.chip_err.setText(f"异常 {counts['error']}")
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started))
        self.summary_lab.setText(
            f"诊断完成（{seconds}s）：正常 {counts['ok']} / "
            f"需要注意 {counts['warn']} / 异常 {counts['error']}")
        self.last_run_lab.setText(f"最近诊断：{stamp}（{seconds} 秒）")
        self.btn_export.setEnabled(True)
        self.btn_clear.setEnabled(True)
        self.ctx.settings.set("last_diag_time", stamp)
        self.ctx.settings.set(
            "last_diag_summary",
            f"正常 {counts['ok']} / 注意 {counts['warn']} / "
            f"异常 {counts['error']}（{stamp}）")

    # ---------------------------------------------------------- render
    def _clear_rows(self):
        while self.rows.count():
            item = self.rows.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _render(self, results):
        self._clear_rows()
        for r in results:
            row = QWidget()
            row.setAttribute(Qt.WA_StyledBackground, False)
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(10)
            dot = QLabel("●")
            dot.setStyleSheet(
                f"color:{LEVEL_COLOR[r['level']]}; font-size:11px; "
                "background:transparent;")
            name = QLabel(f"{r['name']}")
            name.setObjectName("KVValue")
            level = QLabel(LEVEL_CN[r["level"]])
            level.setStyleSheet(
                f"color:{LEVEL_COLOR[r['level']]}; font-weight:600;")
            detail = QLabel(r["detail"])
            detail.setObjectName("MutedLabel")
            detail.setWordWrap(True)
            detail.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            h.addWidget(dot, 0, Qt.AlignTop)
            h.addWidget(name)
            h.addWidget(level)
            h.addWidget(detail, 1)
            self.rows.addWidget(row)
        self.rows.addStretch(1)

    def _clear(self):
        self._clear_rows()
        self.rows.addWidget(self.placeholder)
        self.results = []
        self.report_text = ""
        self.summary_lab.setText("尚未诊断")
        for lab, txt in ((self.chip_ok, "正常 0"),
                         (self.chip_warn, "需要注意 0"),
                         (self.chip_err, "异常 0")):
            lab.setText(txt)
        self.btn_export.setEnabled(False)
        self.btn_clear.setEnabled(False)
        self.last_run_lab.setText("")

    def _export(self):
        if not self.report_text:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出诊断报告",
            f"diagnostic-{time.strftime('%Y%m%d-%H%M%S')}.txt",
            "文本文件 (*.txt);;所有文件 (*)")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.report_text)
        self.last_run_lab.setText(f"报告已导出：{path}")
