"""Clean minimalist light & dark themes: palette + Qt stylesheet builder."""

import os
import tempfile

FONT_FAMILY = '"Microsoft YaHei UI", "Segoe UI", "PingFang SC", sans-serif'
FONT_SCALES = [9, 10, 11]   # pt; index 0/1/2 = 标准 / 大 / 更大

DARK = {
    "id": "dark",
    "bg_top": "#0F141E",
    "bg_bottom": "#0F141E",
    "sidebar": "#151C28",
    "sidebar_border": "#232D3F",
    "card_rgb": (24, 32, 46),
    "card_border": "rgba(148, 163, 184, 38)",
    "panel_solid": "#18202E",
    "accent": "#3B82F6",
    "accent2": "#2563EB",
    "ok": "#10B981",
    "warn": "#F59E0B",
    "err": "#EF4444",
    "text": "#F1F5F9",
    "muted": "#94A3B8",
    "input_bg": "#111824",
    "view_bg": "#111824",
    "view_text": "#E2E8F0",
    "table_alt": "rgba(255, 255, 255, 8)",
    "table_header": "#1A2333",
    "tooltip_bg": "#1E293B",
    "combo_popup": "#18202E",
    "hover": "rgba(59, 130, 246, 28)",
    "danger": "#DC2626",
    "hero_bg1": "#18202E",
    "hero_bg2": "#18202E",
    "hero_border": "rgba(148, 163, 184, 42)",
}

LIGHT = {
    "id": "light",
    "bg_top": "#F5F7FA",
    "bg_bottom": "#F5F7FA",
    "sidebar": "#FFFFFF",
    "sidebar_border": "#E2E8F0",
    "card_rgb": (255, 255, 255),
    "card_border": "#E2E8F0",
    "panel_solid": "#FFFFFF",
    "accent": "#2563EB",
    "accent2": "#1D4ED8",
    "ok": "#059669",
    "warn": "#D97706",
    "err": "#DC2626",
    "text": "#0F172A",
    "muted": "#64748B",
    "input_bg": "#FFFFFF",
    "view_bg": "#F8FAFC",
    "view_text": "#1E293B",
    "table_alt": "#F8FAFC",
    "table_header": "#F1F5F9",
    "tooltip_bg": "#0F172A",
    "combo_popup": "#FFFFFF",
    "hover": "rgba(37, 99, 235, 18)",
    "danger": "#DC2626",
    "hero_bg1": "#FFFFFF",
    "hero_bg2": "#FFFFFF",
    "hero_border": "#E2E8F0",
}


def is_system_dark():
    """Detect if the OS/Desktop is currently in Dark Mode."""
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            hints = app.styleHints()
            if hasattr(hints, "colorScheme"):
                return hints.colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        pass
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return val == 0
    except Exception:
        return True


def resolve_theme_id(settings):
    theme_val = settings.get("theme", "system")
    if theme_val == "system":
        return "dark" if is_system_dark() else "light"
    return "light" if theme_val == "light" else "dark"


def palette(settings):
    return LIGHT if resolve_theme_id(settings) == "light" else DARK


def card_alpha(settings):
    """Card background alpha (0-255) from the glass strength setting."""
    is_light = resolve_theme_id(settings) == "light"
    if not settings.get("glass", True):
        return 255 if is_light else 248
    strength = int(settings.get("glass_strength", 60))
    strength = max(0, min(100, strength))
    if is_light:
        return 225 + int(strength * 0.30)  # 225 .. 255
    return 185 + int(strength * 0.65)      # 185 .. 250


_CHECK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" '
    'viewBox="0 0 16 16"><path d="M3.4 8.5l3.1 3.2 6.2-7.1" fill="none" '
    'stroke="#FFFFFF" stroke-width="2.2" stroke-linecap="round" '
    'stroke-linejoin="round"/></svg>'
)


def _check_icon_qss():
    """勾选框选中态的对勾图标：首次使用时写入临时目录并返回 QSS url()。"""
    try:
        path = os.path.join(tempfile.gettempdir(), "sni_proxy_qss", "check.svg")
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(_CHECK_SVG)
        return f'url("{path.replace(os.sep, "/")}")'
    except Exception:
        return ""


def build_qss(settings):
    p = palette(settings)
    alpha = card_alpha(settings)
    r, g, b = p["card_rgb"]
    card = f"rgba({r}, {g}, {b}, {alpha})"
    card_border = p["card_border"]
    font_pt = FONT_SCALES[max(0, min(len(FONT_SCALES) - 1,
                                     int(settings.get("font_scale", 0))))]
    small = font_pt - 1
    title = font_pt + 2

    check_icon = _check_icon_qss()
    check_img = f"image: {check_icon};" if check_icon else ""

    return f"""
    * {{
        font-family: {FONT_FAMILY};
        font-size: {font_pt}pt;
        outline: none;
    }}
    QMainWindow, QDialog {{ background: {p['bg_top']}; }}
    QLabel {{ color: {p['text']}; background: transparent; }}
    #MutedLabel {{ color: {p['muted']}; }}
    #TinyLabel {{ color: {p['muted']}; font-size: {small}pt; }}
    #TitleLabel {{ font-size: {title}pt; font-weight: 700; color: {p['text']}; }}
    #BrandName {{ color: {p['text']}; font-size: {title}pt; font-weight: 700; }}
    #BrandVersion {{ color: {p['muted']}; font-size: {small - 1}pt; }}
    #TitleChip {{
        color: {p['muted']}; font-size: {small}pt;
        background: {card}; border: 1px solid {card_border};
        border-radius: 8px; padding: 3px 10px;
    }}
    QFrame#HLine {{ background: {card_border}; border: none; max-height: 1px; }}

    QPushButton {{
        color: {p['text']};
        background: {card};
        border: 1px solid {card_border};
        border-radius: 8px;
        padding: 6px 14px;
        font-size: {font_pt}pt;
    }}
    QPushButton:hover {{ border-color: {p['accent']}; background: {p['hover']}; }}
    QPushButton:pressed {{ background: {p['accent']}; color: #FFFFFF; }}
    QPushButton:checked {{
        background: {p['accent']}; color: #FFFFFF;
        border-color: {p['accent']}; font-weight: 600;
    }}
    QPushButton:disabled {{
        color: {p['muted']}; background: rgba({r}, {g}, {b}, 95);
        border-color: rgba(148, 163, 184, 24);
    }}
    QPushButton#Primary {{
        color: #FFFFFF; font-weight: 600; border: none;
        background: {p['accent']};
    }}
    QPushButton#Primary:hover {{ background: {p['accent2']}; }}
    QPushButton#Primary:disabled {{
        background: rgba({r}, {g}, {b}, 110); color: rgba(255,255,255,130);
    }}
    QPushButton#Danger {{
        color: #FFFFFF; font-weight: 600; border: none;
        background: {p['danger']};
    }}
    QPushButton#Danger:hover {{ background: #B91C1C; }}
    QPushButton#Danger:disabled {{
        background: rgba(220, 38, 38, 95); color: rgba(255,255,255,130);
    }}
    QPushButton#WinBtn, QPushButton#WinBtnClose {{
        color: {p['muted']}; background: transparent; border: none;
        border-radius: 6px; min-width: 32px; min-height: 26px;
        font-size: {small}pt; padding: 0 6px;
    }}
    QPushButton#WinBtn:hover {{ background: {p['hover']}; color: {p['text']}; }}
    QPushButton#WinBtnClose:hover {{ background: {p['danger']}; color: #FFFFFF; }}

    QLineEdit, QComboBox, QSpinBox {{
        background: {p['input_bg']}; color: {p['text']};
        border: 1px solid {card_border}; border-radius: 8px;
        padding: 5px 10px; selection-background-color: {p['accent']};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {p['accent']}; }}
    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {p['combo_popup']}; color: {p['text']};
        border: 1px solid {card_border};
        selection-background-color: {p['accent']}; selection-color: #FFFFFF;
    }}
    QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; border: none; }}

    QRadioButton {{ color: {p['text']}; spacing: 8px; background: transparent; }}
    QCheckBox {{ color: {p['text']}; spacing: 8px; background: transparent; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px; border-radius: 4px;
        border: 1px solid {card_border}; background: {p['input_bg']};
    }}
    QCheckBox::indicator:hover {{ border-color: {p['accent']}; }}
    QCheckBox::indicator:checked {{
        background: {p['accent']}; border-color: {p['accent']};
        {check_img}
    }}
    QCheckBox::indicator:checked:hover {{ background: {p['accent2']}; border-color: {p['accent2']}; }}
    QCheckBox::indicator:disabled {{ border-color: rgba(148, 163, 184, 60); }}

    QPlainTextEdit, QTextEdit, QListWidget {{
        background: {p['view_bg']}; color: {p['view_text']};
        border: 1px solid {card_border}; border-radius: 10px;
        padding: 8px; font-family: Consolas, "Microsoft YaHei UI"; font-size: {small}pt;
    }}

    QTableWidget {{
        background: {p['view_bg']};
        alternate-background-color: {p['table_alt']};
        color: {p['view_text']};
        border: 1px solid {card_border};
        border-radius: 10px;
        gridline-color: {card_border};
        selection-background-color: {p['hover']};
        selection-color: {p['text']};
    }}
    QHeaderView::section {{
        background: {p['table_header']};
        color: {p['muted']};
        font-weight: 600;
        border: none;
        border-bottom: 1px solid {card_border};
        padding: 6px 8px;
    }}

    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget {{ background: transparent; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
    QScrollBar::handle:vertical {{
        background: {card_border}; border-radius: 4px; min-height: 28px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {p['accent']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
    QScrollBar::handle:horizontal {{
        background: {card_border}; border-radius: 4px; min-width: 28px;
    }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    #Sidebar {{
        background: {p['sidebar']};
        border: 1px solid {p['sidebar_border']};
        border-radius: 12px;
    }}
    #SidebarTip {{ color: {p['muted']}; font-size: {small - 1}pt; background: transparent; }}
    QPushButton#NavButton {{
        text-align: left; color: {p['muted']}; background: transparent;
        border: none; border-radius: 8px; padding: 7px 12px;
        font-size: {font_pt}pt;
    }}
    QPushButton#NavButton:hover {{ color: {p['text']}; background: {p['hover']}; }}
    QPushButton#NavButton:checked {{
        color: #FFFFFF; font-weight: 600;
        background: {p['accent']};
    }}
    QPushButton#NavButton:disabled {{ color: rgba(148,163,184,90); background: transparent; }}

    #GlassPanel, #StatusCard, #MetricCard {{
        background-color: {card};
        border: 1px solid {card_border};
        border-radius: 12px;
    }}
    #StatusCard {{ border-radius: 10px; }}
    #PanelTitle {{
        color: {p['muted']}; font-size: {small}pt; font-weight: 600;
        background: transparent; border: none; padding: 0;
    }}
    #PanelHeaderTitle {{
        color: {p['text']}; font-size: 11.5pt; font-weight: 700;
        background: transparent; border: none; padding: 0;
    }}
    #CardGlyph {{ font-size: {title}pt; background: transparent; border: none; }}
    #CardTitle {{ color: {p['muted']}; font-size: {small}pt; background: transparent; border: none; padding: 0; }}
    #CardValue {{ color: {p['text']}; font-size: {title}pt; font-weight: 600; background: transparent; border: none; padding: 0; }}
    #CardValue[state="ok"] {{ color: {p['ok']}; }}
    #CardValue[state="warn"] {{ color: {p['warn']}; }}
    #CardValue[state="error"] {{ color: {p['err']}; }}
    #CardSub {{ color: {p['muted']}; font-size: {small - 1}pt; background: transparent; border: none; padding: 0; }}

    #MetricTitle {{ color: {p['muted']}; font-size: 9pt; background: transparent; }}
    #MetricValue {{ color: {p['text']}; font-size: 13pt; font-weight: 700; background: transparent; }}

    #TitleBarText {{ color: {p['muted']}; font-size: 9.5pt; background: transparent; font-weight: 500; }}
    #ItemText {{ color: {p['text']}; font-size: 9.5pt; background: transparent; }}
    #SysInfoLabel {{ color: {p['text']}; font-size: 9pt; background: transparent; }}
    #TimelineText {{ color: {p['text']}; font-size: 9pt; background: transparent; }}
    #TimelineTime {{ color: {p['muted']}; font-size: 8.5pt; font-family: Consolas, monospace; background: transparent; }}

    #SecondaryBtn {{
        background: {card};
        border: 1px solid {card_border};
        border-radius: 8px;
        color: {p['text']};
        font-size: 10pt;
        font-weight: 600;
    }}
    #SecondaryBtn:hover {{
        background: {p['hover']};
        border-color: {p['accent']};
        color: {p['accent']};
    }}
    #SecondaryBtn:pressed {{ background: {card}; }}

    #SecondaryBtnSmall {{
        background: {card};
        border: 1px solid {card_border};
        border-radius: 6px;
        color: {p['muted']};
        font-size: 8.5pt;
        padding: 3px 10px;
    }}
    #SecondaryBtnSmall:hover {{
        background: {p['hover']};
        color: {p['accent']};
        border-color: {p['accent']};
    }}

    #KVKey {{ color: {p['muted']}; font-size: {small}pt; background: transparent; }}
    #KVValue {{ color: {p['text']}; font-size: {font_pt}pt; font-weight: 600; background: transparent; }}

    QToolTip {{
        background: {p['tooltip_bg']}; color: #FFFFFF;
        border: 1px solid {card_border}; padding: 4px 8px;
    }}
    """


def state_color(settings, state):
    p = palette(settings)
    return {"ok": p["ok"], "warn": p["warn"], "err": p["err"],
            "idle": p["muted"]}.get(state, p["muted"])


def apply_theme(app, settings):
    app.setStyleSheet(build_qss(settings))
