"""GUI preferences, Windows startup registration and app metadata (Qt-free API)."""

import os
import sys

from sni_proxy import config

from .util import BASE_DIR, run_hidden

APP_NAME = "toci"
ORG_NAME = "toci"

AUTOSTART_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_VALUE_NAME = "toci"

DEFAULTS = {
    "theme": "system",          # system | dark | light
    "glass": True,              # 卡片半透明质感
    "glass_strength": 60,       # 卡片不透明度 0-100
    "animations": True,
    "font_scale": 0,            # index into FONT_SCALES
    "show_on_start": True,      # 启动时显示主窗口（False 则启动后隐藏到托盘）
    "minimize_to_tray": True,   # 关闭按钮最小化到托盘运行
    "log_level_filter": 0,      # 日志中心默认级别筛选（combo 索引）
    "log_retention_days": 14,
    "mask_diagnostics": True,   # 诊断报告 IP 脱敏
    "last_diag_time": "",
    "last_diag_summary": "",
}


def autostart_command():
    """Return the quoted command line registered under HKCU Run."""
    if getattr(sys, "frozen", False):
        return f'"{os.path.abspath(sys.executable)}" --minimized'
    py_exe = sys.executable
    pyw = os.path.join(os.path.dirname(os.path.abspath(py_exe)), "pythonw.exe")
    if os.path.isfile(pyw):
        py_exe = pyw
    main_script = os.path.join(BASE_DIR, "main.py")
    return f'"{py_exe}" "{main_script}" --minimized'


def is_autostart_enabled(reg_path=AUTOSTART_REG_PATH, value_name=AUTOSTART_VALUE_NAME):
    """True when Windows current-user Run entry exists for this app."""
    if os.name != "nt":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, value_name)
            return bool(str(val or "").strip())
    except OSError:
        return False


def set_autostart_enabled(enabled, reg_path=AUTOSTART_REG_PATH, value_name=AUTOSTART_VALUE_NAME):
    """Enable or disable launch-at-login in HKCU Run (no UAC needed)."""
    if os.name != "nt":
        return False, "仅支持 Windows 系统"
    try:
        import winreg
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_SET_VALUE
        ) as key:
            if enabled:
                winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, value_name)
                except FileNotFoundError:
                    pass
        return True, ""
    except OSError as e:
        return False, str(e)


def env_info():
    """Runtime versions shown in 设置中心 / 关于."""
    py = f"{sys.version_info.major}.{sys.version_info.minor}." \
         f"{sys.version_info.micro}"
    try:
        import cryptography
        crypto_ver = getattr(cryptography, "__version__", "")
    except ImportError:
        crypto_ver = ""
    ossl = config.OPENSSL
    found = os.path.exists(ossl)
    if not found:
        import shutil
        ossl = shutil.which("openssl") or ossl
        found = bool(ossl and os.path.exists(ossl))
    ossl_ver = ""
    if found:
        code, out, _ = run_hidden([ossl, "version"], timeout=10)
        if code == 0:
            ossl_ver = out.strip().splitlines()[0] if out.strip() else ""
    return {
        "version": config.VERSION,
        "python": py,
        "python_exe": sys.executable,
        "cryptography_version": crypto_ver or "内置可用",
        "openssl_path": ossl,
        "openssl_version": ossl_ver or "纯代码模式（无需 OpenSSL）",
        "openssl_found": found,
        "listen": f"{config.LISTEN_HOST}:{config.LISTEN_PORT}",
        "strict_upstream": config.STRICT_UPSTREAM,
        "asset_compat": config.ASSET_COMPAT,
    }
