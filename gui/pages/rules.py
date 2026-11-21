"""规则管理与智能学习页：分流规则配置、一键域名探测自动学习与策略缓存管理。"""

import os
import subprocess
import threading
import time

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMessageBox, QPushButton, QRadioButton, QScrollArea,
    QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from gui.components.glass_panel import GlassPanel
from gui.workers import FuncWorker
from services import probe_service
from sni_proxy import config, rules_manager
from .base import Page


class TabPillButton(QPushButton):
    """Sleek tab button for switching sections."""

    def __init__(self, title, glyph="", parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(34)
        self.glyph = glyph
        self.title_text = title
        self._is_light = False
        self._text_col = QColor("#E2E8F0")

    def set_palette(self, pal):
        self._is_light = pal.get("id") == "light"
        self._text_col = QColor(pal.get("text", "#F8FAFC"))
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = float(self.width()), float(self.height())
        rect = QRectF(0, 0, w, h)
        is_active = self.isChecked()
        is_hover = self.underMouse()

        if is_active:
            grad = QLinearGradient(0, 0, w, 0)
            grad.setColorAt(0.0, QColor(37, 99, 235))
            grad.setColorAt(1.0, QColor(59, 130, 246))
            p.setBrush(QBrush(grad))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(rect, 8, 8)
        elif is_hover:
            bg_col = QColor(37, 99, 235, 25) if self._is_light else QColor(30, 58, 138, 80)
            p.setBrush(bg_col)
            p.setPen(QPen(QColor(59, 130, 246, 70), 1.0))
            p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 8, 8)
        else:
            p.setBrush(Qt.NoBrush)
            p.setPen(Qt.NoPen)

        # Text
        p.setFont(QFont("Microsoft YaHei UI", 9, QFont.Bold if is_active else QFont.Normal))
        if is_active:
            col = QColor("#FFFFFF")
        elif self._is_light:
            col = QColor("#1E293B")
        else:
            col = QColor("#94A3B8")
        p.setPen(col)
        display = f"{self.glyph} {self.title_text}".strip()
        p.drawText(rect, Qt.AlignCenter, display)
        p.end()


class RulesPage(Page):
    """规则管理与智能学习页面：支持 PAC 分流配置、智能阻断探测与 strategies 缓存操作。"""

    probe_progress = Signal(str)
    probe_finished = Signal(dict)

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self._pal = {}
        self._current_probe_result = None
        self._probing = False
        self._probe_worker = None

        self.probe_progress.connect(self._on_probe_progress)
        self.probe_finished.connect(self._on_probe_finished)

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
        body_v.setSpacing(14)
        scroll.setWidget(body)
        body.setAutoFillBackground(False)
        scroll.viewport().setAutoFillBackground(False)
        outer.addWidget(scroll)
        self._scroll = scroll
        self._body = body

        # -------------------------------------------------------------
        # 1. 顶部标题与工具栏
        # -------------------------------------------------------------
        head_box = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("规则管理与智能学习")
        title.setObjectName("TitleLabel")
        sub = QLabel("管理分流域名、SNI 伪装规则与策略缓存，支持一键探测阻断域名并自动学习")
        sub.setObjectName("MutedLabel")
        sub.setWordWrap(True)
        title_col.addWidget(title)
        title_col.addWidget(sub)
        head_box.addLayout(title_col, 1)

        btn_box = QHBoxLayout()
        btn_box.setSpacing(8)
        self.btn_reload = QPushButton("🔄 重载外部规则")
        self.btn_reload.setCursor(Qt.PointingHandCursor)
        self.btn_reload.setToolTip("从 rules.json 重新加载规则并更新 PAC 分流脚本")
        self.btn_reload.clicked.connect(self._reload_rules)
        btn_box.addWidget(self.btn_reload)

        self.btn_open_file = QPushButton("📁 打开 rules.json")
        self.btn_open_file.setCursor(Qt.PointingHandCursor)
        self.btn_open_file.setToolTip("在系统编辑器中打开外部 rules.json 配置文件")
        self.btn_open_file.clicked.connect(self._open_rules_file)
        btn_box.addWidget(self.btn_open_file)

        head_box.addLayout(btn_box)
        body_v.addLayout(head_box)

        # -------------------------------------------------------------
        # 2. 代理分流模式选择卡 (PAC 智能分流 vs 全局代理)
        # -------------------------------------------------------------
        self.panel_mode = GlassPanel("代理分流模式与 PAC 脚本")
        mode_box = QVBoxLayout()
        mode_box.setSpacing(10)

        radio_row = QHBoxLayout()
        radio_row.setSpacing(16)
        self.radio_pac = QRadioButton("PAC 智能分流模式 (推荐)")
        self.radio_pac.setCursor(Qt.PointingHandCursor)
        self.radio_pac.setToolTip("仅将命中封锁列表的域名导向本地代理，其余全部 DIRECT 直连，轻量且不与 Clash 冲突")
        self.radio_global = QRadioButton("全局系统代理模式")
        self.radio_global.setCursor(Qt.PointingHandCursor)
        self.radio_global.setToolTip("所有系统流量均经过本地代理端口 127.0.0.1:8888")

        radio_row.addWidget(self.radio_pac)
        radio_row.addWidget(self.radio_global)
        radio_row.addStretch(1)

        self.btn_apply_mode = QPushButton("应用模式变更")
        self.btn_apply_mode.setObjectName("Primary")
        self.btn_apply_mode.setCursor(Qt.PointingHandCursor)
        self.btn_apply_mode.clicked.connect(self._save_proxy_mode)
        radio_row.addWidget(self.btn_apply_mode)
        mode_box.addLayout(radio_row)

        # PAC 脚本地址与说明行
        pac_info_row = QHBoxLayout()
        pac_info_row.setSpacing(8)
        self.lbl_pac_url = QLabel("PAC 脚本地址：http://127.0.0.1:8888/proxy.pac")
        self.lbl_pac_url.setWordWrap(True)
        self.lbl_pac_url.setStyleSheet("font-family: Consolas, 'Microsoft YaHei UI'; font-size: 8.5pt;")
        self.btn_copy_pac = QPushButton("📋 复制")
        self.btn_copy_pac.setFixedHeight(26)
        self.btn_copy_pac.setCursor(Qt.PointingHandCursor)
        self.btn_copy_pac.clicked.connect(self._copy_pac_url)
        pac_info_row.addWidget(self.lbl_pac_url)
        pac_info_row.addWidget(self.btn_copy_pac)
        pac_info_row.addStretch(1)
        mode_box.addLayout(pac_info_row)

        self.panel_mode.add_layout(mode_box)
        body_v.addWidget(self.panel_mode)

        # -------------------------------------------------------------
        # 3. 分区切换 Tab 栏 (智能探测 / 封锁后缀 / SNI 映射 / 策略缓存)
        # -------------------------------------------------------------
        tab_nav_frame = QFrame()
        tab_nav_frame.setStyleSheet("""
            QFrame {
                background: rgba(15, 23, 42, 0.4);
                border: 1px solid rgba(56, 189, 248, 0.15);
                border-radius: 10px;
            }
        """)
        tab_nav_layout = QHBoxLayout(tab_nav_frame)
        tab_nav_layout.setContentsMargins(6, 6, 6, 6)
        tab_nav_layout.setSpacing(6)

        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)

        self.btn_tab_probe = TabPillButton("智能探测", "🚀")
        self.btn_tab_rules = TabPillButton("分流后缀", "📋")
        self.btn_tab_rewrites = TabPillButton("SNI 伪装", "🔀")
        self.btn_tab_cache = TabPillButton("策略缓存", "⚡")

        for idx, btn in enumerate((self.btn_tab_probe, self.btn_tab_rules,
                                  self.btn_tab_rewrites, self.btn_tab_cache)):
            self.tab_group.addButton(btn, idx)
            tab_nav_layout.addWidget(btn, 1)
            btn.clicked.connect(lambda _=False, i=idx: self._switch_tab(i))

        body_v.addWidget(tab_nav_frame)

        # -------------------------------------------------------------
        # 4. 各分区卡片容器
        # -------------------------------------------------------------
        self.box_probe = self._build_probe_card()
        self.box_rules = self._build_rules_card()
        self.box_rewrites = self._build_rewrites_card()
        self.box_cache = self._build_cache_card()

        body_v.addWidget(self.box_probe)
        body_v.addWidget(self.box_rules)
        body_v.addWidget(self.box_rewrites)
        body_v.addWidget(self.box_cache)

        # 默认选中并展示智能探测卡
        self.btn_tab_probe.setChecked(True)
        self._switch_tab(0)

        # 加载外部 rules.json 数据到 UI
        self._refresh_all_data()

    # -------------------------------------------------------------
    # 模块构建：一键智能探测与自动学习卡
    # -------------------------------------------------------------
    def _build_probe_card(self):
        panel = GlassPanel("一键阻断探测与策略学习")
        v = QVBoxLayout()
        v.setSpacing(12)

        desc = QLabel(
            "输入在校园网下打不开或加载异常的域名（例如 douyin.com、v.qq.com、example.edu.cn）。\n"
            "系统将自动检测直连连通性，并在候选白名单 SNI 池与边缘 IP 中并发探测，找到最优绕过策略后支持一键写入分流规则。"
        )
        desc.setObjectName("MutedLabel")
        desc.setWordWrap(True)
        v.addWidget(desc)

        # 输入栏 + 开始按钮
        inp_row = QHBoxLayout()
        inp_row.setSpacing(10)
        self.inp_probe_domain = QLineEdit()
        self.inp_probe_domain.setPlaceholderText("请输入测试域名，例如：douyin.com 或 https://www.douyin.com")
        self.inp_probe_domain.returnPressed.connect(self._start_probe)
        self.inp_probe_domain.setFixedHeight(36)
        inp_row.addWidget(self.inp_probe_domain, 1)

        self.btn_start_probe = QPushButton("🚀 开始智能探测")
        self.btn_start_probe.setObjectName("Primary")
        self.btn_start_probe.setFixedHeight(36)
        self.btn_start_probe.setCursor(Qt.PointingHandCursor)
        self.btn_start_probe.clicked.connect(self._start_probe)
        inp_row.addWidget(self.btn_start_probe)
        v.addLayout(inp_row)

        # 实时探测状态与日志信息
        self.lbl_probe_status = QLabel("就绪：等待开始探测")
        self.lbl_probe_status.setStyleSheet("color: #38BDF8; font-size: 9.5pt;")
        v.addWidget(self.lbl_probe_status)

        # 探测结果卡片
        self.probe_result_card = QFrame()
        self.probe_result_card.setStyleSheet("""
            QFrame {
                background: rgba(15, 23, 42, 0.65);
                border: 1px solid rgba(56, 189, 248, 0.25);
                border-radius: 12px;
                padding: 10px;
            }
        """)
        rc_lay = QVBoxLayout(self.probe_result_card)
        rc_lay.setContentsMargins(14, 12, 14, 12)
        rc_lay.setSpacing(8)

        self.lbl_res_title = QLabel("探测结果待定")
        self.lbl_res_title.setStyleSheet("font-size: 11pt; font-weight: 700; color: #FFFFFF;")
        rc_lay.addWidget(self.lbl_res_title)

        self.lbl_res_details = QLabel("暂无探测结果。在上方输入域名并点击“开始智能探测”。")
        self.lbl_res_details.setObjectName("MutedLabel")
        self.lbl_res_details.setWordWrap(True)
        rc_lay.addWidget(self.lbl_res_details)

        res_btn_row = QHBoxLayout()
        res_btn_row.addStretch(1)
        self.btn_apply_probe = QPushButton("✨ 一键应用并加入规则")
        self.btn_apply_probe.setObjectName("Primary")
        self.btn_apply_probe.setFixedHeight(32)
        self.btn_apply_probe.setCursor(Qt.PointingHandCursor)
        self.btn_apply_probe.setEnabled(False)
        self.btn_apply_probe.clicked.connect(self._apply_probe_result)
        res_btn_row.addWidget(self.btn_apply_probe)
        rc_lay.addLayout(res_btn_row)

        v.addWidget(self.probe_result_card)
        panel.add_layout(v)
        return panel

    # -------------------------------------------------------------
    # 模块构建：封锁域名后缀列表
    # -------------------------------------------------------------
    def _build_rules_card(self):
        panel = GlassPanel("封锁域名分流后缀列表")
        v = QVBoxLayout()
        v.setSpacing(10)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        self.inp_add_suffix = QLineEdit()
        self.inp_add_suffix.setPlaceholderText("输入要添加的封锁域名后缀（如 example.com）")
        self.inp_add_suffix.returnPressed.connect(self._add_suffix)
        top_row.addWidget(self.inp_add_suffix, 1)

        self.btn_add_suffix = QPushButton("➕ 添加后缀")
        self.btn_add_suffix.setObjectName("Primary")
        self.btn_add_suffix.setCursor(Qt.PointingHandCursor)
        self.btn_add_suffix.clicked.connect(self._add_suffix)
        top_row.addWidget(self.btn_add_suffix)

        self.inp_search_suffix = QLineEdit()
        self.inp_search_suffix.setPlaceholderText("🔍 快速过滤列表...")
        self.inp_search_suffix.textChanged.connect(self._filter_suffixes)
        self.inp_search_suffix.setFixedWidth(180)
        top_row.addWidget(self.inp_search_suffix)
        v.addLayout(top_row)

        # 后缀表格
        self.table_suffixes = QTableWidget()
        self.table_suffixes.setColumnCount(3)
        self.table_suffixes.setHorizontalHeaderLabels(["域名后缀", "匹配模式", "操作"])
        self.table_suffixes.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_suffixes.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_suffixes.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_suffixes.horizontalHeader().setMinimumSectionSize(40)
        self.table_suffixes.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table_suffixes.verticalHeader().setVisible(False)
        self.table_suffixes.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_suffixes.setMinimumWidth(0)
        self.table_suffixes.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.table_suffixes.setMinimumHeight(220)
        self.table_suffixes.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_suffixes.setAlternatingRowColors(True)
        v.addWidget(self.table_suffixes)

        self.lbl_suffix_count = QLabel("共 0 个规则后缀")
        self.lbl_suffix_count.setObjectName("MutedLabel")
        v.addWidget(self.lbl_suffix_count)

        panel.add_layout(v)
        return panel

    # -------------------------------------------------------------
    # 模块构建：SNI 伪装重写映射
    # -------------------------------------------------------------
    def _build_rewrites_card(self):
        panel = GlassPanel("特定主机名 SNI 伪装重写映射")
        v = QVBoxLayout()
        v.setSpacing(10)

        desc = QLabel(
            "当访问左侧原始主机名时，向校园网网关发送右侧伪装 SNI 进行握手，实现阻断绕过。"
        )
        desc.setObjectName("MutedLabel")
        desc.setWordWrap(True)
        v.addWidget(desc)

        add_row = QHBoxLayout()
        add_row.setSpacing(8)
        self.inp_rw_host = QLineEdit()
        self.inp_rw_host.setPlaceholderText("原始主机名（如 www.douyin.com）")
        self.inp_rw_sni = QLineEdit()
        self.inp_rw_sni.setPlaceholderText("伪装 SNI（如 douyin.com）")
        self.btn_add_rw = QPushButton("➕ 添加映射")
        self.btn_add_rw.setObjectName("Primary")
        self.btn_add_rw.setCursor(Qt.PointingHandCursor)
        self.btn_add_rw.clicked.connect(self._add_rewrite)

        add_row.addWidget(self.inp_rw_host, 1)
        add_row.addWidget(self.inp_rw_sni, 1)
        add_row.addWidget(self.btn_add_rw)
        v.addLayout(add_row)

        self.table_rewrites = QTableWidget()
        self.table_rewrites.setColumnCount(3)
        self.table_rewrites.setHorizontalHeaderLabels(["原始主机名", "伪装 SNI", "操作"])
        self.table_rewrites.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_rewrites.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table_rewrites.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_rewrites.horizontalHeader().setMinimumSectionSize(40)
        self.table_rewrites.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table_rewrites.verticalHeader().setVisible(False)
        self.table_rewrites.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_rewrites.setMinimumWidth(0)
        self.table_rewrites.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.table_rewrites.setMinimumHeight(180)
        self.table_rewrites.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_rewrites.setAlternatingRowColors(True)
        v.addWidget(self.table_rewrites)

        # 候选 SNI 白名单池展示
        pool_lab = QLabel("候选白名单 SNI 探测池（自动探测时使用）：")
        pool_lab.setStyleSheet("font-weight: 600; margin-top: 8px;")
        v.addWidget(pool_lab)

        self.lbl_pool_chips = QLabel()
        self.lbl_pool_chips.setObjectName("MutedLabel")
        self.lbl_pool_chips.setWordWrap(True)
        v.addWidget(self.lbl_pool_chips)

        panel.add_layout(v)
        return panel

    # -------------------------------------------------------------
    # 模块构建：策略缓存管理 (strategies.json)
    # -------------------------------------------------------------
    def _build_cache_card(self):
        panel = GlassPanel("策略缓存管理 (strategies.json)")
        v = QVBoxLayout()
        v.setSpacing(10)

        desc = QLabel(
            "本地 strategies.json 记录了各域名历史成功测通的边缘 IP 与伪装 SNI，供代理即时复用。\n"
            "若某域名出现打不开或连接失败，可删除该条目让代理重新进行实时多路竞速探测。"
        )
        desc.setObjectName("MutedLabel")
        desc.setWordWrap(True)
        v.addWidget(desc)

        self.table_cache = QTableWidget()
        self.table_cache.setColumnCount(5)
        self.table_cache.setHorizontalHeaderLabels(["目标域名", "优选 IP", "伪装 SNI", "校验级别", "操作"])
        self.table_cache.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_cache.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_cache.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table_cache.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_cache.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table_cache.horizontalHeader().setMinimumSectionSize(40)
        self.table_cache.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.table_cache.verticalHeader().setVisible(False)
        self.table_cache.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table_cache.setMinimumWidth(0)
        self.table_cache.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.table_cache.setMinimumHeight(220)
        self.table_cache.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_cache.setAlternatingRowColors(True)
        v.addWidget(self.table_cache)

        bottom_bar = QHBoxLayout()
        self.lbl_cache_count = QLabel("共 0 个缓存条目")
        self.lbl_cache_count.setObjectName("MutedLabel")
        bottom_bar.addWidget(self.lbl_cache_count)
        bottom_bar.addStretch(1)

        self.btn_refresh_cache = QPushButton("🔄 刷新缓存")
        self.btn_refresh_cache.setCursor(Qt.PointingHandCursor)
        self.btn_refresh_cache.clicked.connect(self._refresh_cache_table)
        bottom_bar.addWidget(self.btn_refresh_cache)

        self.btn_clear_cache = QPushButton("⚠️ 清空全部缓存")
        self.btn_clear_cache.setObjectName("Danger")
        self.btn_clear_cache.setCursor(Qt.PointingHandCursor)
        self.btn_clear_cache.clicked.connect(self._clear_all_cache)
        bottom_bar.addWidget(self.btn_clear_cache)

        v.addLayout(bottom_bar)
        panel.add_layout(v)
        return panel

    # -------------------------------------------------------------
    # 界面交互与数据加载
    # -------------------------------------------------------------
    def _switch_tab(self, index):
        self.box_probe.setVisible(index == 0)
        self.box_rules.setVisible(index == 1)
        self.box_rewrites.setVisible(index == 2)
        self.box_cache.setVisible(index == 3)

    def _refresh_all_data(self):
        rules = rules_manager.load_rules()
        # 1. Mode
        mode = rules.get("proxy_mode", "pac")
        if mode == "global":
            self.radio_global.setChecked(True)
        else:
            self.radio_pac.setChecked(True)

        # 2. Suffixes
        self._populate_suffixes(rules.get("blocked_suffixes", []))

        # 3. Rewrites & Pool
        self._populate_rewrites(rules.get("sni_rewrite", {}))
        pool = rules.get("allowed_sni_pool", [])
        self.lbl_pool_chips.setText("  •  ".join(pool) if pool else "无")

        # 4. Cache
        self._refresh_cache_table()

    def _populate_suffixes(self, suffixes):
        self._all_suffixes = list(suffixes)
        self._filter_suffixes()

    def _filter_suffixes(self):
        term = self.inp_search_suffix.text().strip().lower()
        items = [s for s in getattr(self, "_all_suffixes", []) if not term or term in s.lower()]
        self.table_suffixes.setRowCount(len(items))
        for row, s in enumerate(items):
            self.table_suffixes.setItem(row, 0, QTableWidgetItem(s))
            self.table_suffixes.setItem(row, 1, QTableWidgetItem(f"*.{s} 及 {s}"))
            btn_del = QPushButton("删除")
            btn_del.setFixedHeight(24)
            btn_del.setCursor(Qt.PointingHandCursor)
            btn_del.clicked.connect(lambda _=False, suffix=s: self._remove_suffix(suffix))
            self.table_suffixes.setCellWidget(row, 2, btn_del)
        self.lbl_suffix_count.setText(f"共 {len(self._all_suffixes)} 个规则后缀（当前显示 {len(items)} 个）")

    def _populate_rewrites(self, rewrites):
        self.table_rewrites.setRowCount(len(rewrites))
        for row, (h, r) in enumerate(rewrites.items()):
            self.table_rewrites.setItem(row, 0, QTableWidgetItem(h))
            self.table_rewrites.setItem(row, 1, QTableWidgetItem(r))
            btn_del = QPushButton("删除")
            btn_del.setFixedHeight(24)
            btn_del.setCursor(Qt.PointingHandCursor)
            btn_del.clicked.connect(lambda _=False, host=h: self._remove_rewrite(host))
            self.table_rewrites.setCellWidget(row, 2, btn_del)

    def _refresh_cache_table(self):
        cache = rules_manager.get_strategy_cache()
        rows = []
        for d, entry in cache.items():
            eps = entry.get("endpoints", [])
            if eps:
                ip, sni, lvl = eps[0][0], eps[0][1], eps[0][2] if len(eps[0]) > 2 else "chain"
            else:
                ip, sni, lvl = "无可用策略", "--", "--"
            rows.append((d, ip, sni, lvl))

        self.table_cache.setRowCount(len(rows))
        for r, (d, ip, sni, lvl) in enumerate(rows):
            self.table_cache.setItem(r, 0, QTableWidgetItem(d))
            self.table_cache.setItem(r, 1, QTableWidgetItem(ip))
            self.table_cache.setItem(r, 2, QTableWidgetItem(sni))
            self.table_cache.setItem(r, 3, QTableWidgetItem(lvl))
            btn_del = QPushButton("删除")
            btn_del.setFixedHeight(24)
            btn_del.setCursor(Qt.PointingHandCursor)
            btn_del.clicked.connect(lambda _=False, domain=d: self._delete_cache_entry(domain))
            self.table_cache.setCellWidget(r, 4, btn_del)
        self.lbl_cache_count.setText(f"共 {len(rows)} 个已缓存的域名策略")

    # -------------------------------------------------------------
    # 规则增删操作
    # -------------------------------------------------------------
    def _add_suffix(self):
        text = self.inp_add_suffix.text().strip().lower()
        if not text:
            return
        if rules_manager.add_blocked_suffix(text):
            self.inp_add_suffix.clear()
            self._refresh_all_data()
        else:
            QMessageBox.information(self, "提示", f"后缀「{text}」已存在或格式不正确。")

    def _remove_suffix(self, suffix):
        if QMessageBox.question(
            self, "确认删除", f"确定从分流规则中移除后缀「{suffix}」吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) == QMessageBox.Yes:
            rules_manager.remove_blocked_suffix(suffix)
            self._refresh_all_data()

    def _add_rewrite(self):
        host = self.inp_rw_host.text().strip().lower()
        sni = self.inp_rw_sni.text().strip().lower()
        if not host or not sni:
            QMessageBox.warning(self, "提示", "原始主机名与伪装 SNI 均不能为空。")
            return
        rules_manager.add_sni_rewrite(host, sni)
        self.inp_rw_host.clear()
        self.inp_rw_sni.clear()
        self._refresh_all_data()

    def _remove_rewrite(self, host):
        if QMessageBox.question(
            self, "确认删除", f"确定移除主机「{host}」的 SNI 重写映射吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) == QMessageBox.Yes:
            rules_manager.remove_sni_rewrite(host)
            self._refresh_all_data()

    def _delete_cache_entry(self, domain):
        rules_manager.delete_strategy_cache_entry(domain)
        self._refresh_cache_table()

    def _clear_all_cache(self):
        if QMessageBox.warning(
            self, "确认清空", "确定清空全部 strategies.json 策略缓存吗？清空后各域名将在首次访问时重新探测。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) == QMessageBox.Yes:
            rules_manager.clear_strategy_cache()
            self._refresh_cache_table()

    def _save_proxy_mode(self):
        new_mode = "global" if self.radio_global.isChecked() else "pac"
        rules_manager.set_proxy_mode(new_mode)
        # 通知主窗口刷新系统代理（若代理处于开启状态）
        self.request_action.emit("set-proxy")
        QMessageBox.information(
            self, "模式变更", f"已切换为「{'全局代理' if new_mode == 'global' else 'PAC 智能分流'}」模式并即时生效。"
        )

    def _copy_pac_url(self):
        from PySide6.QtWidgets import QApplication
        cb = QApplication.clipboard()
        if cb:
            cb.setText("http://127.0.0.1:8888/proxy.pac")
            QMessageBox.information(self, "已复制", "PAC 脚本地址已复制到剪贴板！")

    def _reload_rules(self):
        rules_manager.load_rules(force=True)
        self._refresh_all_data()
        QMessageBox.information(self, "重载成功", "已从 rules.json 重新加载最新配置，PAC 分流脚本已同步生成。")

    def _open_rules_file(self):
        if os.path.exists(rules_manager.RULES_FILE):
            os.startfile(rules_manager.RULES_FILE)
        else:
            rules_manager.ensure_rules_file()
            os.startfile(rules_manager.RULES_FILE)

    # -------------------------------------------------------------
    # 一键智能探测
    # -------------------------------------------------------------
    def _start_probe(self):
        domain = self.inp_probe_domain.text().strip()
        if not domain:
            QMessageBox.warning(self, "提示", "请输入需要探测的域名。")
            return
        if self._probing:
            return

        self._probing = True
        self.btn_start_probe.setEnabled(False)
        self.btn_apply_probe.setEnabled(False)
        self.lbl_probe_status.setText("🚀 正在发起智能探测与多路竞速...")
        self.lbl_res_title.setText("⏳ 探测进行中...")
        self.lbl_res_details.setText("正在执行 DNS 解析、直连特征分析与并发候选伪装 SNI 测试...")

        def _work(on_progress):
            # FuncWorker 会把 on_progress 作为参数传入，不能再写成无参函数
            return probe_service.probe_domain_smart(
                domain, on_progress=on_progress
            )

        # 必须持有 worker 引用并监听 FuncWorker.done(result, error)：
        # QThread.finished 无参数，且局部变量会在探测线程运行期间被回收，
        # 触发 "QThread: Destroyed while thread is still running" 并退出程序。
        self._probe_worker = FuncWorker(_work, parent=self)
        self._probe_worker.progress.connect(self._on_probe_progress)
        self._probe_worker.done.connect(self._on_probe_done)
        self._probe_worker.finished.connect(self._on_probe_thread_finished)
        self._probe_worker.start()

    def _on_probe_thread_finished(self):
        worker = getattr(self, "_probe_worker", None)
        self._probe_worker = None
        if worker is not None:
            worker.deleteLater()

    def _on_probe_done(self, result, error):
        if error or not result:
            self._probing = False
            self.btn_start_probe.setEnabled(True)
            self.btn_apply_probe.setEnabled(False)
            self._current_probe_result = None
            self.lbl_res_title.setText("❌ 探测未通")
            self.lbl_res_title.setStyleSheet(
                "font-size: 11pt; font-weight: 700; color: #EF4444;")
            self.lbl_res_details.setText(
                f"原因：{error or '探测超时或无响应'}\n"
                "建议检查网络连接或尝试手动添加放行白名单 SNI。")
            self.lbl_probe_status.setText("❌ 探测失败")
            return
        self._on_probe_finished(result)

    def _on_probe_progress(self, msg):
        self.lbl_probe_status.setText(msg)

    def _on_probe_finished(self, res):
        self._probing = False
        self.btn_start_probe.setEnabled(True)
        self._current_probe_result = res

        if not res or not res.get("success"):
            err = res.get("error", "未知错误") if res else "探测超时或无响应"
            self.lbl_res_title.setText("❌ 探测未通")
            self.lbl_res_title.setStyleSheet("font-size: 11pt; font-weight: 700; color: #EF4444;")
            self.lbl_res_details.setText(f"原因：{err}\n建议检查网络连接或尝试手动添加放行白名单 SNI。")
            self.btn_apply_probe.setEnabled(False)
            return

        self.lbl_res_title.setText("✅ 智能探测成功，已发现最优解封策略！")
        self.lbl_res_title.setStyleSheet("font-size: 11pt; font-weight: 700; color: #10B981;")
        domain = res["domain"]
        best_ip = res["best_ip"]
        best_sni = res["best_sni"]
        lat = res["latency_ms"]
        level = res.get("verify_level", "chain")
        suf = res.get("recommended_suffix", domain)

        detail_text = (
            f"目标域名：{domain}  |  推荐规则后缀：*.{suf}\n"
            f"优选边缘 IP：{best_ip}  |  伪装 SNI：{best_sni}\n"
            f"握手耗时：{lat} ms  |  证书校验级别：{level} ({'直签' if level == 'host' else '证书链兼容'})\n"
            f"直连状态：{'已被校园网 SNI 阻断' if res.get('is_blocked') else '直连正常'}"
        )
        self.lbl_res_details.setText(detail_text)
        self.btn_apply_probe.setEnabled(True)

    def _apply_probe_result(self):
        if not self._current_probe_result or not self._current_probe_result.get("success"):
            return
        ok, msg = probe_service.apply_probe_result(self._current_probe_result)
        if ok:
            QMessageBox.information(self, "应用成功", msg)
            self.btn_apply_probe.setEnabled(False)
            self._refresh_all_data()
        else:
            QMessageBox.warning(self, "应用失败", msg)

    # -------------------------------------------------------------
    # 主题适配
    # -------------------------------------------------------------
    def set_palette(self, pal):
        self._pal = pal
        is_light = pal.get("id") == "light"
        for btn in (self.btn_tab_probe, self.btn_tab_rules,
                    self.btn_tab_rewrites, self.btn_tab_cache):
            btn.set_palette(pal)

        bg_card = "rgba(255, 255, 255, 0.9)" if is_light else "rgba(15, 23, 42, 0.65)"
        border_card = "rgba(203, 213, 225, 0.9)" if is_light else "rgba(56, 189, 248, 0.25)"
        self.probe_result_card.setStyleSheet(f"""
            QFrame {{
                background: {bg_card};
                border: 1px solid {border_card};
                border-radius: 12px;
                padding: 10px;
            }}
        """)
        self.update()
