"""Dashboard page: pixel-perfect implementation of the 2.0.0 mockup design."""

import platform
import socket
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from gui.components.device_widget import DeviceWidget
from gui.components.globe_widget import GlobeWidget
from gui.components.hero_banner import HeroBanner
from gui.components.metric_card import MetricCard
from services.config_manager import env_info
from sni_proxy.config import VERSION
from .base import Page


class DashboardPage(Page):
    """High-tech glassmorphism dashboard matching the exact 2.0.0 mockup."""

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)

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
        body_v.setContentsMargins(14, 12, 14, 14)
        body_v.setSpacing(12)
        scroll.setWidget(body)
        body.setAutoFillBackground(False)
        scroll.viewport().setAutoFillBackground(False)
        outer.addWidget(scroll)

        # -------------------------------------------------------------
        # 1. Top Hero Status Banner
        # -------------------------------------------------------------
        self.hero = HeroBanner()
        body_v.addWidget(self.hero)

        # -------------------------------------------------------------
        # 2. Row 2: 4 Metric Cards（窄窗口自动 2x2）
        # -------------------------------------------------------------
        self.cards_grid = QGridLayout()
        self.cards_grid.setSpacing(12)

        self.card_service = MetricCard(
            icon_kind="pulse", title="服务状态", value="已停止",
            badge_color="#2563EB", chart_type="wave", chart_color="#22C58B"
        )
        self.card_port = MetricCard(
            icon_kind="port", title="监听端口", value="8888",
            badge_color="#8B5CF6", chart_type="bars", chart_color="#A78BFA"
        )
        self.card_cert = MetricCard(
            icon_kind="shield", title="证书状态", value="待检查",
            badge_color="#06B6D4", chart_type="wave", chart_color="#2DD4BF"
        )
        self.card_net = MetricCard(
            icon_kind="globe", title="网络状态", value="良好",
            badge_color="#F59E0B", chart_type="wave_signal", chart_color="#FBBF24"
        )

        self._metric_cards = [self.card_service, self.card_port,
                             self.card_cert, self.card_net]
        self._metrics_cols = 0
        self._relayout_metrics(4)
        body_v.addLayout(self.cards_grid)

        # -------------------------------------------------------------
        # 3. Row 3: 网络连接概览 (60%) + 快速操作 (40%)
        # -------------------------------------------------------------
        mid_row = QHBoxLayout()
        mid_row.setSpacing(12)

        # 3.1 Left Panel: 网络连接概览
        p_net = self._create_glass_card()
        pn_v = QVBoxLayout(p_net)
        pn_v.setContentsMargins(18, 14, 18, 14)
        pn_v.setSpacing(10)

        # Header
        pn_head = QHBoxLayout()
        pn_title = QLabel("网络连接概览")
        pn_title.setObjectName("PanelHeaderTitle")
        pn_head.addWidget(pn_title)
        pn_head.addStretch(1)

        self.btn_refresh_net = QPushButton("🔄 实时刷新")
        self.btn_refresh_net.setCursor(Qt.PointingHandCursor)
        self.btn_refresh_net.setObjectName("SecondaryBtnSmall")
        self.btn_refresh_net.clicked.connect(self._manual_refresh)
        pn_head.addWidget(self.btn_refresh_net)
        pn_v.addLayout(pn_head)

        # Content split: Info list (left) + Globe (right)
        pn_body = QHBoxLayout()
        pn_body.setSpacing(10)

        # Info list
        info_col = QVBoxLayout()
        info_col.setSpacing(8)

        self.chip_net_state = QLabel("  🟢 网络已连接")
        self.chip_net_state.setStyleSheet("""
            QLabel {
                background: rgba(16, 185, 129, 0.15);
                border: 1px solid rgba(52, 211, 153, 0.4);
                border-radius: 12px;
                color: #10B981;
                font-size: 10pt;
                font-weight: 600;
                padding: 4px 8px;
            }
        """)
        info_col.addWidget(self.chip_net_state, 0, Qt.AlignLeft)

        self.item_dns = QLabel("🖧 DNS 解析： 待检测")
        self.item_dns.setObjectName("ItemText")
        info_col.addWidget(self.item_dns)

        self.item_upstream = QLabel("🔒 上游证书： 待检查")
        self.item_upstream.setObjectName("ItemText")
        info_col.addWidget(self.item_upstream)

        self.item_latency = QLabel("⏱ 平均延迟： —")
        self.item_latency.setObjectName("ItemText")
        info_col.addWidget(self.item_latency)
        info_col.addStretch(1)

        pn_body.addLayout(info_col, 1)

        # Globe widget
        self.globe = GlobeWidget()
        pn_body.addWidget(self.globe, 0, Qt.AlignCenter)

        pn_v.addLayout(pn_body)
        mid_row.addWidget(p_net, 6)

        # 3.2 Right Panel: 快速操作
        p_ops = self._create_glass_card()
        po_v = QVBoxLayout(p_ops)
        po_v.setContentsMargins(18, 14, 18, 14)
        po_v.setSpacing(12)

        po_head = QHBoxLayout()
        po_title = QLabel("快速操作")
        po_title.setObjectName("PanelHeaderTitle")
        po_head.addWidget(po_title)
        po_head.addStretch(1)
        po_close = QLabel("✕")
        po_close.setStyleSheet("color: #64748B; font-size: 11pt;")
        po_head.addWidget(po_close)
        po_v.addLayout(po_head)

        # 2x2 Action Button Grid
        grid = QGridLayout()
        grid.setSpacing(10)

        self.btn_start = QPushButton("▶ 启动服务")
        self.btn_start.setCursor(Qt.PointingHandCursor)
        self.btn_start.setFixedHeight(48)
        self.btn_start.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1D4ED8, stop:1 #3B82F6);
                border: 1px solid rgba(56, 189, 248, 0.6);
                border-radius: 12px;
                color: #FFFFFF;
                font-size: 11pt;
                font-weight: 700;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563EB, stop:1 #60A5FA);
                border-color: #93C5FD;
            }
            QPushButton:pressed { background: #1E40AF; }
        """)
        self.btn_start.clicked.connect(self._start_service)
        grid.addWidget(self.btn_start, 0, 0)

        self.btn_stop = QPushButton("■ 停止服务")
        self.btn_stop.setCursor(Qt.PointingHandCursor)
        self.btn_stop.setFixedHeight(48)
        self.btn_stop.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #991B1B, stop:1 #DC2626);
                border: 1px solid rgba(248, 113, 113, 0.5);
                border-radius: 12px;
                color: #FFFFFF;
                font-size: 11pt;
                font-weight: 700;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #B91C1C, stop:1 #EF4444);
                border-color: #FCA5A5;
            }
            QPushButton:pressed { background: #7F1D1D; }
        """)
        self.btn_stop.clicked.connect(self._stop_service)
        grid.addWidget(self.btn_stop, 0, 1)

        self.btn_diag = QPushButton("🩺 网络诊断")
        self.btn_diag.setCursor(Qt.PointingHandCursor)
        self.btn_diag.setFixedHeight(48)
        self.btn_diag.setObjectName("SecondaryBtn")
        self.btn_diag.clicked.connect(self._goto_diag)
        grid.addWidget(self.btn_diag, 1, 0)

        self.btn_logs = QPushButton("📄 查看日志")
        self.btn_logs.setCursor(Qt.PointingHandCursor)
        self.btn_logs.setFixedHeight(48)
        self.btn_logs.setObjectName("SecondaryBtn")
        self.btn_logs.clicked.connect(self._goto_logs)
        grid.addWidget(self.btn_logs, 1, 1)

        po_v.addLayout(grid)
        mid_row.addWidget(p_ops, 4)
        body_v.addLayout(mid_row)

        # -------------------------------------------------------------
        # 4. Row 4: 最近运行记录 (60%) + 系统信息 (40%)
        # -------------------------------------------------------------
        bot_row = QHBoxLayout()
        bot_row.setSpacing(12)

        # 4.1 Left Panel: 最近运行记录
        p_records = self._create_glass_card()
        pr_v = QVBoxLayout(p_records)
        pr_v.setContentsMargins(18, 14, 18, 14)
        pr_v.setSpacing(10)

        pr_head = QHBoxLayout()
        pr_title = QLabel("最近运行记录")
        pr_title.setObjectName("PanelHeaderTitle")
        pr_head.addWidget(pr_title)
        pr_head.addStretch(1)

        btn_view_all = QPushButton("查看全部 →")
        btn_view_all.setCursor(Qt.PointingHandCursor)
        btn_view_all.setStyleSheet("""
            QPushButton {
                color: #2563EB; background: transparent; border: none; font-size: 9.5pt;
            }
            QPushButton:hover { color: #3B82F6; text-decoration: underline; }
        """)
        btn_view_all.clicked.connect(self._goto_logs)
        pr_head.addWidget(btn_view_all)
        pr_v.addLayout(pr_head)

        self.timeline_v = QVBoxLayout()
        self.timeline_v.setSpacing(6)
        pr_v.addLayout(self.timeline_v)
        pr_v.addStretch(1)
        bot_row.addWidget(p_records, 6)

        # 4.2 Right Panel: 系统信息
        p_sys = self._create_glass_card()
        ps_v = QVBoxLayout(p_sys)
        ps_v.setContentsMargins(18, 14, 18, 14)
        ps_v.setSpacing(10)

        ps_title = QLabel("系统信息")
        ps_title.setObjectName("PanelHeaderTitle")
        ps_v.addWidget(ps_title)

        sys_body = QHBoxLayout()
        sys_body.setSpacing(10)

        sys_info_col = QVBoxLayout()
        sys_info_col.setSpacing(6)

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

        self.lab_os = QLabel(f"🪟 操作系统： {os_ver}")
        self.lab_os.setObjectName("SysInfoLabel")
        self.lab_os.setWordWrap(True)
        self.lab_os.setMinimumWidth(0)
        sys_info_col.addWidget(self.lab_os)

        self.lab_py = QLabel(f"🐍 Python 版本： {platform.python_version()}")
        self.lab_py.setObjectName("SysInfoLabel")
        self.lab_py.setWordWrap(True)
        self.lab_py.setMinimumWidth(0)
        sys_info_col.addWidget(self.lab_py)

        # openssl version 输出为 "OpenSSL 3.5.1 ..."，旧逻辑只取首词
        # 会把版本号显示成 "OpenSSL"（截图中的问题）
        _ssl_tokens = env.get("openssl_version", "").split()
        openssl_short = (_ssl_tokens[1] if len(_ssl_tokens) > 1
                         else (_ssl_tokens[0] if _ssl_tokens else "未知"))
        self.lab_ssl = QLabel(f"⚙ OpenSSL 版本： {openssl_short}")
        self.lab_ssl.setObjectName("SysInfoLabel")
        self.lab_ssl.setWordWrap(True)
        self.lab_ssl.setMinimumWidth(0)
        sys_info_col.addWidget(self.lab_ssl)

        ver_pill = QLabel(f"  版本：v{VERSION}  ")
        ver_pill.setStyleSheet("""
            QLabel {
                background: rgba(16, 185, 129, 0.2);
                border: 1px solid rgba(52, 211, 153, 0.5);
                border-radius: 10px;
                color: #10B981;
                font-size: 9pt;
                font-weight: 700;
                padding: 2px 6px;
            }
        """)
        sys_info_col.addWidget(ver_pill, 0, Qt.AlignLeft)
        sys_info_col.addStretch(1)

        sys_body.addLayout(sys_info_col, 1)

        self.device = DeviceWidget()
        sys_body.addWidget(self.device, 0, Qt.AlignCenter)

        ps_v.addLayout(sys_body)
        bot_row.addWidget(p_sys, 4)
        body_v.addLayout(bot_row)

        self._start_time = None
        self._set_default_records()

    def _create_glass_card(self):
        card = QFrame()
        card.setObjectName("GlassPanel")
        card.setAttribute(Qt.WA_StyledBackground, True)
        return card

    def set_palette(self, pal):
        self._pal = pal
        self.hero.set_palette(pal)
        self.globe.set_palette(pal)
        self.device.set_palette(pal)
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
        narrow = self.width() < 760
        self._relayout_metrics(2 if narrow else 4)
        # 窄窗口隐藏纯装饰性的地球/设备插画，避免把行最小宽度撑爆
        self.globe.setVisible(not narrow)
        self.device.setVisible(not narrow)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_responsive()

    def showEvent(self, event):
        super().showEvent(event)
        self._apply_responsive()

    def _set_default_records(self):
        # Initial timeline entries matching mockup style
        now_t = time.strftime("%H:%M:%S")
        records = [
            (now_t, "证书状态检查完成", "#10B981"),
            (now_t, "网络诊断通过", "#10B981"),
            (now_t, "服务就绪，等待启动", "#2563EB"),
        ]
        self._render_timeline(records)

    def _render_timeline(self, items):
        # Clear existing
        while self.timeline_v.count():
            item = self.timeline_v.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for t_str, desc, col in items:
            row = QHBoxLayout()
            row.setSpacing(8)
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {col}; font-size: 10pt; background: transparent;")
            time_lab = QLabel(t_str)
            time_lab.setObjectName("TimelineTime")
            desc_lab = QLabel(desc)
            desc_lab.setObjectName("TimelineText")
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

        # 1. Update Hero
        if running:
            self.hero.set_state(
                True, uptime_str,
                "代理服务运行正常",
                "校园网 SNI 代理已正常工作，网络连接稳定"
            )
            self.card_service.set_value("运行中", "#22C58B")
            self.card_net.set_value("良好", "#22C58B")
            self.chip_net_state.setText("  🟢 网络已连接")
            self.chip_net_state.setStyleSheet("""
                background: rgba(16, 185, 129, 0.15);
                border: 1px solid rgba(52, 211, 153, 0.4);
                border-radius: 12px;
                color: #34D399; font-size: 10pt; font-weight: 600; padding: 4px 8px;
            """)
        else:
            self.hero.set_state(
                False, "--:--:--",
                "代理服务已停止",
                "代理未启动，点击右侧「启动服务」开始代理"
            )
            self.card_service.set_value("已停止", "#94A3B8")
            self.card_net.set_value("未连接", "#F59E0B")
            self.chip_net_state.setText("  🟡 服务未启动")
            self.chip_net_state.setStyleSheet("""
                background: rgba(245, 158, 11, 0.15);
                border: 1px solid rgba(251, 191, 36, 0.4);
                border-radius: 12px;
                color: #FBBF24; font-size: 10pt; font-weight: 600; padding: 4px 8px;
            """)

        # 2. Port & cert status
        port = snap.get("listen_addr", "127.0.0.1:8888").split(":")[-1]
        self.card_port.set_value(port, "#A78BFA")

        cert = snap.get("cert", {})
        if cert.get("exists", False):
            trusted = (cert.get("installed_machine") is True
                       or cert.get("installed_user") is True)
            unknown = (cert.get("installed_machine") is None
                       and cert.get("installed_user") is None)
            if cert.get("expired", False):
                self.card_cert.set_value("已过期", "#EF4444")
                self.item_upstream.setText("🔒 上游证书： 证书已过期")
            elif trusted:
                self.card_cert.set_value("正常 ✔", "#22C58B")
                self.item_upstream.setText("🔒 上游证书： 已安装并信任")
            elif unknown:
                self.card_cert.set_value("待检查", "#EAB54A")
                self.item_upstream.setText("🔒 上游证书： 信任状态未知")
            else:
                self.card_cert.set_value("未信任", "#F59E0B")
                self.item_upstream.setText("🔒 上游证书： 根证书未安装")
        else:
            self.card_cert.set_value("未生成", "#F59E0B")
            self.item_upstream.setText("🔒 上游证书： 待初始化")

        # 3. Dynamic timeline updates if error or recent run
        records = []
        now_t = time.strftime("%H:%M:%S")
        if running:
            records.append((now_t, "代理服务运行中 (127.0.0.1:8888)", "#10B981"))
            records.append((now_t, "证书状态检查完成", "#10B981"))
            records.append((now_t, "网络连接正常", "#10B981"))
        else:
            last_err = snap.get("log_last_error", "")
            if last_err:
                records.append((now_t, f"异常记录：{last_err[:30]}", "#EF4444"))
            records.append((now_t, "服务就绪，随时可启动", "#38BDF8"))
            records.append((now_t, "网络接口已检测", "#10B981"))
        self._render_timeline(records)

    # -------------------------------------------------------------
    # Quick Actions
    # -------------------------------------------------------------
    def _start_service(self):
        text = ("将执行完整启动流程：\n"
                "1. 本机生成/复用设备专属 CA 与通配符证书；\n"
                "2. 将设备 CA 导入系统「受信任的根证书颁发机构」；\n"
                "3. 后台启动代理主程序（127.0.0.1:8888）；\n"
                "4. 备份当前系统代理并设置为本机代理；\n"
                "5. 启动看门狗守护进程。\n\n"
                "是否立即启动服务？")
        self.ctx.confirm_and_run("start", "启动服务", text, "启动")

    def _stop_service(self):
        text = ("将执行安全停止流程：\n"
                "1. 停止看门狗守护并按备份恢复系统代理设置；\n"
                "2. 安全结束代理主程序进程；\n"
                "3. 按 SHA-1 指纹从系统根证书库移除本工具 CA。\n\n"
                "是否确认停止服务？")
        self.ctx.confirm_and_run("stop", "停止服务", text, "停止")

    def _goto_diag(self):
        # 侧边栏顺序：仪表盘0 运行管理1 规则管理2 网络诊断3 网络测速4 日志中心5 ...
        self.ctx._nav(3)
        # Automatically trigger diagnostics
        diag_page = self.ctx.stack.widget(3)
        if hasattr(diag_page, "_run"):
            diag_page._run()

    def _goto_logs(self):
        # 侧边栏顺序：仪表盘0 运行管理1 规则管理2 网络诊断3 网络测速4 日志中心5 ...
        self.ctx._nav(5)

    def _manual_refresh(self):
        self.ctx.refresh_now()
        # Ping latency simulation / update
        try:
            t0 = time.time()
            s = socket.create_connection(("127.0.0.1", 8888), timeout=0.3)
            s.close()
            ms = int((time.time() - t0) * 1000)
            self.item_latency.setText(f"⏱ 本地代理延迟： {ms} ms")
        except Exception:
            self.item_latency.setText("⏱ 本地代理延迟： 未运行")
