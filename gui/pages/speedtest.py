"""网络测速中心页：直连与代理通道带宽、延迟与抖动测试。"""

import csv
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QGridLayout, QHeaderView, QHBoxLayout,
    QLabel, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from gui.components.glass_panel import GlassPanel, KVGrid
from gui.components.metric_card import MetricCard
from gui.workers import FuncWorker
from services.speedtest_service import SPEED_TARGETS, SpeedTester, get_network_info
from .base import Page


class SpeedTestPage(Page):
    """网络测速中心：支持直连与代理通道测速、实时波形显示与历史记录导出。"""

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self._tester = None
        self._worker = None
        self._history = []
        self._pal = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setAttribute(Qt.WA_StyledBackground, False)

        body = QWidget()
        body.setAttribute(Qt.WA_StyledBackground, False)
        body_v = QVBoxLayout(body)
        body_v.setContentsMargins(20, 16, 20, 16)
        body_v.setSpacing(12)
        scroll.setWidget(body)
        body.setAutoFillBackground(False)
        scroll.viewport().setAutoFillBackground(False)
        outer.addWidget(scroll)
        self._scroll = scroll
        self._body = body

        # -------------------------------------------------------------
        # 1. 顶部操作栏（响应式两行布局：行1 标题+按钮，行2 测速选项）
        # -------------------------------------------------------------
        head_box = QVBoxLayout()
        head_box.setSpacing(8)

        # 行1：标题与主操作按钮
        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("网络测速中心")
        title.setObjectName("TitleLabel")
        sub = QLabel("支持直连与本地代理通道测速，综合测量下载、上传带宽及网络延迟")
        sub.setObjectName("MutedLabel")
        sub.setWordWrap(True)
        title_col.addWidget(title)
        title_col.addWidget(sub)
        top_row.addLayout(title_col, 1)

        # 开始与停止按钮
        btn_box = QHBoxLayout()
        btn_box.setSpacing(8)
        self.btn_start = QPushButton("🚀 开始测速")
        self.btn_start.setObjectName("Primary")
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.setFixedHeight(34)
        self.btn_start.setToolTip("开始完整上下行带宽与延迟抖动测试")
        self.btn_start.clicked.connect(self._start_test)
        btn_box.addWidget(self.btn_start)

        self.btn_stop = QPushButton("■ 停止")
        self.btn_stop.setObjectName("Danger")
        self.btn_stop.setCursor(Qt.PointingHandCursor)
        self.btn_stop.setFixedHeight(34)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setToolTip("中断当前正在进行的测速")
        self.btn_stop.clicked.connect(self._stop_test)
        btn_box.addWidget(self.btn_stop)
        top_row.addLayout(btn_box)

        head_box.addLayout(top_row)

        # 行2：通道模式与节点选择
        opt_bar = QHBoxLayout()
        opt_bar.setSpacing(10)

        lbl_mode = QLabel("测速通道:")
        lbl_mode.setObjectName("KVKey")
        opt_bar.addWidget(lbl_mode)

        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["直连测速 (Direct)", "代理通道测速 (Proxy: 8888)"])
        self.combo_mode.setToolTip("选择测速流量是通过本地代理转发还是直接出网")
        self.combo_mode.setFixedHeight(28)
        self.combo_mode.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo_mode.setMinimumContentsLength(10)
        self.combo_mode.setMinimumWidth(0)
        opt_bar.addWidget(self.combo_mode)

        opt_bar.addSpacing(10)
        lbl_target = QLabel("测速节点:")
        lbl_target.setObjectName("KVKey")
        opt_bar.addWidget(lbl_target)

        self.combo_target = QComboBox()
        for t in SPEED_TARGETS:
            self.combo_target.addItem(t["name"])
        self.combo_target.setToolTip("选择测速的目标源节点")
        self.combo_target.setFixedHeight(28)
        self.combo_target.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo_target.setMinimumContentsLength(10)
        self.combo_target.setMinimumWidth(0)
        opt_bar.addWidget(self.combo_target)

        opt_bar.addStretch(1)
        head_box.addLayout(opt_bar)

        body_v.addLayout(head_box)

        # -------------------------------------------------------------
        # 2. 核心 4 个指标卡片 (下载 / 上传 / 延迟 / 抖动)
        #    窄窗口自动改为 2x2，避免整页被四张卡片撑宽而右侧裁切
        # -------------------------------------------------------------
        self.metrics_grid = QGridLayout()
        self.metrics_grid.setSpacing(12)

        self.card_dl = MetricCard(
            icon_kind="pulse", title="下载速率", value="—",
            badge_color="#10B981", chart_type="wave", chart_color="#10B981"
        )
        self.card_ul = MetricCard(
            icon_kind="pulse", title="上传速率", value="—",
            badge_color="#3B82F6", chart_type="wave", chart_color="#3B82F6"
        )
        self.card_ping = MetricCard(
            icon_kind="clock", title="网络延迟", value="—",
            badge_color="#8B5CF6", chart_type="bars", chart_color="#A78BFA"
        )
        self.card_jitter = MetricCard(
            icon_kind="globe", title="网络抖动", value="—",
            badge_color="#F59E0B", chart_type="wave_signal", chart_color="#FBBF24"
        )

        self._metric_cards = [self.card_dl, self.card_ul, self.card_ping,
                              self.card_jitter]
        self._metrics_cols = 0
        self._relayout_metrics(4)
        body_v.addLayout(self.metrics_grid)

        # -------------------------------------------------------------
        # 3. 中间区域：实时测速动态 + 当前网络环境
        #    宽屏左右并排，窄屏上下堆叠，避免两栏最小宽度相加后溢出
        # -------------------------------------------------------------
        self.mid_grid = QGridLayout()
        self.mid_grid.setSpacing(12)

        # 3.1 实时监控卡片
        p_gauge = GlassPanel("测速实时状态")
        pg_v = QVBoxLayout()
        pg_v.setSpacing(10)
        pg_v.setContentsMargins(8, 6, 8, 8)

        # 大数字实时读数
        readout_box = QHBoxLayout()
        readout_box.setAlignment(Qt.AlignCenter)
        self.speed_num = QLabel("0.00")
        self.speed_num.setMinimumWidth(0)
        self.speed_num.setStyleSheet(
            "font-size: 32pt; font-weight: 800; color: #2563EB; font-family: 'Segoe UI', sans-serif;")
        self.speed_unit = QLabel("Mbps")
        self.speed_unit.setMinimumWidth(0)
        self.speed_unit.setStyleSheet(
            "font-size: 13pt; font-weight: 600; color: #64748B; margin-left: 6px; margin-top: 12px;")
        readout_box.addWidget(self.speed_num)
        readout_box.addWidget(self.speed_unit)
        pg_v.addLayout(readout_box)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background: rgba(100, 116, 139, 0.2);
                border: none;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563EB, stop:1 #06B6D4);
                border-radius: 4px;
            }
        """)
        pg_v.addWidget(self.progress_bar)

        # 提示文案
        self.status_tip = QLabel("准备就绪 · 点击「开始测速」运行全面检测")
        self.status_tip.setAlignment(Qt.AlignCenter)
        self.status_tip.setObjectName("MutedLabel")
        self.status_tip.setWordWrap(True)
        self.status_tip.setMinimumWidth(0)
        self.status_tip.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        pg_v.addWidget(self.status_tip)

        p_gauge.add(pg_v)
        self._gauge_panel = p_gauge

        # 3.2 网络环境卡片
        p_net = GlassPanel("网络环境信息")
        self.net_grid = KVGrid()
        self.net_grid.grid.setHorizontalSpacing(12)
        self.net_grid.add_row("本机出口 IP", "--", "ip")
        self.net_grid.add_row("计算机主机名", "--", "host")
        self.net_grid.add_row("本地代理地址", "127.0.0.1:8888", "proxy")
        self.net_grid.add_row("服务运行状态", "--", "status")
        self.net_grid.add_row("最近测速时间", "尚未测速", "time")
        p_net.add(self.net_grid)
        self._net_panel = p_net

        self._mid_wide = None
        self._relayout_mid(True)
        body_v.addLayout(self.mid_grid)

        # -------------------------------------------------------------
        # 4. 底部：测速历史记录与导出
        # -------------------------------------------------------------
        p_hist = GlassPanel("测速历史记录")
        hist_lay = QVBoxLayout()
        hist_lay.setSpacing(8)

        bar_hist = QHBoxLayout()
        self.lab_hist_count = QLabel("共 0 次测速记录")
        self.lab_hist_count.setObjectName("MutedLabel")
        bar_hist.addWidget(self.lab_hist_count)
        bar_hist.addStretch(1)

        self.btn_export = QPushButton("📊 导出 CSV 报告")
        self.btn_export.setObjectName("SecondaryBtnSmall")
        self.btn_export.setCursor(Qt.PointingHandCursor)
        self.btn_export.clicked.connect(self._export_csv)
        self.btn_export.setEnabled(False)
        bar_hist.addWidget(self.btn_export)

        self.btn_clear_hist = QPushButton("清空记录")
        self.btn_clear_hist.setObjectName("SecondaryBtnSmall")
        self.btn_clear_hist.setCursor(Qt.PointingHandCursor)
        self.btn_clear_hist.clicked.connect(self._clear_history)
        self.btn_clear_hist.setEnabled(False)
        bar_hist.addWidget(self.btn_clear_hist)

        hist_lay.addLayout(bar_hist)

        # 表格展示
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["测试时间", "测速模式", "下载带宽", "上传带宽", "网络延迟", "网络抖动"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setFixedHeight(135)
        # Stretch 列会让 QTableWidget 的 minimumSizeHint 随当前宽度增长，
        # 进而把整页最小宽度越撑越大；显式允许它收缩到 0。
        self.table.setMinimumWidth(0)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.table.horizontalHeader().setMinimumSectionSize(40)
        self.table.setStyleSheet("""
            QTableWidget {
                background: transparent;
                border: 1px solid rgba(148, 163, 184, 0.2);
                border-radius: 10px;
                gridline-color: rgba(148, 163, 184, 0.15);
            }
            QHeaderView::section {
                background: rgba(100, 116, 139, 0.15);
                border: none;
                padding: 6px;
                font-weight: 600;
                color: #64748B;
            }
        """)
        hist_lay.addWidget(self.table)
        p_hist.add(hist_lay)
        body_v.addWidget(p_hist)

        self._refresh_net_info()

    def set_palette(self, pal):
        self._pal = pal
        is_light = pal.get("id") == "light"
        speed_col = "#2563EB" if is_light else "#38BDF8"
        self.speed_num.setStyleSheet(
            f"font-size: 32pt; font-weight: 800; color: {speed_col}; font-family: 'Segoe UI', sans-serif;")
        self.update()

    def _relayout_metrics(self, cols):
        """4 列（宽屏）或 2x2（窄屏）排布指标卡片。"""
        if cols == self._metrics_cols:
            return
        self._metrics_cols = cols
        for i, card in enumerate(self._metric_cards):
            self.metrics_grid.addWidget(card, i // cols, i % cols)
        for c in range(4):
            self.metrics_grid.setColumnStretch(c, 1 if c < cols else 0)
        # 卡片换位后必须让布局失效，否则 QScrollArea 可能保留旧的宽度
        self.metrics_grid.invalidate()
        self.metrics_grid.activate()

    def _relayout_mid(self, wide):
        """测速状态与网络环境：宽屏并排，窄屏上下堆叠。"""
        if self._mid_wide == wide:
            return
        self._mid_wide = wide
        if wide:
            self.mid_grid.addWidget(self._gauge_panel, 0, 0)
            self.mid_grid.addWidget(self._net_panel, 0, 1)
            self.mid_grid.setColumnStretch(0, 6)
            self.mid_grid.setColumnStretch(1, 4)
        else:
            self.mid_grid.addWidget(self._gauge_panel, 0, 0)
            self.mid_grid.addWidget(self._net_panel, 1, 0)
            self.mid_grid.setColumnStretch(0, 1)
            self.mid_grid.setColumnStretch(1, 0)
        self.mid_grid.invalidate()
        self.mid_grid.activate()

    def _apply_responsive(self):
        if not getattr(self, "_metric_cards", None):
            return
        narrow = self.width() < 900
        self._relayout_metrics(2 if narrow else 4)
        self._relayout_mid(not narrow)
        # 窄窗口缩小大数字字号，避免读数面板把整页撑宽
        size, unit = (24, 11) if narrow else (32, 13)
        self.speed_num.setStyleSheet(
            f"font-size: {size}pt; font-weight: 800; color: "
            f"{'#2563EB' if self._pal.get('id') == 'light' else '#38BDF8'}; "
            "font-family: 'Segoe UI', sans-serif;")
        self.speed_unit.setStyleSheet(
            f"font-size: {unit}pt; font-weight: 600; color: #64748B; "
            "margin-left: 6px; margin-top: 12px;")
        # 强制同步一次滚动区宽度，避免窗口缩小时内容仍保持旧的宽尺寸
        self._sync_body_width()
        QTimer.singleShot(0, self._sync_body_width)

    def _sync_body_width(self):
        """让滚动区内容宽度跟随视口，避免 4 列/2 列切换后残留旧宽度。"""
        if not getattr(self, "_scroll", None):
            return
        vp = self._scroll.viewport().width()
        if vp <= 0:
            return
        self._body.layout().activate()
        if (self._body.width() != vp
                and self._body.minimumSizeHint().width() <= vp):
            self._body.resize(vp, self._body.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_responsive()

    def showEvent(self, event):
        super().showEvent(event)
        # 页面从隐藏切到前台时宽度可能已经变化，补一次布局评估
        self._apply_responsive()

    def _refresh_net_info(self):
        info = get_network_info()
        self.net_grid.set_value("ip", info.get("local_ip", "--"))
        self.net_grid.set_value("host", info.get("hostname", "--"))
        snap = getattr(self.ctx, "last_snapshot", {})
        running = snap.get("running", False)
        self.net_grid.set_value("status", "运行中" if running else "已停止")

    def _start_test(self):
        if self._worker and self._worker.isRunning():
            return

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.combo_mode.setEnabled(False)
        self.combo_target.setEnabled(False)

        use_proxy = self.combo_mode.currentIndex() == 1
        target_idx = self.combo_target.currentIndex()

        self._tester = SpeedTester(
            target_idx=target_idx,
            use_proxy=use_proxy,
            proxy_host="127.0.0.1",
            proxy_port=8888,
        )

        self.card_dl.set_value("测速中…", "#3B82F6")
        self.card_ul.set_value("等待中…", "#94A3B8")
        self.card_ping.set_value("测速中…", "#A855F7")
        self.card_jitter.set_value("测速中…", "#F59E0B")
        self.speed_num.setText("0.00")
        self.progress_bar.setValue(5)
        self.status_tip.setText("正在连接测速节点，初始化环境...")

        def run_job(on_progress):
            return self._tester.run(on_progress)

        self._worker = FuncWorker(run_job, parent=self)
        self._worker.progress.connect(self._on_progress_update)
        self._worker.done.connect(self._on_test_done)
        self._worker.start()

    def _stop_test(self):
        if self._tester:
            self._tester.cancel()
        self.status_tip.setText("测速已手动终止")
        self.btn_stop.setEnabled(False)

    def _on_progress_update(self, data):
        if not isinstance(data, dict):
            return

        pct = data.get("progress", 0)
        self.progress_bar.setValue(pct)

        msg = data.get("msg", "")
        if msg:
            self.status_tip.setText(msg)

        if "speed_mbps" in data:
            self.speed_num.setText(f"{data['speed_mbps']:.2f}")

        phase = data.get("phase")
        if phase == "download" and "speed_mbps" in data:
            self.card_dl.set_value(f"{data['speed_mbps']:.2f} Mbps", "#10B981")
        elif phase == "upload" and "speed_mbps" in data:
            self.card_ul.set_value(f"{data['speed_mbps']:.2f} Mbps", "#3B82F6")

    @staticmethod
    def _fmt_speed(value):
        """Format a bandwidth value; None means the measurement failed."""
        return "测速失败" if value is None else f"{value:.2f} Mbps"

    @staticmethod
    def _fmt_ms(value):
        """Format a latency value; None means unavailable."""
        return "不可用" if value is None else f"{value:.1f} ms"

    def _on_test_done(self, result, error):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.combo_mode.setEnabled(True)
        self.combo_target.setEnabled(True)

        if error or not result:
            self.status_tip.setText(f"测速未能正常完成：{error or '已取消'}")
            return

        self.progress_bar.setValue(100)

        dl = result.get("download_mbps")
        ul = result.get("upload_mbps")
        ping = result.get("ping_ms")
        jitter = result.get("jitter_ms")

        self.card_dl.set_value(
            self._fmt_speed(dl), "#10B981" if dl is not None else "#EF4444")
        self.card_ul.set_value(
            self._fmt_speed(ul), "#3B82F6" if ul is not None else "#EF4444")
        self.card_ping.set_value(
            self._fmt_ms(ping), "#A855F7" if ping is not None else "#EF4444")
        self.card_jitter.set_value(
            self._fmt_ms(jitter), "#F59E0B" if jitter is not None else "#EF4444")
        self.speed_num.setText(f"{dl:.2f}" if dl is not None else "--")

        detail = result.get("detail") or {}
        dl_tip = detail.get("download_error") or detail.get("download_source") or ""
        ul_tip = detail.get("upload_error") or detail.get("upload_endpoint") or ""
        if detail.get("upload_note"):
            ul_tip = detail["upload_note"] + (("\n" + ul_tip) if ul_tip else "")
        self.card_dl.setToolTip(dl_tip)
        self.card_ul.setToolTip(ul_tip)

        # 端点本身限速/未确认接收到完整请求体时，用 ≈ 标注为估算值
        if ul is not None and detail.get("upload_estimated"):
            self.card_ul.set_value(f"≈{ul:.2f} Mbps", "#3B82F6")

        if result.get("ok", True):
            self.status_tip.setText("✅ 测速已完成！")
            self.status_tip.setToolTip("")
        else:
            err = result.get("error") or "部分测速项目失败"
            brief = err.split("；")[0]
            if len(brief) > 60:
                brief = brief[:57] + "…"
            self.status_tip.setText(f"⚠️ {brief}（详细原因见卡片提示）")
            self.status_tip.setToolTip(err)

        self.net_grid.set_value("time", result["timestamp"])
        self._add_history(result)

    def _add_history(self, res):
        self._history.insert(0, res)
        row = self.table.rowCount()
        self.table.insertRow(0)

        items = [
            res["timestamp"],
            res["mode"],
            self._fmt_speed(res.get("download_mbps")),
            self._fmt_speed(res.get("upload_mbps")),
            self._fmt_ms(res.get("ping_ms")),
            self._fmt_ms(res.get("jitter_ms")),
        ]
        for col, val in enumerate(items):
            it = QTableWidgetItem(val)
            it.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(0, col, it)

        self.lab_hist_count.setText(f"共 {len(self._history)} 次测速记录")
        self.btn_export.setEnabled(True)
        self.btn_clear_hist.setEnabled(True)

    def _clear_history(self):
        self._history.clear()
        self.table.setRowCount(0)
        self.lab_hist_count.setText("共 0 次测速记录")
        self.btn_export.setEnabled(False)
        self.btn_clear_hist.setEnabled(False)

    def _export_csv(self):
        if not self._history:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出测速报告", f"speedtest_{time.strftime('%Y%m%d_%H%M%S')}.csv",
            "CSV 电子表格 (*.csv);;所有文件 (*)"
        )
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(["测试时间", "测速模式", "测速节点", "下载带宽(Mbps)", "上传带宽(Mbps)", "延迟(ms)", "抖动(ms)", "本机IP"])
                def _num(v, digits=2):
                    return "" if v is None else f"{v:.{digits}f}"
                for r in self._history:
                    writer.writerow([
                        r["timestamp"],
                        r["mode"],
                        r.get("target_name", ""),
                        _num(r.get("download_mbps")),
                        _num(r.get("upload_mbps")),
                        _num(r.get("ping_ms"), 1),
                        _num(r.get("jitter_ms"), 1),
                        r.get("net_info", {}).get("local_ip", ""),
                    ])
            self.status_tip.setText(f"测速记录已成功导出至：{path}")
        except Exception as e:
            self.status_tip.setText(f"导出失败：{e}")
