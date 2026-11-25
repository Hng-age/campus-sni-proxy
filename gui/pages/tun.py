"""TUN/VPN 虚拟网卡代理页：支持多线路保存/编辑/测速/切换、规则与全局模式及自定义分流规则。"""

import copy

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QFrame, QGridLayout,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea, QSizePolicy, QSpinBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from gui.components.glass_panel import GlassPanel
from gui.pages.rules import TabPillButton
from gui.workers import FuncWorker
from services import tun_service
from .base import Page

RULE_PLACEHOLDERS = {
    "DOMAIN-SUFFIX": "域名后缀，如 douyin.com 或 edu.cn",
    "DOMAIN": "完整域名，如 api.example.com",
    "DOMAIN-KEYWORD": "域名关键字，如 bilibili",
    "IP-CIDR": "IP 网段，如 192.168.1.0/24 或 10.0.0.0/8",
    "DST-PORT": "目标端口，如 443 或 8080",
    "PROCESS-NAME": "进程名，如 WeChat.exe 或 Telegram.exe",
}


class ProfileEditorDialog(QDialog):
    """添加 / 编辑代理线路对话框：支持保存前先行测试连通性与账号认证。"""

    def __init__(self, profile=None, parent=None):
        super().__init__(parent)
        self._profile = copy.deepcopy(profile) if profile else {}
        self._is_edit = bool(self._profile.get("id"))
        self._testing = False
        self._workers = []
        self._last_test = None

        self.setWindowTitle("编辑代理线路" if self._is_edit else "添加代理线路")
        self.setMinimumWidth(440)
        self.setModal(True)

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(12)

        title = QLabel("编辑代理线路" if self._is_edit else "添加新代理线路")
        title.setObjectName("TitleLabel")
        v.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        grid.addWidget(QLabel("线路名称"), 0, 0)
        self.inp_name = QLineEdit()
        self.inp_name.setPlaceholderText("例如：宿舍台式机 SOCKS5")
        grid.addWidget(self.inp_name, 0, 1)

        grid.addWidget(QLabel("代理协议"), 1, 0)
        self.cmb_proto = QComboBox()
        self.cmb_proto.addItem("SOCKS5（支持 UDP，推荐）", "socks5")
        self.cmb_proto.addItem("HTTP / HTTPS 代理", "http")
        self.cmb_proto.currentIndexChanged.connect(self._on_proto_changed)
        grid.addWidget(self.cmb_proto, 1, 1)

        grid.addWidget(QLabel("服务器 IP / 域名"), 2, 0)
        self.inp_server = QLineEdit()
        self.inp_server.setPlaceholderText("例如：192.168.1.10")
        grid.addWidget(self.inp_server, 2, 1)

        grid.addWidget(QLabel("端口"), 3, 0)
        self.spn_port = QSpinBox()
        self.spn_port.setRange(1, 65535)
        self.spn_port.setValue(18081)
        grid.addWidget(self.spn_port, 3, 1)

        grid.addWidget(QLabel("用户名（可选）"), 4, 0)
        self.inp_user = QLineEdit()
        self.inp_user.setPlaceholderText("无认证可留空（如 user）")
        grid.addWidget(self.inp_user, 4, 1)

        grid.addWidget(QLabel("密码（可选）"), 5, 0)
        pw_row = QHBoxLayout()
        pw_row.setSpacing(6)
        self.inp_pass = QLineEdit()
        self.inp_pass.setEchoMode(QLineEdit.Password)
        self.inp_pass.setPlaceholderText("无认证可留空")
        self.btn_eye = QPushButton("👁")
        self.btn_eye.setCheckable(True)
        self.btn_eye.setFixedSize(34, 28)
        self.btn_eye.setCursor(Qt.PointingHandCursor)
        self.btn_eye.toggled.connect(
            lambda ck: self.inp_pass.setEchoMode(QLineEdit.Normal if ck else QLineEdit.Password)
        )
        pw_row.addWidget(self.inp_pass, 1)
        pw_row.addWidget(self.btn_eye)
        grid.addLayout(pw_row, 5, 1)

        self.chk_udp = QCheckBox("开启 UDP 转发（仅 SOCKS5 支持，游戏/语音/QUIC 需要）")
        self.chk_udp.setChecked(True)
        grid.addWidget(self.chk_udp, 6, 0, 1, 2)

        grid.setColumnStretch(1, 1)
        v.addLayout(grid)

        self.lbl_test = QLabel("保存前可点击「测试是否可用」验证连通性与账号密码。")
        self.lbl_test.setObjectName("MutedLabel")
        self.lbl_test.setWordWrap(True)
        v.addWidget(self.lbl_test)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_test = QPushButton("🔍 测试是否可用")
        self.btn_test.setCursor(Qt.PointingHandCursor)
        self.btn_test.clicked.connect(self._test_line)

        btn_cancel = QPushButton("取消")
        btn_cancel.setCursor(Qt.PointingHandCursor)
        btn_cancel.clicked.connect(self.reject)

        self.btn_save = QPushButton("💾 保存线路")
        self.btn_save.setObjectName("Primary")
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.clicked.connect(self._save)

        btn_row.addWidget(self.btn_test)
        btn_row.addStretch(1)
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(self.btn_save)
        v.addLayout(btn_row)

        if self._profile:
            self.inp_name.setText(self._profile.get("name", ""))
            idx_p = self.cmb_proto.findData(self._profile.get("protocol", "socks5"))
            if idx_p >= 0:
                self.cmb_proto.setCurrentIndex(idx_p)
            self.inp_server.setText(self._profile.get("server", ""))
            self.spn_port.setValue(int(self._profile.get("port", 18081)))
            self.inp_user.setText(self._profile.get("username", ""))
            self.inp_pass.setText(self._profile.get("password", ""))
            self.chk_udp.setChecked(bool(self._profile.get("udp", True)))
        self._sync_udp_state()

    def _on_proto_changed(self):
        proto = self.cmb_proto.currentData()
        cur = self.spn_port.value()
        if proto == "http" and cur == 18081:
            self.spn_port.setValue(18080)
        elif proto == "socks5" and cur == 18080:
            self.spn_port.setValue(18081)
        self._sync_udp_state()

    def _sync_udp_state(self):
        self.chk_udp.setEnabled(self.cmb_proto.currentData() == "socks5")

    def profile_data(self):
        srv = self.inp_server.text().strip()
        prt = int(self.spn_port.value())
        proto = self.cmb_proto.currentData() or "socks5"
        name = self.inp_name.text().strip() or f"{proto.upper()} · {srv}:{prt}"
        data = {
            "id": self._profile.get("id", ""),
            "name": name,
            "protocol": proto,
            "server": srv,
            "port": prt,
            "username": self.inp_user.text(),
            "password": self.inp_pass.text(),
            "udp": self.chk_udp.isChecked(),
        }
        if self._last_test is not None:
            if self._last_test.get("ok"):
                ms = self._last_test.get("latency_ms")
                data["last_status"] = f"✅ {ms} ms" if ms is not None else "✅ 可用"
                data["last_latency_ms"] = ms
            else:
                msg = self._last_test.get("message") or "不可用"
                data["last_status"] = f"❌ {msg[:24]}"
                data["last_latency_ms"] = None
        return data

    def _test_line(self):
        if self._testing:
            return
        d = self.profile_data()
        if not d["server"]:
            QMessageBox.warning(self, "提示", "请先填写服务器 IP 地址。")
            return
        self._testing = True
        self.btn_test.setEnabled(False)
        self.lbl_test.setText(f"⏳ 正在测试 {d['server']}:{d['port']}...")
        self.lbl_test.setStyleSheet("color: #3B82F6;")

        w = FuncWorker(lambda _p: tun_service.test_upstream_proxy(d), parent=self)
        self._workers.append(w)

        def _done(res, err):
            try:
                self._workers.remove(w)
            except ValueError:
                pass
            w.deleteLater()
            self._testing = False
            self.btn_test.setEnabled(True)
            if err or not res:
                self._last_test = {"ok": False, "message": str(err or "测试失败")}
                self.lbl_test.setText(f"❌ 测试异常：{err or '未知错误'}")
                self.lbl_test.setStyleSheet("color: #EF4444;")
                return
            self._last_test = res
            if res.get("ok"):
                self.lbl_test.setText(f"✅ {res['message']}")
                self.lbl_test.setStyleSheet("color: #10B981;")
            else:
                self.lbl_test.setText(f"❌ {res['message']}")
                self.lbl_test.setStyleSheet("color: #EF4444;")

        w.done.connect(_done)
        w.start()

    def _save(self):
        if not self.inp_server.text().strip():
            QMessageBox.warning(self, "提示", "服务器 IP 地址或域名不能为空。")
            return
        self.accept()


class TunPage(Page):
    """TUN/VPN 共享代理页面：多线路管理、使用前测试、规则/全局切换与分流规则编辑器。"""

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self._pal = {}
        self._cfg = tun_service.load_tun_config()
        self._rules = copy.deepcopy(self._cfg.get("rules", []))
        self._status = {}
        self._busy = False
        self._testing_ids = set()
        self._workers = []
        self._poll_pending = False

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
        body_v.setContentsMargins(18, 14, 18, 14)
        body_v.setSpacing(12)
        scroll.setWidget(body)
        body.setAutoFillBackground(False)
        scroll.viewport().setAutoFillBackground(False)
        outer.addWidget(scroll)
        self._scroll = scroll
        self._body = body

        # -------------------------------------------------------------
        # 1. 页面标题与内核状态徽章
        # -------------------------------------------------------------
        head_row = QHBoxLayout()
        head_row.setSpacing(10)
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("TUN / VPN 虚拟网卡代理")
        title.setObjectName("TitleLabel")
        sub = QLabel("保存多条共享代理线路，支持使用前测速、编辑修改与规则/全局模式切换")
        sub.setObjectName("MutedLabel")
        sub.setWordWrap(True)
        sub.setMinimumWidth(0)
        title_col.addWidget(title)
        title_col.addWidget(sub)
        head_row.addLayout(title_col, 1)

        self.lbl_core_badge = QLabel("内核检测中...")
        self.lbl_core_badge.setObjectName("TitleChip")
        head_row.addWidget(self.lbl_core_badge, 0, Qt.AlignTop)
        body_v.addLayout(head_row)

        # -------------------------------------------------------------
        # 2. 状态总控栏 + 规则/全局模式实时切换
        # -------------------------------------------------------------
        self.panel_ctrl = GlassPanel("TUN 运行控制与模式切换")
        ctrl_v = QVBoxLayout()
        ctrl_v.setSpacing(10)

        top_ctrl = QHBoxLayout()
        top_ctrl.setSpacing(10)

        self.lbl_run_state = QLabel("⚪ TUN 未启动")
        self.lbl_run_state.setStyleSheet("font-size: 11pt; font-weight: 700;")
        top_ctrl.addWidget(self.lbl_run_state)
        top_ctrl.addStretch(1)

        self.btn_start_tun = QPushButton("🚀 启动 TUN")
        self.btn_start_tun.setObjectName("Primary")
        self.btn_start_tun.setFixedHeight(34)
        self.btn_start_tun.setCursor(Qt.PointingHandCursor)
        self.btn_start_tun.setToolTip("创建虚拟网卡并接管系统网络（仅启停 TUN 时需要 UAC）")
        self.btn_start_tun.clicked.connect(self._start_tun)

        self.btn_stop_tun = QPushButton("■ 停止 TUN")
        self.btn_stop_tun.setObjectName("Danger")
        self.btn_stop_tun.setFixedHeight(34)
        self.btn_stop_tun.setCursor(Qt.PointingHandCursor)
        self.btn_stop_tun.clicked.connect(self._stop_tun)

        top_ctrl.addWidget(self.btn_start_tun)
        top_ctrl.addWidget(self.btn_stop_tun)
        ctrl_v.addLayout(top_ctrl)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        lbl_m = QLabel("代理模式:")
        lbl_m.setObjectName("MutedLabel")
        mode_row.addWidget(lbl_m)

        self.btn_mode_rule = QPushButton("📋 规则代理")
        self.btn_mode_rule.setCheckable(True)
        self.btn_mode_rule.setCursor(Qt.PointingHandCursor)
        self.btn_mode_rule.setFixedHeight(30)
        self.btn_mode_rule.setToolTip("规则代理 (Rule)：按分流规则决定哪些流量走代理、哪些直连")
        self.btn_mode_rule.clicked.connect(lambda: self._switch_mode("rule"))

        self.btn_mode_global = QPushButton("🌐 全局代理")
        self.btn_mode_global.setCheckable(True)
        self.btn_mode_global.setCursor(Qt.PointingHandCursor)
        self.btn_mode_global.setFixedHeight(30)
        self.btn_mode_global.setToolTip("全局代理 (Global)：所有非局域网流量全部经由上级代理转发")
        self.btn_mode_global.clicked.connect(lambda: self._switch_mode("global"))

        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_group.addButton(self.btn_mode_rule, 0)
        self.mode_group.addButton(self.btn_mode_global, 1)

        mode_row.addWidget(self.btn_mode_rule)
        mode_row.addWidget(self.btn_mode_global)
        mode_row.addStretch(1)
        ctrl_v.addLayout(mode_row)

        self.lbl_live_stats = QLabel("当前线路: 未选择  |  活动连接: 0  |  ↑ 0 B  ↓ 0 B")
        self.lbl_live_stats.setObjectName("MutedLabel")
        self.lbl_live_stats.setWordWrap(True)
        self.lbl_live_stats.setMinimumWidth(0)
        ctrl_v.addWidget(self.lbl_live_stats)

        self.panel_ctrl.add_layout(ctrl_v)
        body_v.addWidget(self.panel_ctrl)

        # -------------------------------------------------------------
        # 3. 子页面切换栏
        # -------------------------------------------------------------
        self.tab_nav_frame = QFrame()
        self.tab_nav_frame.setObjectName("StatusCard")
        tab_lay = QHBoxLayout(self.tab_nav_frame)
        tab_lay.setContentsMargins(6, 6, 6, 6)
        tab_lay.setSpacing(6)

        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        self.btn_tab_cfg = TabPillButton("线路与配置", "⚙")
        self.btn_tab_rules = TabPillButton("分流规则", "📜")
        self.btn_tab_conns = TabPillButton("实时连接与日志", "📡")

        for idx, b in enumerate((self.btn_tab_cfg, self.btn_tab_rules, self.btn_tab_conns)):
            self.tab_group.addButton(b, idx)
            tab_lay.addWidget(b, 1)
            b.clicked.connect(lambda _=False, i=idx: self._switch_tab(i))

        body_v.addWidget(self.tab_nav_frame)

        # -------------------------------------------------------------
        # 4. 三个子面板
        # -------------------------------------------------------------
        self.box_cfg = self._build_lines_and_config_card()
        self.box_rules = self._build_rules_card()
        self.box_conns = self._build_conns_card()

        body_v.addWidget(self.box_cfg)
        body_v.addWidget(self.box_rules)
        body_v.addWidget(self.box_conns)

        self.btn_tab_cfg.setChecked(True)
        self._switch_tab(0)

        self._load_config_to_ui(self._cfg)

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(2500)
        self.poll_timer.timeout.connect(self._poll_status)

    # -------------------------------------------------------------
    # 子视图 1：已保存代理线路列表 + 网络选项
    # -------------------------------------------------------------
    def _build_lines_and_config_card(self):
        wrap = QWidget()
        wrap.setAttribute(Qt.WA_StyledBackground, False)
        wv = QVBoxLayout(wrap)
        wv.setContentsMargins(0, 0, 0, 0)
        wv.setSpacing(12)

        # 1. 已保存代理线路卡
        panel_lines = GlassPanel("已保存代理线路（点击「测试」验证可用性，点击「选用」切换线路）")
        lv = QVBoxLayout()
        lv.setSpacing(10)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.lbl_active_line = QLabel("当前使用：未选择")
        self.lbl_active_line.setWordWrap(True)
        self.lbl_active_line.setMinimumWidth(0)
        bar.addWidget(self.lbl_active_line, 1)

        self.btn_test_all = QPushButton("🔍 全部测速")
        self.btn_test_all.setCursor(Qt.PointingHandCursor)
        self.btn_test_all.setToolTip("依次测试所有已保存线路的连通性与账号认证")
        self.btn_test_all.clicked.connect(self._test_all_profiles)
        bar.addWidget(self.btn_test_all)

        self.btn_add_profile = QPushButton("➕ 添加线路")
        self.btn_add_profile.setObjectName("Primary")
        self.btn_add_profile.setCursor(Qt.PointingHandCursor)
        self.btn_add_profile.clicked.connect(self._add_profile_dialog)
        bar.addWidget(self.btn_add_profile)
        lv.addLayout(bar)

        self.table_profiles = QTableWidget()
        self.table_profiles.setColumnCount(5)
        self.table_profiles.setHorizontalHeaderLabels(["线路名称", "地址与协议", "认证", "测试状态", "操作"])
        hdr = self.table_profiles.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hdr.setMinimumSectionSize(36)
        self.table_profiles.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table_profiles.verticalHeader().setVisible(False)
        self.table_profiles.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_profiles.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_profiles.setMinimumWidth(0)
        self.table_profiles.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.table_profiles.setMinimumHeight(185)
        self.table_profiles.setAlternatingRowColors(True)
        lv.addWidget(self.table_profiles)

        self.lbl_test_result = QLabel("提示：点击「➕ 添加线路」保存 IP、端口与账号密码；可先点击对应行的「测试」再「选用」。")
        self.lbl_test_result.setObjectName("MutedLabel")
        self.lbl_test_result.setWordWrap(True)
        self.lbl_test_result.setMinimumWidth(0)
        lv.addWidget(self.lbl_test_result)

        panel_lines.add_layout(lv)
        wv.addWidget(panel_lines)

        # 2. TUN 网络选项卡
        panel_net = GlassPanel("TUN 网络接管选项")
        nv = QVBoxLayout()
        nv.setSpacing(10)

        stack_row = QHBoxLayout()
        stack_row.setSpacing(10)
        stack_row.addWidget(QLabel("TUN 协议栈:"))
        self.cmb_stack = QComboBox()
        self.cmb_stack.setMinimumWidth(0)
        self.cmb_stack.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_stack.addItem("gVisor（兼容稳定，推荐）", "gvisor")
        self.cmb_stack.addItem("Mixed（TCP+UDP 混合）", "mixed")
        self.cmb_stack.addItem("System（系统栈）", "system")
        stack_row.addWidget(self.cmb_stack, 1)

        self.btn_save_cfg = QPushButton("💾 保存网络选项")
        self.btn_save_cfg.setCursor(Qt.PointingHandCursor)
        self.btn_save_cfg.clicked.connect(self._save_and_reload)
        stack_row.addWidget(self.btn_save_cfg)
        nv.addLayout(stack_row)

        opts = QGridLayout()
        opts.setHorizontalSpacing(14)
        opts.setVerticalSpacing(6)
        self.chk_bypass_lan = QCheckBox("绕过局域网与私有网段")
        self.chk_bypass_lan.setToolTip("自动直连 192.168.0.0/16、10.0.0.0/8、172.16.0.0/12 与代理服务器 IP，防止回环")
        self.chk_fake_ip = QCheckBox("启用 Fake-IP DNS 劫持")
        self.chk_fake_ip.setToolTip("使用 198.18.0.1/16 虚拟 DNS，确保微信、抖音、游戏等自建网络栈 App 全接管")
        self.chk_sys_proxy = QCheckBox("同步接管系统代理 (17897)")
        self.chk_sys_proxy.setToolTip("启动 TUN 时同步把 Windows 系统代理指向 127.0.0.1:17897，浏览器与 App 统一走分流规则")
        self.chk_fallback_direct = QCheckBox("代理掉线自动恢复直连（推荐）")
        self.chk_fallback_direct.setToolTip("当上级共享代理断开或不可达时，自动切回本机直连（规则与全局模式均生效），恢复后自动切回代理")

        for c in (self.chk_bypass_lan, self.chk_fake_ip, self.chk_sys_proxy, self.chk_fallback_direct):
            c.setMinimumWidth(0)
        opts.addWidget(self.chk_bypass_lan, 0, 0)
        opts.addWidget(self.chk_fake_ip, 0, 1)
        opts.addWidget(self.chk_sys_proxy, 1, 0)
        opts.addWidget(self.chk_fallback_direct, 1, 1)
        nv.addLayout(opts)

        panel_net.add_layout(nv)
        wv.addWidget(panel_net)
        return wrap

    # -------------------------------------------------------------
    # 子视图 2：分流规则配置
    # -------------------------------------------------------------
    def _build_rules_card(self):
        panel = GlassPanel("分流规则设置（仅「规则代理」模式生效，按从上到下顺序匹配）")
        v = QVBoxLayout()
        v.setSpacing(10)

        preset_row = QHBoxLayout()
        preset_row.setSpacing(8)
        preset_row.addWidget(QLabel("快速预设:"))
        self.cmb_preset = QComboBox()
        for key, info in tun_service.RULE_PRESETS.items():
            self.cmb_preset.addItem(info["label"], key)
        self.cmb_preset.setMinimumWidth(0)
        preset_row.addWidget(self.cmb_preset, 1)

        self.btn_apply_preset = QPushButton("应用预设")
        self.btn_apply_preset.setCursor(Qt.PointingHandCursor)
        self.btn_apply_preset.clicked.connect(self._apply_preset)
        preset_row.addWidget(self.btn_apply_preset)
        v.addLayout(preset_row)

        final_row = QHBoxLayout()
        final_row.setSpacing(8)
        final_row.addWidget(QLabel("未命中规则默认动作 (MATCH):"))
        self.cmb_final = QComboBox()
        self.cmb_final.setMinimumWidth(0)
        self.cmb_final.addItem("PROXY（其余流量全部走共享代理）", "PROXY")
        self.cmb_final.addItem("DIRECT（其余流量全部直连）", "DIRECT")
        final_row.addWidget(self.cmb_final, 1)
        v.addLayout(final_row)

        self.lbl_fallback_rule = QLabel("")
        self.lbl_fallback_rule.setObjectName("MutedLabel")
        self.lbl_fallback_rule.setWordWrap(True)
        self.lbl_fallback_rule.setMinimumWidth(0)
        v.addWidget(self.lbl_fallback_rule)

        add_box = QFrame()
        add_box.setObjectName("StatusCard")
        ab_v = QVBoxLayout(add_box)
        ab_v.setContentsMargins(10, 8, 10, 8)
        ab_v.setSpacing(8)

        row_a = QHBoxLayout()
        row_a.setSpacing(8)
        self.cmb_rule_type = QComboBox()
        for rt in tun_service.RULE_TYPES:
            self.cmb_rule_type.addItem(rt, rt)
        self.cmb_rule_type.currentTextChanged.connect(self._update_rule_placeholder)
        row_a.addWidget(self.cmb_rule_type)

        self.inp_rule_val = QLineEdit()
        self.inp_rule_val.setMinimumWidth(0)
        self.inp_rule_val.returnPressed.connect(self._add_rule)
        row_a.addWidget(self.inp_rule_val, 1)
        ab_v.addLayout(row_a)

        row_b = QHBoxLayout()
        row_b.setSpacing(8)
        self.cmb_rule_policy = QComboBox()
        self.cmb_rule_policy.addItem("PROXY（走代理）", "PROXY")
        self.cmb_rule_policy.addItem("DIRECT（直连）", "DIRECT")
        self.cmb_rule_policy.addItem("REJECT（拦截）", "REJECT")
        row_b.addWidget(self.cmb_rule_policy)

        self.inp_rule_note = QLineEdit()
        self.inp_rule_note.setPlaceholderText("备注（可选，例如：学校教务网）")
        self.inp_rule_note.setMinimumWidth(0)
        self.inp_rule_note.returnPressed.connect(self._add_rule)
        row_b.addWidget(self.inp_rule_note, 1)

        self.btn_add_rule = QPushButton("➕ 添加规则")
        self.btn_add_rule.setObjectName("Primary")
        self.btn_add_rule.setCursor(Qt.PointingHandCursor)
        self.btn_add_rule.clicked.connect(self._add_rule)
        row_b.addWidget(self.btn_add_rule)
        ab_v.addLayout(row_b)

        v.addWidget(add_box)
        self._update_rule_placeholder(self.cmb_rule_type.currentText())

        self.table_rules = QTableWidget()
        self.table_rules.setColumnCount(6)
        self.table_rules.setHorizontalHeaderLabels(["启用", "规则类型", "匹配值", "动作", "备注", "操作"])
        hdr = self.table_rules.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.Stretch)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        hdr.setMinimumSectionSize(36)
        self.table_rules.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table_rules.verticalHeader().setVisible(False)
        self.table_rules.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_rules.setMinimumWidth(0)
        self.table_rules.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.table_rules.setMinimumHeight(210)
        self.table_rules.setAlternatingRowColors(True)
        v.addWidget(self.table_rules)

        bot_row = QHBoxLayout()
        self.lbl_rules_count = QLabel("共 0 条自定义规则")
        self.lbl_rules_count.setObjectName("MutedLabel")
        bot_row.addWidget(self.lbl_rules_count)
        bot_row.addStretch(1)

        self.btn_save_rules = QPushButton("💾 保存并热重载规则")
        self.btn_save_rules.setObjectName("Primary")
        self.btn_save_rules.setCursor(Qt.PointingHandCursor)
        self.btn_save_rules.clicked.connect(self._save_and_reload)
        bot_row.addWidget(self.btn_save_rules)
        v.addLayout(bot_row)

        panel.add_layout(v)
        return panel

    # -------------------------------------------------------------
    # 子视图 3：实时连接与运行日志
    # -------------------------------------------------------------
    def _build_conns_card(self):
        panel = GlassPanel("TUN 实时连接与内核日志")
        v = QVBoxLayout()
        v.setSpacing(10)

        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)
        self.inp_conn_filter = QLineEdit()
        self.inp_conn_filter.setPlaceholderText("🔍 按进程名 / 域名 / 规则过滤...")
        self.inp_conn_filter.setMinimumWidth(0)
        self.inp_conn_filter.textChanged.connect(self._render_connections)
        top_bar.addWidget(self.inp_conn_filter, 1)

        self.btn_refresh_conns = QPushButton("🔄 刷新")
        self.btn_refresh_conns.setCursor(Qt.PointingHandCursor)
        self.btn_refresh_conns.clicked.connect(self._poll_status)
        top_bar.addWidget(self.btn_refresh_conns)

        self.btn_close_conns = QPushButton("✂ 断开全部连接")
        self.btn_close_conns.setCursor(Qt.PointingHandCursor)
        self.btn_close_conns.clicked.connect(self._close_all_conns)
        top_bar.addWidget(self.btn_close_conns)
        v.addLayout(top_bar)

        self.table_conns = QTableWidget()
        self.table_conns.setColumnCount(5)
        self.table_conns.setHorizontalHeaderLabels(["进程", "目标地址", "命中规则", "出口链路", "流量"])
        hdr = self.table_conns.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(1, QHeaderView.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hdr.setMinimumSectionSize(36)
        self.table_conns.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table_conns.verticalHeader().setVisible(False)
        self.table_conns.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_conns.setMinimumWidth(0)
        self.table_conns.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.table_conns.setMinimumHeight(190)
        self.table_conns.setAlternatingRowColors(True)
        v.addWidget(self.table_conns)

        log_lbl = QLabel("内核输出日志 (logs/tun.log)：")
        log_lbl.setObjectName("MutedLabel")
        v.addWidget(log_lbl)

        self.txt_tun_log = QPlainTextEdit()
        self.txt_tun_log.setReadOnly(True)
        self.txt_tun_log.setFixedHeight(130)
        v.addWidget(self.txt_tun_log)

        panel.add_layout(v)
        return panel

    # -------------------------------------------------------------
    # 数据同步与线路列表渲染
    # -------------------------------------------------------------
    def _switch_tab(self, idx):
        self.box_cfg.setVisible(idx == 0)
        self.box_rules.setVisible(idx == 1)
        self.box_conns.setVisible(idx == 2)
        if idx == 2:
            self._poll_status()

    def _update_rule_placeholder(self, rtype):
        self.inp_rule_val.setPlaceholderText(RULE_PLACEHOLDERS.get(rtype, "输入匹配值"))

    def _active_profile(self):
        aid = self._cfg.get("active_profile_id", "")
        for p in self._cfg.get("profiles") or []:
            if p.get("id") == aid:
                return p
        return None

    def _load_config_to_ui(self, cfg):
        self._cfg = cfg
        idx_s = self.cmb_stack.findData(cfg.get("stack", "gvisor"))
        if idx_s >= 0:
            self.cmb_stack.setCurrentIndex(idx_s)

        self.chk_bypass_lan.setChecked(bool(cfg.get("bypass_lan", True)))
        self.chk_fake_ip.setChecked(bool(cfg.get("fake_ip", True)))
        self.chk_sys_proxy.setChecked(bool(cfg.get("also_set_sys_proxy", True)))
        fb_on = bool(cfg.get("fallback_to_direct", True))
        self.chk_fallback_direct.setChecked(fb_on)
        self._update_fallback_banner(fb_on, int(cfg.get("fallback_interval", 10)))

        idx_f = self.cmb_final.findData(cfg.get("final_policy", "PROXY"))
        if idx_f >= 0:
            self.cmb_final.setCurrentIndex(idx_f)

        mode = cfg.get("mode", "rule")
        self.btn_mode_global.setChecked(mode == "global")
        self.btn_mode_rule.setChecked(mode != "global")

        self._rules = copy.deepcopy(cfg.get("rules", []))
        self._render_profiles_table()
        self._render_rules_table()

    def _update_fallback_banner(self, enabled, interval=10):
        if enabled:
            self.lbl_fallback_rule.setText(
                f"保底规则：✅ 已开启「代理掉线自动恢复直连」（每 {interval} 秒检测一次，代理断开自动切为 DIRECT 直连）"
            )
            self.lbl_fallback_rule.setStyleSheet("color: #10B981;")
        else:
            self.lbl_fallback_rule.setText(
                "保底规则：⚪ 未开启「代理掉线自动恢复直连」（可在「线路与配置」选项卡勾选开启）"
            )
            self.lbl_fallback_rule.setStyleSheet("")

    def _collect_ui_config(self):
        cfg = copy.deepcopy(self._cfg)
        cfg["stack"] = self.cmb_stack.currentData() or "gvisor"
        cfg["bypass_lan"] = self.chk_bypass_lan.isChecked()
        cfg["fake_ip"] = self.chk_fake_ip.isChecked()
        cfg["also_set_sys_proxy"] = self.chk_sys_proxy.isChecked()
        cfg["fallback_to_direct"] = self.chk_fallback_direct.isChecked()
        cfg["final_policy"] = self.cmb_final.currentData() or "PROXY"
        cfg["mode"] = "global" if self.btn_mode_global.isChecked() else "rule"
        cfg["rules"] = copy.deepcopy(self._rules)
        return cfg

    def _render_profiles_table(self):
        profiles = self._cfg.get("profiles") or []
        active_id = self._cfg.get("active_profile_id", "")
        active_prof = self._active_profile()

        if active_prof:
            self.lbl_active_line.setText(
                f"当前使用：{active_prof['name']}（{active_prof['protocol'].upper()} · "
                f"{active_prof['server']}:{active_prof['port']}）"
            )
        else:
            self.lbl_active_line.setText("当前使用：未添加线路（请点击右侧「➕ 添加线路」）")

        self.table_profiles.setRowCount(len(profiles))
        for row, prof in enumerate(profiles):
            pid = prof["id"]
            is_active = pid == active_id

            name_txt = f"{'★ ' if is_active else ''}{prof['name']}"
            self.table_profiles.setItem(row, 0, QTableWidgetItem(name_txt))
            addr_txt = f"{prof['protocol'].upper()} · {prof['server']}:{prof['port']}"
            self.table_profiles.setItem(row, 1, QTableWidgetItem(addr_txt))
            auth_txt = prof["username"] if prof.get("username") else "无认证"
            self.table_profiles.setItem(row, 2, QTableWidgetItem(auth_txt))

            if pid in self._testing_ids:
                st_txt = "⏳ 测试中..."
            else:
                st_txt = prof.get("last_status") or "未测试"
            self.table_profiles.setItem(row, 3, QTableWidgetItem(st_txt))

            op_w = QWidget()
            op_l = QHBoxLayout(op_w)
            op_l.setContentsMargins(2, 2, 2, 2)
            op_l.setSpacing(4)

            btn_use = QPushButton("使用中" if is_active else "选用")
            btn_use.setEnabled(not is_active)
            if is_active:
                btn_use.setObjectName("Primary")
            btn_use.setFixedHeight(22)
            btn_use.setCursor(Qt.PointingHandCursor)
            btn_use.clicked.connect(lambda _=False, p_id=pid: self._select_profile(p_id))

            btn_test = QPushButton("测试")
            btn_test.setFixedHeight(22)
            btn_test.setEnabled(pid not in self._testing_ids)
            btn_test.setCursor(Qt.PointingHandCursor)
            btn_test.clicked.connect(lambda _=False, p_id=pid: self._test_profile(p_id))

            btn_edit = QPushButton("编辑")
            btn_edit.setFixedHeight(22)
            btn_edit.setCursor(Qt.PointingHandCursor)
            btn_edit.clicked.connect(lambda _=False, p_id=pid: self._edit_profile_dialog(p_id))

            btn_del = QPushButton("删")
            btn_del.setFixedHeight(22)
            btn_del.setCursor(Qt.PointingHandCursor)
            btn_del.clicked.connect(lambda _=False, p_id=pid: self._delete_profile(p_id))

            for b in (btn_use, btn_test, btn_edit, btn_del):
                b.setStyleSheet("padding: 0 7px; font-size: 8.5pt; border-radius: 5px;")
                op_l.addWidget(b)
            self.table_profiles.setCellWidget(row, 4, op_w)

    # -------------------------------------------------------------
    # 线路管理操作（添加 / 编辑 / 测试 / 选用 / 删除）
    # -------------------------------------------------------------
    def _add_profile_dialog(self):
        dlg = ProfileEditorDialog(parent=self)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.profile_data()
            cfg = self._collect_ui_config()
            updated, saved = tun_service.upsert_profile(cfg, data, activate=False)
            self._load_config_to_ui(updated)
            self.lbl_test_result.setText(f"✅ 已保存新线路「{saved['name']}」。")
            self.lbl_test_result.setStyleSheet("color: #10B981;")

    def _edit_profile_dialog(self, profile_id):
        prof = next((p for p in (self._cfg.get("profiles") or []) if p["id"] == profile_id), None)
        if not prof:
            return
        dlg = ProfileEditorDialog(profile=prof, parent=self)
        if dlg.exec() == QDialog.Accepted:
            data = dlg.profile_data()
            cfg = self._collect_ui_config()
            updated, saved = tun_service.upsert_profile(cfg, data, activate=False)
            self._load_config_to_ui(updated)
            # 若编辑的是当前正在使用的线路且 TUN 运行中，热重载之
            if saved["id"] == updated.get("active_profile_id") and self._status.get("running"):
                self._spawn_worker(
                    lambda _p: tun_service.reload_live_config(updated),
                    lambda res, _e: self._on_hot_reload_feedback(res),
                )
            else:
                self.lbl_test_result.setText(f"✅ 已更新线路「{saved['name']}」。")
                self.lbl_test_result.setStyleSheet("color: #10B981;")

    def _select_profile(self, profile_id):
        cfg = self._collect_ui_config()
        updated = tun_service.select_profile(cfg, profile_id)
        self._load_config_to_ui(updated)
        prof = self._active_profile()
        name = prof["name"] if prof else profile_id
        if self._status.get("running"):
            self._spawn_worker(
                lambda _p: tun_service.reload_live_config(updated),
                lambda res, _e: self._on_hot_reload_feedback(res, extra=f"已切换至线路「{name}」"),
            )
        else:
            self.lbl_test_result.setText(f"✅ 已选用线路「{name}」，点击「🚀 启动 TUN」即可生效。")
            self.lbl_test_result.setStyleSheet("color: #10B981;")

    def _delete_profile(self, profile_id):
        prof = next((p for p in (self._cfg.get("profiles") or []) if p["id"] == profile_id), None)
        if not prof:
            return
        if QMessageBox.question(
            self, "确认删除", f"确定删除已保存线路「{prof['name']}」吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return
        cfg = self._collect_ui_config()
        updated = tun_service.delete_profile(cfg, profile_id)
        self._load_config_to_ui(updated)
        self.lbl_test_result.setText(f"已删除线路「{prof['name']}」。")
        self.lbl_test_result.setStyleSheet("")

    def _test_profile(self, profile_id):
        prof = next((p for p in (self._cfg.get("profiles") or []) if p["id"] == profile_id), None)
        if not prof or profile_id in self._testing_ids:
            return
        self._testing_ids.add(profile_id)
        self._render_profiles_table()
        self.lbl_test_result.setText(f"⏳ 正在测试「{prof['name']}」({prof['server']}:{prof['port']})...")
        self.lbl_test_result.setStyleSheet("color: #3B82F6;")

        def _job(_p):
            return tun_service.test_upstream_proxy(prof)

        def _done(res, err):
            self._testing_ids.discard(profile_id)
            if err or not res:
                res = {"ok": False, "message": str(err or "测试失败"), "detail": ""}
            updated = tun_service.update_profile_test_result(self._cfg, profile_id, res)
            self._load_config_to_ui(updated)
            if res.get("ok"):
                self.lbl_test_result.setText(f"✅ [{prof['name']}] {res['message']}")
                self.lbl_test_result.setStyleSheet("color: #10B981;")
            else:
                self.lbl_test_result.setText(f"❌ [{prof['name']}] {res['message']}")
                self.lbl_test_result.setStyleSheet("color: #EF4444;")

        self._spawn_worker(_job, _done)

    def _test_all_profiles(self):
        profiles = self._cfg.get("profiles") or []
        if not profiles:
            QMessageBox.information(self, "提示", "暂无已保存的线路，请先点击「➕ 添加线路」。")
            return
        for p in profiles:
            self._test_profile(p["id"])

    def _on_hot_reload_feedback(self, res, extra=""):
        if res and res[0]:
            msg = f"{extra}：{res[1]}" if extra else res[1]
            self.lbl_test_result.setText(f"✅ {msg}")
            self.lbl_test_result.setStyleSheet("color: #10B981;")
        elif res:
            self.lbl_test_result.setText(f"⚠️ {res[1]}")
            self.lbl_test_result.setStyleSheet("color: #F59E0B;")

    # -------------------------------------------------------------
    # 规则表格渲染与操作
    # -------------------------------------------------------------
    def _render_rules_table(self):
        self.table_rules.setRowCount(len(self._rules))
        for row, rule in enumerate(self._rules):
            chk = QCheckBox()
            chk.setChecked(bool(rule.get("enabled", True)))
            chk.toggled.connect(lambda val, r=row: self._toggle_rule_enabled(r, val))
            chk_wrap = QWidget()
            cl = QHBoxLayout(chk_wrap)
            cl.setContentsMargins(6, 0, 6, 0)
            cl.setAlignment(Qt.AlignCenter)
            cl.addWidget(chk)
            self.table_rules.setCellWidget(row, 0, chk_wrap)

            self.table_rules.setItem(row, 1, QTableWidgetItem(rule.get("type", "")))
            self.table_rules.setItem(row, 2, QTableWidgetItem(rule.get("value", "")))
            self.table_rules.setItem(row, 3, QTableWidgetItem(rule.get("policy", "PROXY")))
            self.table_rules.setItem(row, 4, QTableWidgetItem(rule.get("comment", "")))

            op_w = QWidget()
            op_l = QHBoxLayout(op_w)
            op_l.setContentsMargins(2, 2, 2, 2)
            op_l.setSpacing(3)

            btn_up = QPushButton("↑")
            btn_up.setFixedSize(24, 22)
            btn_up.setEnabled(row > 0)
            btn_up.clicked.connect(lambda _=False, r=row: self._move_rule(r, -1))

            btn_dn = QPushButton("↓")
            btn_dn.setFixedSize(24, 22)
            btn_dn.setEnabled(row < len(self._rules) - 1)
            btn_dn.clicked.connect(lambda _=False, r=row: self._move_rule(r, 1))

            btn_del = QPushButton("删")
            btn_del.setFixedSize(30, 22)
            btn_del.clicked.connect(lambda _=False, r=row: self._delete_rule(r))

            for b in (btn_up, btn_dn, btn_del):
                b.setCursor(Qt.PointingHandCursor)
                b.setStyleSheet("padding: 0; font-size: 8.5pt; border-radius: 5px;")
                op_l.addWidget(b)
            self.table_rules.setCellWidget(row, 5, op_w)

        enabled_cnt = sum(1 for r in self._rules if r.get("enabled", True))
        self.lbl_rules_count.setText(f"共 {len(self._rules)} 条自定义规则（已启用 {enabled_cnt} 条）")

    def _toggle_rule_enabled(self, row, val):
        if 0 <= row < len(self._rules):
            self._rules[row]["enabled"] = bool(val)
            enabled_cnt = sum(1 for r in self._rules if r.get("enabled", True))
            self.lbl_rules_count.setText(f"共 {len(self._rules)} 条自定义规则（已启用 {enabled_cnt} 条）")

    def _move_rule(self, row, delta):
        target = row + delta
        if 0 <= row < len(self._rules) and 0 <= target < len(self._rules):
            self._rules[row], self._rules[target] = self._rules[target], self._rules[row]
            self._render_rules_table()

    def _delete_rule(self, row):
        if 0 <= row < len(self._rules):
            del self._rules[row]
            self._render_rules_table()

    def _add_rule(self):
        rtype = self.cmb_rule_type.currentData() or "DOMAIN-SUFFIX"
        val = self.inp_rule_val.text().strip()
        pol = self.cmb_rule_policy.currentData() or "PROXY"
        note = self.inp_rule_note.text().strip()
        if not val:
            QMessageBox.warning(self, "提示", "请输入规则匹配值。")
            return
        self._rules.insert(0, {
            "enabled": True,
            "type": rtype,
            "value": val,
            "policy": pol,
            "comment": note,
        })
        self.inp_rule_val.clear()
        self.inp_rule_note.clear()
        self._render_rules_table()

    def _apply_preset(self):
        key = self.cmb_preset.currentData()
        if not key:
            return
        cfg = self._collect_ui_config()
        updated = tun_service.apply_rule_preset(cfg, key)
        self._load_config_to_ui(updated)
        QMessageBox.information(self, "预设已加载", "已套用预设分流规则，点击「保存并热重载规则」即可生效。")

    # -------------------------------------------------------------
    # 保存、热重载与 TUN 启停控制
    # -------------------------------------------------------------
    def _spawn_worker(self, fn, on_done):
        w = FuncWorker(fn, parent=self)
        self._workers.append(w)

        def _cleanup(res, err):
            try:
                self._workers.remove(w)
            except ValueError:
                pass
            w.deleteLater()
            on_done(res, err)

        w.done.connect(_cleanup)
        w.start()
        return w

    def _save_and_reload(self):
        cfg = self._collect_ui_config()
        self._cfg = tun_service.save_tun_config(cfg)
        self._update_fallback_banner(
            bool(self._cfg.get("fallback_to_direct", True)),
            int(self._cfg.get("fallback_interval", 10)),
        )
        if not self._cfg.get("server"):
            QMessageBox.information(self, "已保存", "网络与分流设置已保存（请先添加并选用代理线路后再启动 TUN）。")
            return

        def _job(_prog):
            return tun_service.reload_live_config(self._cfg)

        def _done(res, err):
            if err or not res:
                QMessageBox.warning(self, "保存失败", str(err or "未知错误"))
                return
            ok, msg = res
            if ok:
                QMessageBox.information(self, "已保存", msg)
            else:
                QMessageBox.warning(self, "配置校验未通过", msg)
            self._poll_status()

        self._spawn_worker(_job, _done)

    def _switch_mode(self, mode):
        def _job(_prog):
            return tun_service.switch_live_mode(mode)

        def _done(res, _err):
            self._cfg["mode"] = mode
            if res and res[0]:
                self.lbl_test_result.setText(f"ℹ️ {res[1]}")
                self.lbl_test_result.setStyleSheet("color: #3B82F6;")
            self._poll_status()

        self._spawn_worker(_job, _done)

    def _start_tun(self):
        if self._busy:
            return
        cfg = self._collect_ui_config()
        if not cfg.get("server"):
            QMessageBox.warning(self, "提示", "请先点击「➕ 添加线路」保存一条代理线路并选用后再启动 TUN。")
            return
        if not tun_service.find_mihomo_exe():
            QMessageBox.warning(
                self, "缺少 TUN 内核",
                "未找到 Mihomo 内核 (bin/mihomo.exe)，请确认安装包完整或已安装 Clash Verge。"
            )
            return

        try:
            self._cfg = tun_service.save_tun_config(cfg)
            tun_service.export_mihomo_yaml(self._cfg)
        except Exception as e:
            QMessageBox.warning(self, "配置错误", str(e))
            return

        prof = self._active_profile()
        line_name = prof["name"] if prof else f"{cfg['server']}:{cfg['port']}"
        text = (
            f"即将启动 TUN/VPN 虚拟网卡并接管系统流量：\n"
            f"• 选用线路：{line_name}\n"
            f"• 上级代理：{cfg['protocol'].upper()}://{cfg['server']}:{cfg['port']}\n"
            f"• 路由模式：{'规则代理 (Rule)' if cfg['mode'] == 'rule' else '全局代理 (Global)'}\n"
            f"• 虚拟网卡：{cfg['device_name']}\n\n"
            "注意：创建 Windows 虚拟网卡需要弹出一次 UAC 管理员确认。\n"
            "是否立即启动？"
        )
        self.ctx.confirm_and_run("start-tun", "启动 TUN / VPN", text, "启动 TUN")

    def _stop_tun(self):
        if self._busy:
            return
        self.ctx.confirm_and_run(
            "stop-tun", "停止 TUN / VPN",
            "将关闭 TUN 虚拟网卡，并恢复启动前的 Windows 系统代理设置。\n是否继续？",
            "停止 TUN",
        )

    def _close_all_conns(self):
        self._spawn_worker(lambda _p: tun_service.close_all_connections(), lambda _r, _e: self._poll_status())

    # -------------------------------------------------------------
    # 生命周期 Hooks & 状态轮询
    # -------------------------------------------------------------
    def activate(self):
        self._poll_status()
        if not self.poll_timer.isActive():
            self.poll_timer.start()

    def on_action_started(self, _action):
        self._busy = True
        self.btn_start_tun.setEnabled(False)
        self.btn_stop_tun.setEnabled(False)

    def on_action_finished(self, _ok):
        self._busy = False
        self.btn_start_tun.setEnabled(True)
        self.btn_stop_tun.setEnabled(True)
        self._poll_status()

    def _poll_status(self):
        if self._poll_pending:
            return
        self._poll_pending = True

        def _job(_prog):
            st = tun_service.get_tun_status()
            st["log_tail"] = tun_service.get_tun_logs_tail(80) if self.box_conns.isVisible() else ""
            return st

        def _done(st, _err):
            self._poll_pending = False
            if not st:
                return
            self._status = st
            self._apply_status_ui(st)

        self._spawn_worker(_job, _done)

    def _apply_status_ui(self, st):
        if st.get("mihomo_found"):
            self.lbl_core_badge.setText("Mihomo TUN 内核就绪")
        else:
            self.lbl_core_badge.setText("未找到 Mihomo 内核")

        running = bool(st.get("running"))
        dev = st.get("device_name", tun_service.TUN_DEVICE_NAME)
        fallback_active = bool(st.get("fallback_active"))
        active_out = st.get("active_outbound", "")
        if running:
            if fallback_active:
                self.lbl_run_state.setText(f"🟡 代理已掉线，已自动恢复直连（{dev}）")
                self.lbl_run_state.setStyleSheet("font-size: 11pt; font-weight: 700; color: #F59E0B;")
            elif active_out == "LAN-PROXY":
                self.lbl_run_state.setText(f"🟢 TUN 运行中 · 代理正常（{dev}）")
                self.lbl_run_state.setStyleSheet("font-size: 11pt; font-weight: 700; color: #10B981;")
            else:
                self.lbl_run_state.setText(f"🟢 TUN 运行中（{dev}）")
                self.lbl_run_state.setStyleSheet("font-size: 11pt; font-weight: 700; color: #10B981;")
            self.btn_start_tun.setText("🔄 重启 TUN")
            self.btn_start_tun.setEnabled(not self._busy)
            self.btn_stop_tun.setEnabled(not self._busy)
        else:
            self.lbl_run_state.setText("⚪ TUN 未启动")
            self.lbl_run_state.setStyleSheet("font-size: 11pt; font-weight: 700; color: #94A3B8;")
            self.btn_start_tun.setText("🚀 启动 TUN")
            self.btn_start_tun.setEnabled(not self._busy)
            self.btn_stop_tun.setEnabled(False)

        mode = st.get("mode", self._cfg.get("mode", "rule"))
        self.btn_mode_global.setChecked(mode == "global")
        self.btn_mode_rule.setChecked(mode != "global")

        prof = self._active_profile()
        line_label = prof["name"] if prof else "未选择"
        cnt = st.get("connections_count", 0)
        up = tun_service.fmt_bytes(st.get("upload_total", 0))
        dn = tun_service.fmt_bytes(st.get("download_total", 0))
        fallback_note = ""
        if running and fallback_active:
            fallback_note = "  |  ⚠️ 上游掉线·已切回直连"
        elif running and active_out:
            fallback_note = f"  |  出口: {active_out}"
        self.lbl_live_stats.setText(
            f"当前线路: {line_label}  |  活动连接: {cnt}  |  ↑ {up}  ↓ {dn}{fallback_note}"
        )

        if self.box_conns.isVisible():
            self._render_connections()
            log_txt = st.get("log_tail", "")
            if log_txt != self.txt_tun_log.toPlainText():
                self.txt_tun_log.setPlainText(log_txt)
                sb = self.txt_tun_log.verticalScrollBar()
                sb.setValue(sb.maximum())

    def _render_connections(self):
        conns = self._status.get("connections") or []
        term = self.inp_conn_filter.text().strip().lower()
        filtered = []
        for c in conns:
            meta = c.get("metadata") or {}
            proc = meta.get("process") or meta.get("processPath") or "--"
            host = meta.get("host") or meta.get("destinationIP") or "--"
            port = meta.get("destinationPort") or ""
            target = f"{host}:{port}" if port else host
            rule = c.get("rule") or "--"
            if c.get("rulePayload"):
                rule = f"{rule} ({c['rulePayload']})"
            chains = " → ".join(reversed(c.get("chains") or [])) or "--"
            if term and term not in f"{proc} {target} {rule} {chains}".lower():
                continue
            traffic = f"↑{tun_service.fmt_bytes(c.get('upload'))} / ↓{tun_service.fmt_bytes(c.get('download'))}"
            filtered.append((proc, target, rule, chains, traffic))

        self.table_conns.setRowCount(len(filtered))
        for r, row_vals in enumerate(filtered):
            for col, val in enumerate(row_vals):
                self.table_conns.setItem(r, col, QTableWidgetItem(val))

    def set_palette(self, pal):
        self._pal = pal
        for b in (self.btn_tab_cfg, self.btn_tab_rules, self.btn_tab_conns):
            b.set_palette(pal)
        self.update()
