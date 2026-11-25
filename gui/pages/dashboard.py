"""Minimalist dashboard page: clean status overview and quick actions."""

import platform
import socket
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from gui.components.hero_banner import HeroBanner
from gui.components.metric_card import MetricCard
from services.config_manager import env_info
from sni_proxy.config import VERSION
from .base import Page


class DashboardPage(Page):
    """Clean minimalist dashboard overview."""

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
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
        body_v.setContentsMargins(18, 14, 18, 16)
        body_v.setSpacing(12)
        scroll.setWidget(body)
        body.setAutoFillBackground(False)
        scroll.viewport().setAutoFillBackground(False)
        outer.addWidget(scroll)

        # 1. Compact Status Hero
        self.hero = HeroBanner()
        body_v.addWidget(self.hero)

        # 2. 4 Metric Summary Cards (4 cols wide, 2x2 narrow)
        self.cards_grid = QGridLayout()
        self.cards_grid.setSpacing(10)

        self.card_service = MetricCard(
            icon_kind="pulse", title="服务状态", value="已停止", badge_color="#64748B"
        )
        self.card_port = MetricCard(
            icon_kind="port", title="监听端口", value="8888", badge_color="#2563EB"
        )
        self.card_cert = MetricCard(
            icon_kind="shield", title="证书状态", value="待检查", badge_color="#059669"
        )
        self.card_net = MetricCard(
            icon_kind="globe", title="网络状态", value="待检测", badge_color="#D97706"
        )

        self._metric_cards = [self.card_service, self.card_port,
                              self.card_cert, self.card_net]
        self._metrics_cols = 0
        self._relayout_metrics(4)
        body_v.addLayout(self.cards_grid)

        # 3. Quick Actions Card
        p_ops = self._create_glass_card()
        po_v = QVBoxLayout(p_ops)
        po_v.setContentsMargins(16, 14, 16, 14)
        po_v.setSpacing(10)

        po_head = QHBoxLayout()
        po_title = QLabel("快捷操作")
        po_title.setObjectName("PanelHeaderTitle")
        po_head.addWidget(po_title)
        po_head.addStretch(1)
        po_v.addLayout(po_head)

        ops_row = QHBoxLayout()
        ops_row.setSpacing(10)

        self.btn_start = QPushButton("▶ 启动服务")
        self.btn_start.setObjectName("Primary")
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.setFixedHeight(38)
        self.btn_start.clicked.connect(self._start_service)

        self.btn_stop = QPushButton("■ 停止服务")
        self.btn_stop.setObjectName("Danger")
        self.btn_stop.setCursor(Qt.PointingHandCursor)
        self.btn_stop.setFixedHeight(38)
        self.btn_stop.clicked.connect(self._stop_service)

        self.btn_tun = QPushButton("🛰 TUN 代理")
        self.btn_tun.setObjectName("SecondaryBtn")
        self.btn_tun.setCursor(Qt.PointingHandCursor)
        self.btn_tun.setFixedHeight(38)
        self.btn_tun.clicked.connect(self._goto_tun)

        self.btn_diag = QPushButton("🩺 网络诊断")
        self.btn_diag.setObjectName("SecondaryBtn")
        self.btn_diag.setCursor(Qt.PointingHandCursor)
        self.btn_diag.setFixedHeight(38)
        self.btn_diag.clicked.connect(self._goto_diag)

        self.btn_logs = QPushButton("📄 查看日志")
        self.btn_logs.setObjectName("SecondaryBtn")
        self.btn_logs.setCursor(Qt.PointingHandCursor)
        self.btn_logs.setFixedHeight(38)
        self.btn_logs.clicked.connect(self._goto_logs)

        for b in (self.btn_start, self.btn_stop, self.btn_tun, self.btn_diag, self.btn_logs):
            b.setMinimumWidth(0)
            ops_row.addWidget(b, 1)

        po_v.addLayout(ops_row)
        body_v.addWidget(p_ops)

        # 4. Bottom 2-Column Info: Network & System | Recent Activity
        bot_row = QHBoxLayout()
        bot_row.setSpacing(10)

        # 4.1 Left: Network & System
        p_net = self._create_glass_card()
        pn_v = QVBoxLayout(p_net)
        pn_v.setContentsMargins(16, 14, 16, 14)
        pn_v.setSpacing(8)

        pn_head = QHBoxLayout()
        pn_title = QLabel("网络与环境")
        pn_title.setObjectName("PanelHeaderTitle")
        pn_head.addWidget(pn_title)
        pn_head.addStretch(1)

        self.btn_refresh_net = QPushButton("刷新")
        self.btn_refresh_net.setCursor(Qt.PointingHandCursor)
        self.btn_refresh_net.setObjectName("SecondaryBtnSmall")
        self.btn_refresh_net.clicked.connect(self._manual_refresh)
        pn_head.addWidget(self.btn_refresh_net)
        pn_v.addLayout(pn_head)

        self.item_dns = QLabel("DNS 解析：待检测")
        self.item_dns.setObjectName("ItemText")
        self.item_dns.setMinimumWidth(0)
        pn_v.addWidget(self.item_dns)

        self.item_upstream = QLabel("根证书：待检查")
        self.item_upstream.setObjectName("ItemText")
        self.item_upstream.setMinimumWidth(0)
        pn_v.addWidget(self.item_upstream)

        self.item_latency = QLabel("本地代理延迟：—")
        self.item_latency.setObjectName("ItemText")
        self.item_latency.setMinimumWidth(0)
        pn_v.addWidget(self.item_latency)

        env = env_info()
        try:
            import sys as _sys
            _win = _sys.getwindowsversion()
            os_ver = "Windows 11" if _win.build >= 22000 else "Windows 10"
            _edition = platform.win32_edition()
            if _edition and _edition != "None":
                os_ver += f" · {_edition}"
        except Exception:
            os_ver = f"{platform.system()} {platform.release()}"

        self.lab_os = QLabel(f"系统：{os_ver}")
        self.lab_os.setObjectName("SysInfoLabel")
        self.lab_os.setWordWrap(True)
        self.lab_os.setMinimumWidth(0)
        pn_v.addWidget(self.lab_os)

        self.lab_py = QLabel(f"运行环境：Python {platform.python_version()} · v{VERSION}")
        self.lab_py.setObjectName("SysInfoLabel")
        self.lab_py.setWordWrap(True)
        self.lab_py.setMinimumWidth(0)
        pn_v.addWidget(self.lab_py)
        pn_v.addStretch(1)

        bot_row.addWidget(p_net, 1)

        # 4.2 Right: Recent Records
        p_records = self._create_glass_card()
        pr_v = QVBoxLayout(p_records)
        pr_v.setContentsMargins(16, 14, 16, 14)
        pr_v.setSpacing(8)

        pr_head = QHBoxLayout()
        pr_title = QLabel("运行动态")
        pr_title.setObjectName("PanelHeaderTitle")
        pr_head.addWidget(pr_title)
        pr_head.addStretch(1)

        btn_view_all = QPushButton("全部日志 →")
        btn_view_all.setCursor(Qt.PointingHandCursor)
        btn_view_all.setObjectName("SecondaryBtnSmall")
        btn_view_all.clicked.connect(self._goto_logs)
        pr_head.addWidget(btn_view_all)
        pr_v.addLayout(pr_head)

        self.timeline_v = QVBoxLayout()
        self.timeline_v.setSpacing(6)
        pr_v.addLayout(self.timeline_v)
        pr_v.addStretch(1)

        bot_row.addWidget(p_records, 1)
        body_v.addLayout(bot_row)
        body_v.addStretch(1)

        self._set_default_records()

    def _create_glass_card(self):
        card = QFrame()
        card.setObjectName("GlassPanel")
        card.setAttribute(Qt.WA_StyledBackground, True)
        return card

    def set_palette(self, pal):
        self._pal = pal
        self.hero.set_palette(pal)
        self.update()

    def _relayout_metrics(self, cols):
        """4 列（宽屏）或 2x2（窄屏）排布指标卡片。"""
        if cols == self._metrics_cols:
            return
        self._metrics_cols = cols
        for i, card in enumerate(self._metric_cards):
            self.cards_grid.addWidget(card, i // cols, i % cols)
        for c in range(4):
            self.cards_grid.setColumnStretch(c, 1 if c < cols else 0)

    def _apply_responsive(self):
        if not getattr(self, "_metric_cards", None):
            return
        narrow = self.width() < 740
        self._relayout_metrics(2 if narrow else 4)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_responsive()

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_responsive()

    def _set_default_records(self):
        now_t = time.strftime("%H:%M:%S")
        records = [
            (now_t, "证书状态检查完成", "#10B981"),
            (now_t, "网络接口就绪", "#10B981"),
            (now_t, "等待启动代理服务", "#64748B"),
        ]
        self._render_timeline(records)

    def _render_timeline(self, items):
        while self.timeline_v.count():
            item = self.timeline_v.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                while item.layout().count():
                    sub = item.layout().takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()
        for t_str, desc, col in items:
            row = QHBoxLayout()
            row.setSpacing(8)
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {col}; font-size: 8pt; background: transparent;")
            time_lab = QLabel(t_str)
            time_lab.setObjectName("TimelineTime")
            desc_lab = QLabel(desc)
            desc_lab.setObjectName("TimelineText")
            desc_lab.setMinimumWidth(0)
            row.addWidget(dot)
            row.addWidget(time_lab)
            row.addWidget(desc_lab, 1)
            self.timeline_v.addLayout(row)

    # -------------------------------------------------------------
    # Live Snapshot Updates
    # -------------------------------------------------------------
    def update_snapshot(self, snap):
        running = snap.get("running", False)
        uptime_str = snap.get("uptime_str", "--")

        if running:
            self.hero.set_state(
                True, uptime_str,
                "代理服务运行中",
                "本地 SNI 代理已接管规则流量，运行稳定"
            )
            self.card_service.set_value("运行中", "#10B981")
            self.card_net.set_value("正常", "#10B981")
        else:
            self.hero.set_state(
                False, "--:--:--",
                "代理服务已停止",
                "点击下方「启动服务」或前往「TUN / VPN」开启整机接管"
            )
            self.card_service.set_value("已停止", "#94A3B8")
            self.card_net.set_value("未开启", "#D97706")

        port = snap.get("listen_addr", "127.0.0.1:8888").split(":")[-1]
        self.card_port.set_value(port, "#2563EB")

        dns = snap.get("dns") or {}
        if dns.get("ok"):
            self.item_dns.setText(f"DNS 解析：正常（{dns.get('count', 0)} 个 IP）")
            self.item_dns.setStyleSheet("color: #10B981; font-size: 9.5pt; background: transparent;")
            self.item_dns.setToolTip("、".join(dns.get("ips", [])))
        else:
            err = (dns.get("error") or "解析失败").strip()
            self.item_dns.setText(f"DNS 解析：异常（{err[:28]}）")
            self.item_dns.setStyleSheet("color: #EF4444; font-size: 9.5pt; background: transparent;")
            self.item_dns.setToolTip(err)

        cert = snap.get("cert", {})
        if cert.get("exists", False):
            trusted = (cert.get("installed_machine") is True
                       or cert.get("installed_user") is True)
            unknown = (cert.get("installed_machine") is None
                       and cert.get("installed_user") is None)
            if cert.get("expired", False):
                self.card_cert.set_value("已过期", "#EF4444")
                self.item_upstream.setText("根证书：已过期")
            elif trusted:
                self.card_cert.set_value("已信任", "#10B981")
                self.item_upstream.setText("根证书：已安装并信任")
            elif unknown:
                self.card_cert.set_value("待检查", "#D97706")
                self.item_upstream.setText("根证书：信任状态未知")
            else:
                self.card_cert.set_value("未信任", "#D97706")
                self.item_upstream.setText("根证书：尚未导入信任库")
        else:
            self.card_cert.set_value("未生成", "#D97706")
            self.item_upstream.setText("根证书：首次启动自动生成")

        records = []
        now_t = time.strftime("%H:%M:%S")
        if running:
            records.append((now_t, "SNI 代理运行中 (127.0.0.1:8888)", "#10B981"))
            records.append((now_t, "证书校验正常", "#10B981"))
        else:
            last_err = snap.get("log_last_error", "")
            if last_err:
                records.append((now_t, f"异常：{last_err[:32]}", "#EF4444"))
            records.append((now_t, "服务就绪，随时可启动", "#3B82F6"))
            records.append((now_t, "支持关闭最小化到托盘后台运行", "#64748B"))
        self._render_timeline(records)

    # -------------------------------------------------------------
    # Quick Actions
    # -------------------------------------------------------------
    def _start_service(self):
        text = ("将执行启动流程：\n"
                "1. 生成/复用本机设备 CA 与通配符证书；\n"
                "2. 如未导入根证书则引导信任；\n"
                "3. 后台启动代理进程（127.0.0.1:8888）并应用分流规则。\n\n"
                "是否立即启动服务？")
        self.ctx.confirm_and_run("start", "启动服务", text, "启动")

    def _stop_service(self):
        text = ("将执行停止流程：\n"
                "1. 停止看门狗守护并恢复系统代理设置；\n"
                "2. 安全结束代理主程序进程（保留设备根证书）。\n\n"
                "是否确认停止服务？")
        self.ctx.confirm_and_run("stop", "停止服务", text, "停止")

    def _goto_tun(self):
        idx = self.ctx.stack.indexOf(self.ctx.tun_page)
        if idx >= 0:
            self.ctx.sidebar.select(idx)
            self.ctx._nav(idx)

    def _goto_diag(self):
        idx = self.ctx.stack.indexOf(self.ctx.diag_page)
        if idx >= 0:
            self.ctx.sidebar.select(idx)
            self.ctx._nav(idx)
            if hasattr(self.ctx.diag_page, "_run"):
                self.ctx.diag_page._run()

    def _goto_logs(self):
        idx = self.ctx.stack.indexOf(self.ctx.logs_page)
        if idx >= 0:
            self.ctx.sidebar.select(idx)
            self.ctx._nav(idx)

    def _manual_refresh(self):
        self.ctx.refresh_now()
        try:
            t0 = time.time()
            s = socket.create_connection(("127.0.0.1", 8888), timeout=0.3)
            s.close()
            ms = int((time.time() - t0) * 1000)
            self.item_latency.setText(f"本地代理延迟：{ms} ms")
        except Exception:
            self.item_latency.setText("本地代理延迟：未运行")
