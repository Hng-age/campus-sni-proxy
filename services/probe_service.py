"""Smart domain probe and automated strategy learning service."""

import socket
import ssl
import time

from sni_proxy import config, rules_manager, upstream
from sni_proxy.logsetup import log, log_warning
from sni_proxy.netutil import (
    bare_domain,
    cert_covers,
    is_blocked_domain,
    resolve_domain,
    resolve_system,
)


def probe_domain_smart(domain, on_progress=None):
    """Diagnose if a domain is SNI-blocked and automatically probe a working proxy strategy.

    Calls `on_progress(step_message)` to report live progress.
    Returns dict with probe result details.
    """
    clean_domain = domain.strip().lower()
    if clean_domain.startswith("http://"):
        clean_domain = clean_domain[7:].split("/")[0]
    elif clean_domain.startswith("https://"):
        clean_domain = clean_domain[8:].split("/")[0]
    if ":" in clean_domain:
        clean_domain = clean_domain.split(":")[0]

    if not clean_domain:
        return {"success": False, "error": "请输入有效的域名"}

    bare = bare_domain(clean_domain)

    def _prog(msg):
        if on_progress:
            on_progress(msg)

    _prog(f"🔍 正在解析 {clean_domain} 的 DNS 记录...")
    ips = resolve_system(clean_domain)
    for ip in resolve_domain(clean_domain):
        if ip not in ips:
            ips.append(ip)

    if not ips:
        return {
            "success": False,
            "domain": clean_domain,
            "bare_domain": bare,
            "error": "DNS 解析失败：未找到有效 IP 地址，请检查拼写或网络连接",
        }

    _prog(f"📡 DNS 解析成功，发现 {len(ips)} 个 IP：{', '.join(ips[:4])}")

    # 1. 测试直接连通性（检测是否被校园网 SNI 阻断）
    _prog("⚡ 正在测试本机直连（检测是否存在校园网 SNI 阻断）...")
    is_blocked = False
    direct_ok = False
    direct_latency = 0.0

    t0 = time.time()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2.5)
        sock.connect((ips[0], 443))
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        tls_sock = ctx.wrap_socket(sock, server_hostname=clean_domain)
        tls_sock.settimeout(2.5)
        tls_sock.do_handshake()
        direct_latency = round((time.time() - t0) * 1000, 1)
        direct_ok = True
        tls_sock.close()
    except Exception as e:
        is_blocked = True
        direct_err = str(e)

    if direct_ok:
        _prog(f"ℹ️ 直连 TLS 正常（延迟 {direct_latency} ms），可能尚未被校园网阻断")
    else:
        _prog(f"⚠️ 直连失败/受阻：{clean_domain} 已被校园网 SNI 阻断或连接重置")

    # 2. 轮询伪装 SNI 与最优 IP 候选
    _prog("🎯 正在构建候选伪装 SNI 池并开始并发探测...")
    cands = []
    # 尝试自己的 IP + 各种 SNI
    snis_to_try = [clean_domain, bare]
    if clean_domain in config.SNI_REWRITE:
        snis_to_try.insert(0, config.SNI_REWRITE[clean_domain])
    for s in config.ALLOWED_SNI_POOL:
        if s not in snis_to_try:
            snis_to_try.append(s)

    for ip in ips[:6]:
        for sni in snis_to_try:
            cands.append((ip, sni, "probe"))

    _prog(f"🚀 发起 {len(cands)} 组策略并发握手测试...")
    t_start = time.time()
    ssock, winning_ip, winning_sni, _ = upstream.probe_first(
        cands, timeout=2.5, workers=min(16, len(cands)), deadline=6.0
    )
    elapsed = round((time.time() - t_start) * 1000, 1)

    if not ssock:
        _prog("❌ 探测完成：暂未找到可直接绕过的有效策略")
        return {
            "success": False,
            "domain": clean_domain,
            "bare_domain": bare,
            "is_blocked": is_blocked,
            "direct_ok": direct_ok,
            "direct_latency": direct_latency,
            "error": "所有候选伪装策略均握手超时或失败，目标服务器可能拒绝外部 SNI",
        }

    # 检查证书
    cert = ssock.getpeercert()
    covers_host = cert_covers(cert or {}, clean_domain) if cert else False
    ssock.close()

    level = "host" if covers_host else "chain"
    _prog(f"✅ 测通成功！最优 IP: {winning_ip} | 伪装 SNI: {winning_sni} | 耗时: {elapsed} ms")

    already_in_rules = is_blocked_domain(clean_domain)

    return {
        "success": True,
        "domain": clean_domain,
        "bare_domain": bare,
        "is_blocked": is_blocked,
        "direct_ok": direct_ok,
        "direct_latency": direct_latency,
        "best_ip": winning_ip,
        "best_sni": winning_sni,
        "latency_ms": elapsed,
        "verify_level": level,
        "covers_host": covers_host,
        "already_in_rules": already_in_rules,
        "recommended_suffix": bare if len(bare.split(".")) >= 2 else clean_domain,
        "message": f"成功测通！推荐使用伪装 SNI「{winning_sni}」经由边缘 IP「{winning_ip}」进行解封访问（耗时 {elapsed} ms）。",
    }


def apply_probe_result(result):
    """Save the probe result into rules.json and strategies.json, hot-reloading rules."""
    if not result or not result.get("success"):
        return False, "无效的探测结果"

    domain = result["domain"]
    suffix = result["recommended_suffix"]
    best_ip = result["best_ip"]
    best_sni = result["best_sni"]
    level = result.get("verify_level", "chain")

    # 1. 写入 rules.json 封锁后缀
    rules_manager.add_blocked_suffix(suffix)

    # 2. 如果 domain != best_sni，且不是主域名，可以写入 SNI_REWRITE
    if best_sni != domain and domain.startswith("www."):
        rules_manager.add_sni_rewrite(domain, best_sni)

    # 3. 写入 strategies.json 策略缓存
    cache = rules_manager.get_strategy_cache()
    entry = cache.setdefault(domain, {"endpoints": [], "fail_ts": None})
    endpoints = entry.get("endpoints", [])
    if not any(ep[0] == best_ip and ep[1] == best_sni for ep in endpoints):
        endpoints.insert(0, [best_ip, best_sni, level])
        del endpoints[5:]
    entry["endpoints"] = endpoints
    entry["fail_ts"] = None
    cache[domain] = entry

    import json
    try:
        with open(config.STRATEGY_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log_warning(f"failed to write strategies.json: {e}")

    # 同步到运行中 upstream 缓存
    try:
        with upstream._strategy_lock:
            upstream._strategy_cache[domain] = entry
    except Exception:
        pass

    rules_manager.export_pac_file()
    log(f"  [OK] Probe rule applied: {domain} (suffix={suffix}, sni={best_sni})")
    return True, f"已成功将 {domain}（后缀 {suffix}）加入分流规则与最优策略缓存！"
