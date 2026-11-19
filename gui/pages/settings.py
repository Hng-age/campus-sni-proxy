"""设置中心页：外观、应用、安全与软件信息四个分区。"""

import time

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QScrollArea,
    QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from gui.components.glass_panel import GlassPanel, KVGrid
from services import config_manager
from sni_proxy.config import VERSION
from .base import Page

LOG_LEVELS = ("全部", "INFO 及以上", "WARNING 及以上", "仅 ERROR", "含 DEBUG")


class SettingsPage(Page):
    """设置中心：改动即时保存并给出“已保存”反馈。"""

    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self._env = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setAttribute(Qt.WA_StyledBackground, False)
        body_v = QVBoxLayout(body)
        body_v.setContentsMargins(22, 18, 22, 18)
        body_v.setSpacing(14)
        outer.addWidget(scroll)
        scroll.setWidget(body)
        body.setAutoFillBackground(False)
        scroll.viewport().setAutoFillBackground(False)

        # ---- 页面标题
        head = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        title = QLabel("设置中心")
        title.setObjectName("TitleLabel")
        sub = QLabel("改动即时保存；外观类改动立即生效")
        sub.setObjectName("MutedLabel")
        title_col.addWidget(title)
        title_col.addWidget(sub)
        head.addLayout(title_col)
        head.addStretch(1)
        body_v.addLayout(head)

        # ---- 四个分区 + 页脚
        body_v.addWidget(self._build_appearance())
        body_v.addWidget(self._build_app())
        body_v.addWidget(self._build_security())
        body_v.addWidget(self._build_about())

        foot = QHBoxLayout()
        self.saved_lab = QLabel("")
        self.saved_lab.setObjectName("TinyLabel")
        foot.addWidget(self.saved_lab)
        foot.addStretch(1)
        ver = QLabel(f"SNI Proxy Desktop v{VERSION} · MIT 许可证")
        ver.setObjectName("TinyLabel")
        foot.addWidget(ver)
        body_v.addLayout(foot)
        body_v.addStretch(1)

    # -------------------------------------------------------- builders
    @staticmethod
    def _row(grid, row, key, field):
        """设置网格一行：左侧 key 标签 + 右侧控件（或布局）。"""
        lab = QLabel(key)
        lab.setObjectName("KVKey")
        grid.addWidget(lab, row, 0, Qt.AlignTop)
        if isinstance(field, QWidget):
            grid.addWidget(field, row, 1)
        else:
            grid.addLayout(field, row, 1)

    def _build_appearance(self):
        """外观分区：主题 / 玻璃 / 动画 / 字体。"""
        panel = GlassPanel("外观")
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)

        self.combo_theme = QComboBox()
        self.combo_theme.addItems(["跟随系统", "深色模式", "浅色模式"])
        self.combo_theme.setToolTip("跟随系统 / 深色模式 / 浅色模式，改动立即生效并保存")
        self._row(grid, 0, "主题", self.combo_theme)

        self.check_glass = QCheckBox("启用玻璃效果")
        self.check_glass.setToolTip("关闭后卡片改为纯色背景（低配机器更流畅）")
        self._row(grid, 1, "玻璃效果", self.check_glass)

        slider_row = QHBoxLayout()
        slider_row.setSpacing(10)
        self.slider_strength = QSlider(Qt.Horizontal)
        self.slider_strength.setRange(0, 100)
        self.slider_strength.setToolTip("玻璃卡片不透明度：0-100，数值越大越实")
        self.strength_lab = QLabel("60")
        self.strength_lab.setObjectName("MutedLabel")
        slider_row.addWidget(self.slider_strength, 1)
        slider_row.addWidget(self.strength_lab)
        self._row(grid, 2, "玻璃强度", slider_row)

        self.check_anim = QCheckBox("启用界面动画")
        self.check_anim.setToolTip("界面切换等过渡动画")
        self._row(grid, 3, "动画", self.check_anim)

        self.combo_font = QComboBox()
        self.combo_font.addItems(["标准", "大", "更大"])
        self.combo_font.setToolTip("全局字体大小：标准 / 大 / 更大")
        self._row(grid, 4, "字体大小", self.combo_font)

        # 初始值先设置、后连接信号，避免初始化阶段误触发保存
        s = self.ctx.settings
        theme_map = {"system": 0, "dark": 1, "light": 2}
        self.combo_theme.setCurrentIndex(
            theme_map.get(s.get("theme", "system"), 0))
        self.check_glass.setChecked(bool(s.get("glass", True)))
        self.slider_strength.setValue(int(s.get("glass_strength", 60)))
        self.strength_lab.setText(str(self.slider_strength.value()))
        self.check_anim.setChecked(bool(s.get("animations", True)))
        self.combo_font.setCurrentIndex(
            max(0, min(2, int(s.get("font_scale", 0)))))

        self.combo_theme.currentIndexChanged.connect(self._theme_changed)
        self.check_glass.toggled.connect(self._glass_changed)
        self.slider_strength.valueChanged.connect(self._strength_changed)
        self.check_anim.toggled.connect(self._anim_changed)
        self.combo_font.currentIndexChanged.connect(self._font_changed)

        panel.add_layout(grid)
        return panel

    def _build_app(self):
        """应用分区：日志级别/保留天数、启动与关闭行为。"""
        panel = GlassPanel("应用")
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)

        self.combo_level = QComboBox()
        self.combo_level.addItems(list(LOG_LEVELS))
        self.combo_level.setToolTip("默认日志级别过滤（保存所选序号）")
        self._row(grid, 0, "默认日志级别", self.combo_level)

        self.spin_days = QSpinBox()
        self.spin_days.setRange(1, 365)
        self.spin_days.setToolTip("日志文件保留天数（1-365），超期自动清理")
        self._row(grid, 1, "日志保留天数", self.spin_days)

        self.check_show = QCheckBox("启动时显示主窗口")
        self.check_show.setToolTip("取消勾选后启动仅驻留系统托盘")
        self._row(grid, 2, "启动行为", self.check_show)

        self.check_tray = QCheckBox("关闭时最小化到托盘")
        self.check_tray.setToolTip("点关闭按钮时最小化到托盘而不是退出程序")
        self._row(grid, 3, "关闭行为", self.check_tray)

        s = self.ctx.settings
        self.combo_level.setCurrentIndex(
            max(0, min(len(LOG_LEVELS) - 1, int(s.get("log_level_filter", 0)))))
        self.spin_days.setValue(int(s.get("log_retention_days", 14)))
        self.check_show.setChecked(bool(s.get("show_on_start", True)))
        self.check_tray.setChecked(bool(s.get("minimize_to_tray", False)))

        self.combo_level.currentIndexChanged.connect(self._level_changed)
        self.spin_days.valueChanged.connect(self._days_changed)
        self.check_show.toggled.connect(self._show_changed)
        self.check_tray.toggled.connect(self._tray_changed)

        panel.add_layout(grid)
        return panel

    def _build_security(self):
        """安全分区：只读安全状态 + 诊断脱敏开关。"""
        panel = GlassPanel("安全")
        grid = KVGrid()
        v = grid.add_row("上游 TLS 严格校验", "固定启用", "strict")
        v.setToolTip("仅当以环境变量 SNI_STRICT_UPSTREAM=0 启动时才退回兼容"
                     "模式；界面不提供快捷开关")
        grid.add_row("证书有效性检查", "启用", "certcheck")
        grid.add_row("私钥权限检查", "启用", "keyacl")
        grid.add_row("系统设置恢复保护", "启用", "restore")
        panel.add(grid)

        self.check_mask = QCheckBox("诊断报告脱敏（隐藏 IP 地址）")
        self.check_mask.setToolTip("开启后诊断报告中 IP 地址脱敏（建议开启）")
        self.check_mask.setChecked(
            bool(self.ctx.settings.get("mask_diagnostics", True)))
        self.check_mask.toggled.connect(self._mask_changed)
        panel.add(self.check_mask)
        return panel

    def _build_about(self):
        """软件信息分区：env_info() 只读取一次并缓存。"""
        panel = GlassPanel("软件信息")
        self.env_grid = KVGrid()
        self.env_grid.add_row("软件版本", f"v{VERSION}", "version")
        self.env_grid.add_row("Python 版本", "--", "python")
        self.env_grid.add_row("OpenSSL 路径与版本", "--", "openssl")
        self.env_grid.add_row("本地监听地址", "--", "listen")
        self.env_grid.add_row("项目说明", "--", "desc")
        self.env_grid.add_row("开源许可证", "--", "license")
        panel.add(self.env_grid)
        self._load_env_info()
        return panel

    def _load_env_info(self):
        """运行环境信息只在页面构建时读取一次并缓存。"""
        self.env_grid.set_value("version", f"v{VERSION}")
        try:
            self._env = config_manager.env_info()
        except Exception as e:      # noqa: BLE001 - 页内展示错误即可
            self.env_grid.set_value("python", f"读取失败（{e}）")
            return
        info = self._env
        self.env_grid.set_value("python", info["python"])
        self.env_grid.set_value(
            "openssl", f"{info['openssl_path']} · {info['openssl_version']}")
        self.env_grid.set_value("listen", info["listen"])
        self.env_grid.set_value("desc", "本地网络代理管理与诊断工具")
        self.env_grid.set_value("license", "MIT（本项目自带）")

    # ------------------------------------------------------- 保存动作
    def _saved(self, what):
        self.saved_lab.setText(
            f"“{what}”已保存 · {time.strftime('%H:%M:%S')}")

    def _theme_changed(self, index):
        t = {0: "system", 1: "dark", 2: "light"}.get(index, "system")
        self.ctx.settings.set("theme", t)
        self._saved("主题")

    def _glass_changed(self, checked):
        self.ctx.settings.set("glass", bool(checked))
        self._saved("玻璃效果")

    def _strength_changed(self, value):
        self.strength_lab.setText(str(value))
        self.ctx.settings.set("glass_strength", int(value))
        self._saved("玻璃强度")

    def _anim_changed(self, checked):
        self.ctx.settings.set("animations", bool(checked))
        self._saved("动画")

    def _font_changed(self, index):
        self.ctx.settings.set("font_scale", int(index))
        self._saved("字体大小")

    def _level_changed(self, index):
        self.ctx.settings.set("log_level_filter", int(index))
        self._saved("默认日志级别")

    def _days_changed(self, value):
        self.ctx.settings.set("log_retention_days", int(value))
        self._saved("日志保留天数")

    def _show_changed(self, checked):
        self.ctx.settings.set("show_on_start", bool(checked))
        self._saved("启动行为")

    def _tray_changed(self, checked):
        self.ctx.settings.set("minimize_to_tray", bool(checked))
        self._saved("关闭行为")

    def _mask_changed(self, checked):
        self.ctx.settings.set("mask_diagnostics", bool(checked))
        self._saved("诊断脱敏")

    # ------------------------------------------------------- 外部同步
    def on_settings_changed(self, settings):
        """设置被其他入口改动时同步控件显示（阻断信号，不回写）。"""
        with QSignalBlocker(self.combo_theme):
            theme_map = {"system": 0, "dark": 1, "light": 2}
            self.combo_theme.setCurrentIndex(
                theme_map.get(settings.get("theme", "system"), 0))
        with QSignalBlocker(self.check_glass):
            self.check_glass.setChecked(bool(settings.get("glass", True)))
        with QSignalBlocker(self.slider_strength):
            self.slider_strength.setValue(
                int(settings.get("glass_strength", 60)))
        self.strength_lab.setText(str(self.slider_strength.value()))
        with QSignalBlocker(self.check_anim):
            self.check_anim.setChecked(
                bool(settings.get("animations", True)))
        with QSignalBlocker(self.combo_font):
            self.combo_font.setCurrentIndex(
                max(0, min(2, int(settings.get("font_scale", 0)))))
        with QSignalBlocker(self.combo_level):
            self.combo_level.setCurrentIndex(
                max(0, min(len(LOG_LEVELS) - 1,
                           int(settings.get("log_level_filter", 0)))))
        with QSignalBlocker(self.spin_days):
            self.spin_days.setValue(
                int(settings.get("log_retention_days", 14)))
        with QSignalBlocker(self.check_show):
            self.check_show.setChecked(
                bool(settings.get("show_on_start", True)))
        with QSignalBlocker(self.check_tray):
            self.check_tray.setChecked(
                bool(settings.get("minimize_to_tray", False)))
        with QSignalBlocker(self.check_mask):
            self.check_mask.setChecked(
                bool(settings.get("mask_diagnostics", True)))
