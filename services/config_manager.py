"""GUI preferences and app metadata (QSettings-backed, Qt-free API).

The GUI layer owns the QSettings object; this module only defines the
schema, defaults and helpers so the settings stay consistent everywhere.
"""

import os

from sni_proxy import config

from .util import run_hidden

APP_NAME = "SNI Proxy Desktop"
ORG_NAME = "SNIProxy"

DEFAULTS = {
    "theme": "system",          # system | dark | light
    "glass": True,              # 玻璃拟态卡片
    "glass_strength": 60,       # 卡片不透明度 0-100
    "animations": True,
    "font_scale": 0,            # index into FONT_SCALES
    "show_on_start": True,      # 启动时显示主窗口
    "minimize_to_tray": False,  # 关闭按钮最小化到托盘
    "log_level_filter": 0,      # 日志中心默认级别筛选（combo 索引）
    "log_retention_days": 14,
    "mask_diagnostics": True,   # 诊断报告 IP 脱敏
    "last_diag_time": "",
    "last_diag_summary": "",
}


def env_info():
    """Runtime versions shown in 设置中心 / 关于."""
    import sys
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
