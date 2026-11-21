"""Configuration and filesystem paths for the campus SNI proxy."""

import os
import shutil
import sys

VERSION = "2.1.0"

LISTEN_HOST = "127.0.0.1"
# 允许测试时用环境变量换端口，避免影响正在运行的 8888 实例
LISTEN_PORT = int(os.environ.get("SNI_PROXY_PORT", "8888"))

# package lives in <root>/sni_proxy, data files live in <root>/
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
    if not os.path.exists(os.path.join(BASE_DIR, "proxy_manager.ps1")):
        _parent_dir = os.path.dirname(BASE_DIR)
        if os.path.exists(os.path.join(_parent_dir, "proxy_manager.ps1")):
            BASE_DIR = _parent_dir
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CERT_DIR = os.path.join(BASE_DIR, "mitm_certs")
STRATEGY_FILE = os.path.join(CERT_DIR, "strategies.json")
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "proxy.log")
PID_FILE = os.path.join(BASE_DIR, "state", "proxy.pid")

CA_KEY = os.path.join(CERT_DIR, "ca.key")
CA_CERT = os.path.join(CERT_DIR, "ca_cert.crt")
CA_SERIAL = os.path.join(CERT_DIR, "ca_cert.srl")
WILDCARD_CERT = os.path.join(CERT_DIR, "_wildcard.crt")
WILDCARD_KEY = os.path.join(CERT_DIR, "_wildcard.key")
LEGACY_DIR = os.path.join(CERT_DIR, "legacy_1.0.2")
LEGACY_THUMB_FILE = os.path.join(CERT_DIR, "legacy_ca.thumbprint")

# 1.0.2 shipped one shared CA. Its private key must not be reused.
LEGACY_CA_SHA256 = "b4fa5edf50dfc8a54ed8727bc96a7e41cce963b3b64db123104dce1664d30671"

# Fast-path explicit SNI mapping (known good)
SNI_REWRITE = {
    "www.douyin.com": "douyin.com",
    "www.bilibili.com": "bilibili.com",
    "www.xiaohongshu.com": "xiaohongshu.com",
    "live.douyin.com": "douyin.com",
    "www.ixigua.com": "ixigua.com",
}

# Domains whose subdomains get MITM + SNI fallback treatment
BLOCKED_SUFFIXES = [
    "douyin.com", "iesdouyin.com", "douyinpic.com", "douyincdn.com", "douyinvod.com",
    "douyinstatic.com", "douyinvideo.net", "douyinlives.com", "amemv.com",
    "bytedance.com", "byted.org", "bytecdn.cn", "snssdk.com",
    "zijieapi.com", "zijiecdn.com", "toutiao.com", "ixigua.com", "pstatp.com",
    "bilibili.com", "biligame.com", "hdslb.com", "biliapi.net", "biliapi.com",
    "acgvideo.com", "bilivideo.com", "bilivideo.cn", "bvcip.com",
    "xiaohongshu.com", "xhscdn.com",
    "doubao.com",
    # video / short-video / audio
    "kuaishou.com", "yximgs.com",
    "iqiyi.com", "iqiyipic.com",
    "youku.com",
    "ximalaya.com", "xmcdn.com",
    "v.qq.com", "imgcache.qq.com", "vm.gtimg.cn", "puui.qpic.cn",
    "tv.sohu.com",
    # portals / other
    "ifeng.com", "ifengimg.com",
    "douban.com", "doubanio.com",
    "huawei.com",
    "bing.com", "bing.net", "cn.bing.com",
]

# Routed through the proxy but tunneled without MITM (upstream keeps its own
# certificate). Populated from rules.json at startup.
PASSTHROUGH_SUFFIXES = []

# Per-domain upstream TLS overrides, populated from rules.json at startup:
#   upstream_port_overrides: alternate upstream TLS port. The campus firewall
#     blocks TCP/443 to some edges (e.g. the Huawei WAF cluster serving
#     chat.deepseek.com), while the same WAF still serves the complete site on
#     an alternate TLS port, so the domain can be mapped onto it.
#   upstream_cert_pins: SHA-256 pin of the upstream leaf certificate for
#     domains whose override port serves a self-signed certificate. The pin
#     replaces chain/hostname verification for that route, so a changed or
#     intercepted upstream is still detected.
UPSTREAM_PORT_OVERRIDES = {}
UPSTREAM_CERT_PINS = {}

# Allowed SNI pool for fallback (the target edge must accept the SNI)
ALLOWED_SNI_POOL = [
    "www.zhihu.com",
    "douyin.com",
    "bilibili.com",
    "www.baidu.com",
    "www.qq.com",
    "www.163.com",
    "www.weibo.com",
]

# CDN edge pools are shared only inside the same family. A ByteDance edge
# completes TLS for *.xiaohongshu.com but then closes the connection, which
# shows up in browsers as HTTP 000, so pooled IPs must never cross families.
CDN_FAMILIES = {
    "bytedance": [
        "douyin.com", "iesdouyin.com", "douyinpic.com", "douyincdn.com",
        "douyinvod.com", "douyinstatic.com", "douyinvideo.net",
        "douyinlives.com", "amemv.com", "bytedance.com", "byted.org",
        "bytecdn.cn", "snssdk.com", "zijieapi.com", "zijiecdn.com",
        "toutiao.com", "ixigua.com", "pstatp.com", "doubao.com",
    ],
    "bilibili": [
        "bilibili.com", "biligame.com", "hdslb.com", "biliapi.net",
        "biliapi.com", "acgvideo.com", "bilivideo.com", "bilivideo.cn",
        "bvcip.com",
    ],
    "xiaohongshu": ["xiaohongshu.com", "xhscdn.com"],
    "kuaishou": ["kuaishou.com", "yximgs.com"],
}

# ByteDance CDN edges are shared between sibling hosts, but the campus/public
# DNS can return a mobile-only pool that is unreachable here (e.g.
# live.douyin.com -> 36.248.50.x). These siblings resolve to the live pool;
# their IPs are probed with the real host SNI, so a wrong edge is rejected by
# the certificate check instead of returning a 404 page.
CDN_SIBLING_HOSTS = {
    "douyin.com": ["i.snssdk.com", "tos-d-x-hl.snssdk.com", "gecko.zijieapi.com"],
    "iesdouyin.com": ["i.snssdk.com", "tos-d-x-hl.snssdk.com"],
    "amemv.com": ["i.snssdk.com"],
}

# Shared multi-SAN wildcard cert: covers each blocked suffix and its
# one-level subdomains, so new subdomains need no runtime openssl call.
EXTRA_WILDCARD_BASES = ["mcdn.bilivideo.cn", "mcdn.bilivideo.com"]
WILDCARD_BASES = list(dict.fromkeys(
    [s.lower() for s in BLOCKED_SUFFIXES] + EXTRA_WILDCARD_BASES))

# Upstream TLS: the certificate chain is always verified. 1.1.0 enables
# strict hostname verification by default: the upstream certificate must
# cover the original hostname. Set SNI_STRICT_UPSTREAM=0 only when you
# explicitly accept the compatibility trade-off for shared CDN edges.
STRICT_UPSTREAM = os.environ.get("SNI_STRICT_UPSTREAM", "1") != "0"

# Static asset / CDN domains: chain-valid but hostname-mismatched routes are
# allowed here even in strict mode, otherwise the page shell loads but its
# JS/CSS/images return 204 and the UI stays blank. API/document domains are
# not in this list and remain strictly hostname-verified.
# Set SNI_ASSET_COMPAT=0 to disable this exception (pure strict mode).
ASSET_COMPAT = os.environ.get("SNI_ASSET_COMPAT", "1") != "0"
ASSET_COMPAT_SUFFIXES = [
    "douyinstatic.com", "douyinpic.com", "douyincdn.com", "douyinvod.com",
    "douyinvideo.net", "bytecdn.cn", "pstatp.com",
    "hdslb.com", "bilivideo.com", "bilivideo.cn", "acgvideo.com",
    "xhscdn.com", "yximgs.com", "iqiyipic.com", "xmcdn.com",
    "qpic.cn", "gtimg.cn", "doubanio.com", "ifengimg.com", "mm.bing.net",
]

# openssl: env override (set by proxy_manager.ps1) -> Git for Windows -> PATH
OPENSSL = os.environ.get("OPENSSL_EXE") or r"C:\Program Files\Git\usr\bin\openssl.exe"
if not os.path.exists(OPENSSL):
    OPENSSL = shutil.which("openssl") or "openssl"

ATTEMPT_TIMEOUT = 2.5   # seconds per TLS attempt
NEG_CACHE_TTL = 300     # remember failed domains for 5 min

# subprocess flags: never flash console windows (pythonw + console exe)
NO_WINDOW = 0x08000000 if os.name == "nt" else 0

PROXY_MODE = "pac"
RULES_FILE = os.path.join(BASE_DIR, "rules.json")
PAC_FILE = os.path.join(BASE_DIR, "state", "proxy.pac")

try:
    from . import rules_manager
    rules_manager.load_rules()
except Exception:
    pass
