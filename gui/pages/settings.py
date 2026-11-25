"""设置中心页：系统与托盘（含开机自启开关）、外观、日志与安全、关于软件。"""

import time

from PySide6.QtCore import QRectF, QSignalBlocker, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget,
)

from gui.components.glass_panel import GlassPanel, KVGrid
from services import config_manager
from sni_proxy.config import VERSION
from .base import Page

LOG_LEVELS = ("全部", "INFO 及以上", "WARNING 及以上", "仅 ERROR", "含 DEBUG")


class ToggleSwitch(QCheckBox):
    """Minimalist pill toggle switch built on QCheckBox for full signal compatibility."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)

    def sizeHint(self):
        sh = super().sizeHint()
        sh.setHeight(max(sh.height(), 24))
        sh.setWidth(sh.width() + 26)
        return sh

    def hitButton(self, pos):
        return self.rect().contains(pos)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        h = self.height()
        track_w, track_h = 38, 20
        track_y = (h - track_h) / 2.0
        track_rect = QRectF(0, track_y, track_w, track_h)

        checked = self.isChecked()
        enabled = self.isEnabled()
        if checked:
            bg = QColor("#2563EB") if enabled else QColor("#64748B")
        else:
            bg = QColor(148, 163, 184, 95)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(track_rect, track_h / 2.0, track_h / 2.0)

        knob_d = 14.0
        knob_x = (track_w - knob_d - 3.0) if checked else 3.0
        knob_y = track_y + (track_h - knob_d) / 2.0
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(knob_x, knob_y, knob_d, knob_d))

        # Label text using inherited palette color
        text_rect = QRectF(track_w + 10, 0, max(0, self.width() - track_w - 10), h)
        p.setPen(self.palette().windowText().color())
        p.setFont(self.font())
        p.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, self.text())
        p.end()


class SettingsPage(Page):
    """简洁设置中心：开机自启、托盘驻留、外观与安全设置。"""

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
        body_v.setContentsMargins(20, 16, 20, 16)
        body_v.setSpacing(12)
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
        sub = QLabel("所有设置改动即时生效并自动保存")
        sub.setObjectName("MutedLabel")
        title_col.addWidget(title)
        title_col.addWidget(sub)
        head.addLayout(title_col)
        head.addStretch(1)
        body_v.addLayout(head)

        # ---- 四个简洁分区
        body_v.addWidget(self._build_system_tray())
        body_v.addWidget(self._build_appearance())
        body_v.addWidget(self._build_app_and_security())
        body_v.addWidget(self._build_about())

        foot = QHBoxLayout()
        self.saved_lab = QLabel("")
        self.saved_lab.setObjectName("TinyLabel")
        foot.addWidget(self.saved_lab)
        foot.addStretch(1)
        ver = QLabel(f"toci v{VERSION} · MIT 许可证")
        ver.setObjectName("TinyLabel")
        foot.addWidget(ver)
        body_v.addLayout(foot)
        body_v.addStretch(1)

    # -------------------------------------------------------- builders
    @staticmethod
    def _row(grid, row, key, field):
        lab = QLabel(key)
        lab.setObjectName("KVKey")
        grid.addWidget(lab, row, 0, Qt.AlignVCenter)
        if isinstance(field, QWidget):
            grid.addWidget(field, row, 1)
        else:
            grid.addLayout(field, row, 1)

    def _build_system_tray(self):
        """系统启动与托盘运行分区。"""
        panel = GlassPanel("启动与系统托盘")
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)

        self.check_autostart = ToggleSwitch("开机自动启动（登录 Windows 时自动运行，免提权）")
        self.check_autostart.setToolTip("写入当前用户启动项 HKCU\\...\\Run，开机后静默启动到系统托盘")
        self._row(grid, 0, "开机自启", self.check_autostart)

        self.check_show = ToggleSwitch("启动时显示主窗口（关闭则启动后隐藏到托盘）")
        self.check_show.setToolTip("关闭后每次打开软件仅驻留在右下角系统托盘")
        self._row(grid, 1, "启动显示", self.check_show)

        self.check_tray = ToggleSwitch("点击关闭按钮时隐藏到托盘后台运行")
        self.check_tray.setToolTip("开启后点右上角 ✕ 会隐藏到托盘而不是退出程序；右键托盘图标可完全退出")
        self._row(grid, 2, "托盘驻留", self.check_tray)

        tray_action_row = QHBoxLayout()
        tray_action_row.setSpacing(10)
        self.btn_hide_tray = QPushButton("隐藏到系统托盘")
        self.btn_hide_tray.setCursor(Qt.PointingHandCursor)
        self.btn_hide_tray.setToolTip("立即隐藏主窗口，保留程序在右下角托盘运行")
        self.btn_hide_tray.clicked.connect(self._hide_to_tray_now)
        tray_action_row.addWidget(self.btn_hide_tray)
        tray_action_row.addStretch(1)
        self._row(grid, 3, "快捷操作", tray_action_row)

        s = self.ctx.settings
        self.check_autostart.setChecked(config_manager.is_autostart_enabled())
        self.check_show.setChecked(bool(s.get("show_on_start", True)))
        self.check_tray.setChecked(bool(s.get("minimize_to_tray", True)))

        self.check_autostart.toggled.connect(self._autostart_changed)
        self.check_show.toggled.connect(self._show_changed)
        self.check_tray.toggled.connect(self._tray_changed)

        panel.add_layout(grid)
        return panel

    def _build_appearance(self):
        """外观分区：主题 / 卡片质感 / 动画 / 字体。"""
        panel = GlassPanel("外观")
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)

        self.combo_theme = QComboBox()
        self.combo_theme.addItems(["跟随系统", "深色模式", "浅色模式"])
        self._row(grid, 0, "主题配色", self.combo_theme)

        self.combo_font = QComboBox()
        self.combo_font.addItems(["标准", "大", "更大"])
        self._row(grid, 1, "字体大小", self.combo_font)

        self.check_glass = ToggleSwitch("启用卡片半透明效果")
        self._row(grid, 2, "卡片质感", self.check_glass)

        slider_row = QHBoxLayout()
        slider_row.setSpacing(10)
        self.slider_strength = QSlider(Qt.Horizontal)
        self.slider_strength.setRange(0, 100)
        self.strength_lab = QLabel("60")
        self.strength_lab.setObjectName("MutedLabel")
        slider_row.addWidget(self.slider_strength, 1)
        slider_row.addWidget(self.strength_lab)
        self._row(grid, 3, "卡片不透明度", slider_row)

        self.check_anim = ToggleSwitch("启用过渡动画")
        self._row(grid, 4, "界面动画", self.check_anim)

        s = self.ctx.settings
        theme_map = {"system": 0, "dark": 1, "light": 2}
        self.combo_theme.setCurrentIndex(theme_map.get(s.get("theme", "system"), 0))
        self.combo_font.setCurrentIndex(max(0, min(2, int(s.get("font_scale", 0)))))
        self.check_glass.setChecked(bool(s.get("glass", True)))
        self.slider_strength.setValue(int(s.get("glass_strength", 60)))
        self.strength_lab.setText(str(self.slider_strength.value()))
        self.check_anim.setChecked(bool(s.get("animations", True)))

        self.combo_theme.currentIndexChanged.connect(self._theme_changed)
        self.combo_font.currentIndexChanged.connect(self._font_changed)
        self.check_glass.toggled.connect(self._glass_changed)
        self.slider_strength.valueChanged.connect(self._strength_changed)
        self.check_anim.toggled.connect(self._anim_changed)

        panel.add_layout(grid)
        return panel

    def _build_app_and_security(self):
        """日志与安全策略分区。"""
        panel = GlassPanel("日志与安全")
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)

        self.combo_level = QComboBox()
        self.combo_level.addItems(list(LOG_LEVELS))
        self._row(grid, 0, "默认日志级别", self.combo_level)

        self.spin_days = QSpinBox()
        self.spin_days.setRange(1, 365)
        self._row(grid, 1, "日志保留天数", self.spin_days)

        self.check_mask = ToggleSwitch("诊断报告脱敏（隐藏敏感 IP 地址）")
        self._row(grid, 2, "隐私保护", self.check_mask)

        s = self.ctx.settings
        self.combo_level.setCurrentIndex(
            max(0, min(len(LOG_LEVELS) - 1, int(s.get("log_level_filter", 0)))))
        self.spin_days.setValue(int(s.get("log_retention_days", 14)))
        self.check_mask.setChecked(bool(s.get("mask_diagnostics", True)))

        self.combo_level.currentIndexChanged.connect(self._level_changed)
        self.spin_days.valueChanged.connect(self._days_changed)
        self.check_mask.toggled.connect(self._mask_changed)

        panel.add_layout(grid)

        kv = KVGrid()
        kv.add_row("上游 TLS 严格校验", "固定启用", "strict")
        kv.add_row("系统代理异常退出恢复", "启用", "restore")
        panel.add(kv)
        return panel

    def _build_about(self):
        """软件信息分区。"""
        panel = GlassPanel("软件信息")
        self.env_grid = KVGrid()
        self.env_grid.add_row("软件版本", f"v{VERSION}", "version")
        self.env_grid.add_row("Python 版本", "--", "python")
        self.env_grid.add_row("证书引擎", "--", "crypto")
        self.env_grid.add_row("本地监听地址", "--", "listen")
        panel.add(self.env_grid)
        self._load_env_info()
        return panel

    def _load_env_info(self):
        self.env_grid.set_value("version", f"v{VERSION}")
        try:
            self._env = config_manager.env_info()
        except Exception as e:
            self.env_grid.set_value("python", f"读取失败（{e}）")
            return
        info = self._env
        self.env_grid.set_value("python", info["python"])
        self.env_grid.set_value(
            "crypto", f"cryptography {info.get('cryptography_version', '')}".strip())
        self.env_grid.set_value("listen", info["listen"])

    # ------------------------------------------------------- 保存动作
    def activate(self):
        with QSignalBlocker(self.check_autostart):
            self.check_autostart.setChecked(config_manager.is_autostart_enabled())

    def _saved(self, what):
        self.saved_lab.setText(f"“{what}”已保存 · {time.strftime('%H:%M:%S')}")

    def _autostart_changed(self, checked):
        ok, err = config_manager.set_autostart_enabled(bool(checked))
        if not ok:
            with QSignalBlocker(self.check_autostart):
                self.check_autostart.setChecked(config_manager.is_autostart_enabled())
            QMessageBox.warning(self, "开机自启设置失败", f"无法写入注册表启动项：{err}")
            return
        self._saved("开机自启已开启" if checked else "开机自启已关闭")

    def _hide_to_tray_now(self):
        if hasattr(self.ctx, "_hide_to_tray"):
            self.ctx._hide_to_tray()

    def _theme_changed(self, index):
        t = {0: "system", 1: "dark", 2: "light"}.get(index, "system")
        self.ctx.settings.set("theme", t)
        self._saved("主题")

    def _glass_changed(self, checked):
        self.ctx.settings.set("glass", bool(checked))
        self._saved("卡片质感")

    def _strength_changed(self, value):
        self.strength_lab.setText(str(value))
        self.ctx.settings.set("glass_strength", int(value))
        self._saved("卡片不透明度")

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
        self._saved("启动显示")

    def _tray_changed(self, checked):
        self.ctx.settings.set("minimize_to_tray", bool(checked))
        self._saved("托盘驻留")

    def _mask_changed(self, checked):
        self.ctx.settings.set("mask_diagnostics", bool(checked))
        self._saved("诊断脱敏")

    # ------------------------------------------------------- 外部同步
    def on_settings_changed(self, settings):
        with QSignalBlocker(self.combo_theme):
            theme_map = {"system": 0, "dark": 1, "light": 2}
            self.combo_theme.setCurrentIndex(
                theme_map.get(settings.get("theme", "system"), 0))
        with QSignalBlocker(self.check_glass):
            self.check_glass.setChecked(bool(settings.get("glass", True)))
        with QSignalBlocker(self.slider_strength):
            self.slider_strength.setValue(int(settings.get("glass_strength", 60)))
        self.strength_lab.setText(str(self.slider_strength.value()))
        with QSignalBlocker(self.check_anim):
            self.check_anim.setChecked(bool(settings.get("animations", True)))
        with QSignalBlocker(self.combo_font):
            self.combo_font.setCurrentIndex(max(0, min(2, int(settings.get("font_scale", 0)))))
        with QSignalBlocker(self.combo_level):
            self.combo_level.setCurrentIndex(
                max(0, min(len(LOG_LEVELS) - 1, int(settings.get("log_level_filter", 0)))))
        with QSignalBlocker(self.spin_days):
            self.spin_days.setValue(int(settings.get("log_retention_days", 14)))
        with QSignalBlocker(self.check_show):
            self.check_show.setChecked(bool(settings.get("show_on_start", True)))
        with QSignalBlocker(self.check_tray):
            self.check_tray.setChecked(bool(settings.get("minimize_to_tray", True)))
        with QSignalBlocker(self.check_mask):
            self.check_mask.setChecked(bool(settings.get("mask_diagnostics", True)))
