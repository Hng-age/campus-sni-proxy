"""One-shot environment diagnostics (pure checks, GUI runs them in a worker).

Every check returns (name, level, detail) where level is "ok" / "warn" /
"error". The report never includes secrets: only public hostnames, local
addresses and file presence are recorded.
"""

import os
import re
import socket
import ssl
import subprocess
import sys
import time

from sni_proxy import config

from . import cert_service, process_manager
from .util import run_hidden


def _check_env_python():
    ok = sys.version_info >= (3, 8)
    ver = f"{sys.version_info.major}.{sys.version_info.minor}." \
          f"{sys.version_info.micro}"
    return ("Python 运行环境",
            "ok" if ok else "error",
            f"当前 {ver}（{sys.executable}）" + ("" if ok else "，需要 3.8+"))


def _check_env_openssl():
    try:
        import cryptography
        crypto_ver = getattr(cryptography, "__version__", "")
    except ImportError:
        crypto_ver = None

    exe = config.OPENSSL
    if not os.path.exists(exe):
        try:
            import shutil
            exe = shutil.which("openssl") or exe
        except Exception:
            pass
    has_exe = os.path.exists(exe)

    if crypto_ver:
        detail = f"Python cryptography {crypto_ver}（纯代码内置，无需 Git / OpenSSL 外部依赖）"
        if has_exe:
            code, out, _ = run_hidden([exe, "version"], timeout=5)
            ossl_ver = out.strip().splitlines()[0] if (code == 0 and out.strip()) else "已就绪"
            detail += f" · 外部 OpenSSL 备用: {ossl_ver}"
        return ("证书生成与加密引擎", "ok", detail)

    if not has_exe:
        return ("证书生成与加密引擎", "warn",
                "未检测到 cryptography 或 openssl：已有证书可用，但新域名证书无法生成")
    code, out, _ = run_hidden([exe, "version"], timeout=10)
    ver = out.strip().splitlines()[0] if out.strip() else "未知版本"
    return ("证书生成与加密引擎", "ok" if code == 0 else "warn", f"OpenSSL CLI: {ver}（{exe}）")


def _check_interfaces():
    """Default routes / uplinks via route.exe (same logic as the proxy)."""
    code, out, _ = run_hidden(["route", "print", "-4"], timeout=15,
                              decode="mbcs")
    ips = []
    if code == 0:
        for line in out.splitlines():
            parts = line.split()
            if (len(parts) >= 5 and parts[0] == "0.0.0.0"
                    and parts[1] == "0.0.0.0"):
                ip = parts[3]
                if not ip.startswith(("127.", "169.254.")) and ip not in ips:
                    ips.append(ip)
    if not ips:
        return ("网络接口 / 默认路由", "error", "未检测到默认路由，本机可能未联网")
    if len(ips) == 1:
        return ("网络接口 / 默认路由", "ok", f"1 个网络出口：{ips[0]}")
    return ("网络接口 / 默认路由", "ok",
            f"{len(ips)} 个网络出口（代理将自动并发绑定）：{', '.join(ips)}")


def _check_dns():
    from sni_proxy.netutil import resolve_domain
    try:
        ips = resolve_domain("www.douyin.com")
    except Exception:
        ips = []
    if ips:
        return ("DNS 解析", "ok",
                f"公共 DNS 正常（www.douyin.com -> {len(ips)} 个 IP）")
    # fall back to the system resolver before declaring failure
    try:
        socket.getaddrinfo("www.baidu.com", 443)
    except Exception:
        return ("DNS 解析", "error", "DNS 解析失败，请检查本机网络")
    return ("DNS 解析", "warn",
            "公共 DNS 查询失败，已回退系统解析（校园网常见，代理可正常工作）")


def _check_port():
    snap_port = config.LISTEN_PORT
    listener = process_manager.find_listener_pid()
    if not listener:
        return ("本地监听端口", "ok",
                f"端口 {snap_port} 空闲，可以启动代理")
    ident = process_manager.proxy_identity(listener)
    if ident["identity"] == "pidfile":
        return ("本地监听端口", "ok",
                f"端口 {snap_port} 由本代理监听（PID {listener}）")
    if ident["identity"] == "py":
        return ("本地监听端口", "warn",
                f"端口 {snap_port} 被未验证的 Python 进程占用（PID {listener}），"
                "启动前请先确认并关闭")
    return ("本地监听端口", "error",
            f"端口 {snap_port} 被其他程序占用（PID {listener} "
            f"{ident['proc_name'] or ''}），请先关闭该程序")


def _check_system_proxy():
    from .status_monitor import _proxy_reg_state
    p = _proxy_reg_state()
    if not p["enabled"]:
        return ("系统代理配置", "ok",
                "系统代理关闭（仅启动代理模式 / 手动浏览器代理可用）")
    detail = f"系统代理开启：{p['server'] or '(未设置服务器)'}"
    backup = os.path.exists(
        os.path.join(config.BASE_DIR, "state", "proxy_state.json"))
    level = "ok" if backup else "warn"
    if backup:
        detail += "；已保存启动前备份，停止时会自动恢复"
    else:
        detail += "；未发现备份文件（若不是本工具设置的代理，请自行记录当前配置）"
    return ("系统代理配置", level, detail)


def _check_certificates():
    c = cert_service.read_cert_summary()
    if not c.exists:
        return ("证书状态", "warn",
                "设备证书尚未初始化（启动服务时会自动生成）")
    parts = []
    level = "ok"
    machine = cert_service.ca_installed(c.sha1, user_store=False)
    user = cert_service.ca_installed(c.sha1, user_store=True)
    if machine or user:
        parts.append("根证书已安装（机器库）" if machine
                     else "根证书已安装（当前用户库）")
    else:
        level = "warn"
        parts.append("根证书未安装（浏览器会显示证书警告）")
    if not cert_service.wildcard_ready():
        level = "warn"
        parts.append("通配符证书缺失（启动服务时会自动生成）")
    else:
        parts.append("通配符证书就绪")
    if c.is_expired():
        level = "error"
        parts.append("根证书已过期")
    elif c.days_left() is not None and c.days_left() < 30:
        level = "warn"
        parts.append(f"根证书将在 {c.days_left()} 天后过期")
    if c.not_after:
        parts.append(f"有效期至 {c.not_after:%Y-%m-%d}")
    return ("证书状态", level, "；".join(parts))


def _check_key_hygiene():
    rep = cert_service.key_acl_report()
    if not rep["exists"]:
        return ("私钥保护", "warn", "尚未生成 CA 私钥（启动服务时自动生成并加固）")
    if rep["restricted"] is True:
        return ("私钥保护", "ok",
                "CA 私钥 DACL 已加固（仅当前用户 / 管理员 / SYSTEM 可访问）")
    if rep["restricted"] is False:
        return ("私钥保护", "error",
                "CA 私钥存在过宽的访问授权，请重新运行服务以触发 ACL 加固")
    return ("私钥保护", "warn", "无法读取私钥 ACL 状态")


def _check_app_health():
    """App-level health probe: real CONNECT roundtrip through the proxy."""
    ident = process_manager.proxy_identity(
        process_manager.find_listener_pid())
    if not ident["running"]:
        return ("代理服务健康", "warn", "代理未运行（应用级探测跳过）")
    try:
        s = socket.create_connection(
            (config.LISTEN_HOST, config.LISTEN_PORT), timeout=6)
        try:
            s.settimeout(8)
            s.sendall(b"CONNECT www.baidu.com:443 HTTP/1.1\r\n"
                      b"Host: www.baidu.com:443\r\n\r\n")
            first = s.recv(1024).split(b"\r\n", 1)[0]
            if b" 200 " in first:
                return ("代理服务健康", "ok",
                        f"应用级探测通过（PID {ident['pid']}，CONNECT 200）")
            return ("代理服务健康", "error",
                    f"代理应答异常：{first.decode('iso-8859-1', 'replace')}")
        finally:
            s.close()
    except Exception as e:
        return ("代理服务健康", "error", f"应用级探测失败：{e}")


def _check_upstream_tls():
    """Direct TLS to a well-known edge, verifying the machine trust store."""
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection(("www.baidu.com", 443), timeout=6) as s:
            with ctx.wrap_socket(s, server_hostname="www.baidu.com") as ss:
                cert = ss.getpeercert()
                cn = dict(x[0] for x in cert.get("subject", ())).get(
                    "commonName", "未知")
        return ("上游 TLS 校验链", "ok", f"直连 TLS 握手与证书校验正常（{cn}）")
    except Exception as e:
        return ("上游 TLS 校验链", "error", f"直连 TLS 失败：{e}")


ALL_CHECKS = (
    _check_env_python,
    _check_env_openssl,
    _check_interfaces,
    _check_dns,
    _check_port,
    _check_system_proxy,
    _check_certificates,
    _check_key_hygiene,
    _check_app_health,
    _check_upstream_tls,
)


def run_all(mask=False, on_check=None):
    """Run every check; returns (results, report_text, started_at, seconds).

    on_check(result_dict) is called after each check completes (runs on the
    worker thread).
    """
    started = time.time()
    results = []
    for fn in ALL_CHECKS:
        try:
            name, level, detail = fn()
        except Exception as e:
            name, level, detail = fn.__name__, "error", f"检查异常：{e}"
        item = {"name": name, "level": level, "detail": detail}
        results.append(item)
        if on_check:
            try:
                on_check(dict(item))
            except Exception:
                pass

    if mask:
        results = [_mask(r) for r in results]
    seconds = round(time.time() - started, 1)
    return results, build_report(results, started, seconds), started, seconds


_IP_RE = re.compile(r"(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})")


def _mask_ip(text):
    return _IP_RE.sub(lambda m: f"{m.group(1)}.{m.group(2)}.x.x", text)


def _mask(result):
    d = dict(result)
    d["detail"] = _mask_ip(d["detail"])
    return d


def build_report(results, started, seconds):
    counts = {"ok": 0, "warn": 0, "error": 0}
    for r in results:
        counts[r["level"]] += 1
    lines = [
        "=" * 58,
        " SNI Proxy Desktop 环境诊断报告",
        f" 时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(started))}",
        f" 版本：v{config.VERSION}    耗时：{seconds}s",
        f" 汇总：正常 {counts['ok']} / 需要注意 {counts['warn']} / "
        f"异常 {counts['error']}",
        "=" * 58,
    ]
    level_cn = {"ok": "正常", "warn": "注意", "error": "异常"}
    for r in results:
        lines.append(f"\n[{level_cn[r['level']]}] {r['name']}")
        lines.append(f"  {r['detail']}")
    lines.append("\n说明：报告只包含本机环境信息，不含密码、令牌与私钥。")
    return "\n".join(lines)
