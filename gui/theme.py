"""Glassmorphism dark & light themes: palette + Qt stylesheet builder."""

FONT_FAMILY = '"Microsoft YaHei UI", "Segoe UI", "PingFang SC", sans-serif'
FONT_SCALES = [9, 10, 11]   # pt; index 0/1/2 = 标准 / 大 / 更大

DARK = {
    "id": "dark",
    "bg_top": "#0A0F1D",
    "bg_bottom": "#0D1527",
    "glow1": (37, 99, 235, 75),        # 蓝
    "glow2": (139, 92, 246, 65),       # 紫
    "sidebar": "rgba(13, 21, 39, 215)",
    "card_rgb": (17, 24, 42),
    "card_border": "rgba(56, 189, 248, 48)",
    "panel_solid": "rgba(17, 24, 42, 245)",
    "accent": "#2563EB",
    "accent2": "#3B82F6",
    "ok": "#10B981",
    "warn": "#F59E0B",
    "err": "#EF4444",
    "text": "#F8FAFC",
    "muted": "#94A3B8",
    "input_bg": "rgba(15, 23, 42, 210)",
    "view_bg": "rgba(15, 23, 42, 220)",
    "view_text": "#E2E8F0",
    "tooltip_bg": "#1E293B",
    "combo_popup": "#0F172A",
    "hover": "rgba(37, 99, 235, 45)",
    "danger": "#DC2626",
    "hero_bg1": "#0E1934",
    "hero_bg2": "#0A1228",
    "hero_border": "rgba(56, 189, 248, 0.35)",
}

LIGHT = {
    "id": "light",
    "bg_top": "#F8FAFC",              # 清爽明亮底色
    "bg_bottom": "#EDF2F7",
    "glow1": (199, 210, 254, 60),     # 柔和淡蓝光晕
    "glow2": (221, 214, 254, 50),     # 柔和淡紫光晕
    "sidebar": "rgba(255, 255, 255, 235)",
    "card_rgb": (255, 255, 255),
    "card_border": "rgba(203, 213, 225, 180)",
    "panel_solid": "rgba(255, 255, 255, 250)",
    "accent": "#2563EB",
    "accent2": "#3B82F6",
    "ok": "#10B981",
    "warn": "#D97706",
    "err": "#EF4444",
    "text": "#0F172A",                # 深黑文字，杜绝白字看不清
    "muted": "#64748B",
    "input_bg": "#FFFFFF",
    "view_bg": "#F8FAFC",
    "view_text": "#1E293B",
    "tooltip_bg": "#1E293B",
    "combo_popup": "#FFFFFF",
    "hover": "rgba(37, 99, 235, 25)",
    "danger": "#DC2626",
    "hero_bg1": "#EFF6FF",
    "hero_bg2": "#DBEAFE",
    "hero_border": "rgba(191, 219, 254, 200)",
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
        return 250 if is_light else 245
    strength = int(settings.get("glass_strength", 60))
    strength = max(0, min(100, strength))
    if is_light:
        return 185 + int(strength * 0.65)  # 185 .. 250
    return 60 + int(strength * 1.15)   # 60 .. 175


def build_qss(settings):
    p = palette(settings)
    alpha = card_alpha(settings)
    r, g, b = p["card_rgb"]
    card = f"rgba({r}, {g}, {b}, {alpha})"
    card_border = p["card_border"]
    font_pt = FONT_SCALES[max(0, min(len(FONT_SCALES) - 1,
                                     int(settings.get("font_scale", 0))))]
    small = font_pt - 1
    title = font_pt + 1

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
    #TitleLabel {{ font-size: {title}pt; font-weight: 600; color: {p['text']}; }}
    #BrandName {{ color: {p['text']}; font-size: {title}pt; font-weight: 600; }}
    #BrandVersion {{ color: {p['muted']}; font-size: {small - 1}pt; }}
    #TitleChip {{
        color: {p['muted']}; font-size: {small}pt;
        background: {card}; border: 1px solid {card_border};
        border-radius: 9px; padding: 2px 10px;
    }}
    QFrame#HLine {{ background: {card_border}; border: none; max-height: 1px; }}

    QPushButton {{
        color: {p['text']};
        background: {card};
        border: 1px solid {card_border};
        border-radius: 10px;
        padding: 6px 16px;
        font-size: {font_pt}pt;
    }}
    QPushButton:hover {{ border-color: {p['accent']}; background: {p['hover']}; }}
    QPushButton:pressed {{ background: {p['accent']}; color: #FFFFFF; }}
    QPushButton:disabled {{
        color: {p['muted']}; background: rgba({r}, {g}, {b}, 90);
        border-color: rgba(167, 181, 203, 20);
    }}
    QPushButton#Primary {{
        color: #FFFFFF; font-weight: 600; border: none;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {p['accent']}, stop:1 {p['accent2']});
    }}
    QPushButton#Primary:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {p['accent2']}, stop:1 {p['accent']});
    }}
    QPushButton#Primary:disabled {{
        background: rgba({r}, {g}, {b}, 100); color: rgba(255,255,255,120);
    }}
    QPushButton#Danger {{
        color: #FFFFFF; font-weight: 600; border: none;
        background: {p['danger']};
    }}
    QPushButton#Danger:hover {{ background: #c53838; }}
    QPushButton#Danger:disabled {{
        background: rgba(239, 100, 100, 90); color: rgba(255,255,255,120);
    }}
    QPushButton#WinBtn, QPushButton#WinBtnClose {{
        color: {p['muted']}; background: transparent; border: none;
        border-radius: 8px; min-width: 36px; min-height: 26px;
        font-size: {small}pt; padding: 0;
    }}
    QPushButton#WinBtn:hover {{ background: {p['hover']}; color: {p['text']}; }}
    QPushButton#WinBtnClose:hover {{ background: {p['danger']}; color: #FFFFFF; }}

    QLineEdit, QComboBox, QSpinBox {{
        background: {p['input_bg']}; color: {p['text']};
        border: 1px solid {card_border}; border-radius: 9px;
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

    QCheckBox {{ color: {p['text']}; spacing: 8px; background: transparent; }}
    QCheckBox::indicator {{
        width: 16px; height: 16px; border-radius: 5px;
        border: 1px solid {card_border}; background: {p['input_bg']};
    }}
    QCheckBox::indicator:hover {{ border-color: {p['accent']}; }}
    QCheckBox::indicator:checked {{ background: {p['accent']}; border-color: {p['accent']}; }}

    QPlainTextEdit, QTextEdit, QListWidget {{
        background: {p['view_bg']}; color: {p['view_text']};
        border: 1px solid {card_border}; border-radius: 12px;
        padding: 8px; font-family: Consolas, "Microsoft YaHei UI"; font-size: {small}pt;
    }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollArea > QWidget {{ background: transparent; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{
        background: {card_border}; border-radius: 5px; min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {p['accent']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{
        background: {card_border}; border-radius: 5px; min-width: 30px;
    }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

    #Sidebar {{
        background: {p['sidebar']};
        border: 1px solid {card_border};
        border-radius: 16px;
    }}
    #SidebarTip {{ color: {p['muted']}; font-size: {small - 1}pt; background: transparent; }}
    QPushButton#NavButton {{
        text-align: left; color: {p['muted']}; background: transparent;
        border: none; border-radius: 10px; padding: 9px 13px;
        font-size: {font_pt}pt;
    }}
    QPushButton#NavButton:hover {{ color: {p['text']}; background: {p['hover']}; }}
    QPushButton#NavButton:checked {{
        color: #FFFFFF; font-weight: 600;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {p['accent']}, stop:1 {p['accent2']});
    }}
    QPushButton#NavButton:disabled {{ color: rgba(167,181,203,90); background: transparent; }}

    #GlassPanel, #StatusCard, #MetricCard {{
        background-color: {card};
        border: 1px solid {card_border};
        border-radius: 16px;
    }}
    #StatusCard {{ border-radius: 14px; }}
    #PanelTitle {{
        color: {p['muted']}; font-size: {small}pt; font-weight: 600;
        background: transparent; border: none; padding: 0;
    }}
    #PanelHeaderTitle {{
        color: {p['text']}; font-size: 13pt; font-weight: 700;
        background: transparent; border: none; padding: 0;
    }}
    #CardGlyph {{ font-size: {title}pt; background: transparent; border: none; }}
    #CardTitle {{ color: {p['muted']}; font-size: {small}pt; background: transparent; border: none; padding: 0; }}
    #CardValue {{ color: {p['text']}; font-size: {title}pt; font-weight: 600; background: transparent; border: none; padding: 0; }}
    #CardValue[state="ok"] {{ color: {p['ok']}; }}
    #CardValue[state="warn"] {{ color: {p['warn']}; }}
    #CardValue[state="error"] {{ color: {p['err']}; }}
    #CardSub {{ color: {p['muted']}; font-size: {small - 1}pt; background: transparent; border: none; padding: 0; }}

    #MetricTitle {{ color: {p['muted']}; font-size: 9.5pt; background: transparent; }}
    #MetricValue {{ color: {p['text']}; font-size: 13.5pt; font-weight: 700; background: transparent; }}

    #TitleBarText {{ color: {p['muted']}; font-size: 10pt; background: transparent; font-weight: 500; }}
    #TitleBarClock {{ color: {p['muted']}; font-size: 9.5pt; background: transparent; font-family: monospace; }}

    #ItemText {{ color: {p['text']}; font-size: 10pt; background: transparent; }}
    #SysInfoLabel {{ color: {p['text']}; font-size: 9.5pt; background: transparent; }}
    #TimelineText {{ color: {p['text']}; font-size: 9.5pt; background: transparent; }}
    #TimelineTime {{ color: {p['muted']}; font-size: 9pt; font-family: monospace; background: transparent; }}

    #SecondaryBtn {{
        background: {card};
        border: 1px solid {card_border};
        border-radius: 12px;
        color: {p['text']};
        font-size: 11pt;
        font-weight: 600;
    }}
    #SecondaryBtn:hover {{
        background: {p['hover']};
        border-color: {p['accent']};
        color: {p['accent']};
    }}
    #SecondaryBtn:pressed {{
        background: rgba({r}, {g}, {b}, 220);
    }}

    #SecondaryBtnSmall {{
        background: {card};
        border: 1px solid {card_border};
        border-radius: 8px;
        color: {p['muted']};
        font-size: 9pt;
        padding: 4px 10px;
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
