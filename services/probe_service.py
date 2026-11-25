"""Smart domain probe and automated strategy learning service (v2).

v2 changes — why v1 probes "basically did not work":

1. HTTP-validated strategies. v1 declared a candidate successful as soon as
   the TLS handshake completed, so shared-CDN edges that handshake fine but
   then answer 404/418 (e.g. TencentEdgeOne answers 418 to a foreign SNI)
   produced "winning" rules that never worked in a browser. Every candidate
   is now validated with a real HTTP GET carrying the target Host header,
   and only app-level responses count (redirects must have a Location,
   plain bodies must have content; 418/5xx do not count).

2. Alternate TLS ports. Campus firewalls typically block TCP/443 to whole
   edge ranges instead of filtering SNI (verified: Huawei WAF ranges serving
   deepseek are dead on 443 while the same WAF serves the complete site on
   8443). The probe now races 443 plus 8443/2053/2083/2087/2096 with the
   real SNI and recommends an upstream port override instead of SNI
   masquerade whenever the real SNI works.

3. Certificate classification. A winning alternate-port edge either passes
   strict chain+hostname verification (no extra rule needed) or serves a
   self-signed WAF certificate; the latter is applied as a SHA-256
   certificate pin (`upstream_cert_pins`) so the route stays tamper-evident.

4. Direct check with real HTTP. Healthy sites are reported as "no rule
   needed" instead of being wrapped into needless MITM rules.

5. Exact-host suffix for port overrides. v1 always added the bare domain as
   the MITM suffix, which would hijack sibling subdomains that live on
   other edges (adding deepseek.com for chat.deepseek.com would also grab
   api.deepseek.com). Port override rules use the exact host.
"""

import hashlib
import json
import queue
import socket
import ssl
import threading
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

# Alternate TLS ports raced with the real SNI (Cloudflare-style alt ports
# plus the Huawei WAF service port verified to serve full sites on 8443).
ALT_TLS_PORTS = (8443, 2053, 2083, 2087, 2096)

# App-level HTTP statuses accepted as "the real site answered".
# 418 is excluded on purpose: TencentEdgeOne answers it to foreign SNI/Host.
# 5xx is excluded to stay conservative about wrong-edge 502/503 pages.
# 204/206/304 are excluded: a plain GET / never legitimately returns them,
# and empty-range bodies carry no usable evidence.
_REAL_STATUSES = frozenset(
    (200, 201, 202, 301, 302, 303, 307, 308,
     400, 401, 403, 404, 405, 410, 451)
)

_MAX_HTTP_SAMPLE = 65536


def _norm_domain(domain):
    """Extract a clean hostname from user input ('' if invalid)."""
    clean = (domain or "").strip().lower()
    if clean.startswith("http://"):
        clean = clean[7:]
    elif clean.startswith("https://"):
        clean = clean[8:]
    # 带路径的输入（如 chat.deepseek.com/a/b，无论是否带协议头）一律截断
    if "/" in clean:
        clean = clean.split("/")[0]
    if ":" in clean:
        clean = clean.split(":")[0]
    if clean.endswith("."):
        clean = clean[:-1]
    return clean


def _http_probe_once(ip, port, sni, host, timeout=4.0):
    """TLS (unverified) + a real HTTP GET with the target Host header.

    Returns evidence dict or None. Certificate data is captured so the
    winner can be classified without a second connection.
    """
    ss = None
    try:
        raw = socket.create_connection((ip, port), timeout=timeout)
    except Exception:
        return None
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ss = ctx.wrap_socket(raw, server_hostname=sni)
        ss.settimeout(timeout)
        try:
            der = ss.getpeercert(binary_form=True)
        except Exception:
            der = None
        ss.sendall(
            ("GET / HTTP/1.1\r\n"
             f"Host: {host}\r\n"
             "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)\r\n"
             "Accept: */*\r\n"
             "Connection: close\r\n\r\n").encode("ascii")
        )
        data = b""
        while len(data) < _MAX_HTTP_SAMPLE:
            chunk = ss.recv(_MAX_HTTP_SAMPLE)
            if not chunk:
                break
            data += chunk
    except Exception:
        # TLS 握手或请求失败：ss 尚未建立时 raw 也要显式关闭，
        # 不能依赖 GC 兜底（长探测循环会累积 TIME_WAIT/句柄）
        try:
            raw.close()
        except Exception:
            pass
        return None
    finally:
        if ss is not None:
            try:
                ss.close()
            except Exception:
                pass
    if not data or b"\r\n" not in data:
        return None
    head, _, body = data.partition(b"\r\n\r\n")
    lines = head.decode("iso-8859-1", "replace").split("\r\n")
    try:
        status = int(lines[0].split(" ")[1])
    except (IndexError, ValueError):
        return None
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    return {
        "status": status,
        "server": headers.get("server", ""),
        "content_type": headers.get("content-type", ""),
        "content_length": headers.get("content-length", ""),
        "set_cookie": headers.get("set-cookie", ""),
        "location": headers.get("location", ""),
        "body_len": len(body),
        "cert_der": der,
        "cert_sha256": hashlib.sha256(der).hexdigest() if der else "",
    }


def _looks_real(ev):
    """True when the HTTP evidence looks like the real site answered."""
    if not ev:
        return False
    status = ev.get("status", 0)
    if status not in _REAL_STATUSES:
        return False
    if status in (301, 302, 303, 307, 308):
        return bool(ev.get("location"))
    if status < 300:
        # 2xx：必须有内容证据（空 200 与假通难以区分）
        return ev.get("body_len", 0) > 0 or bool(ev.get("content_type"))
    # 4xx：来自真实边缘的正常业务响应（401 未授权 / 404 路径不存在等）。
    # 真实边缘的 4xx 带有明确的服务端特征头（Server / Content-Length /
    # Set-Cookie，如 harness.deepseek.com 的裸 404: Server=CW, CL=0）；
    # 418（边缘拒绝伪装 SNI）与 5xx 已在状态集合中排除。
    return (ev.get("body_len", 0) > 0
            or bool(ev.get("content_type"))
            or bool(ev.get("server"))
            or "content_length" in ev
            or "set_cookie" in ev)


def _race(host, cands, per_timeout=4.0, deadline=14.0, max_workers=24):
    """Race (ip, port, sni) candidates; first HTTP-real response wins.

    Returns (ip, port, sni, evidence) or None.
    """
    if not cands:
        return None
    todo = queue.Queue()
    for c in cands:
        todo.put(c)
    winner = threading.Event()
    result = []
    lock = threading.Lock()

    def worker():
        while not winner.is_set():
            try:
                ip, port, sni = todo.get(timeout=0.2)
            except queue.Empty:
                return
            ev = _http_probe_once(ip, port, sni, host, per_timeout)
            if _looks_real(ev):
                with lock:
                    if not winner.is_set():
                        result.append((ip, port, sni, ev))
                        winner.set()
                return

    threads = [threading.Thread(target=worker, daemon=True)
               for _ in range(min(max_workers, len(cands)))]
    for t in threads:
        t.start()
    winner.wait(deadline)
    winner.set()
    with lock:
        return result[0] if result else None


def _strict_tls_ok(ip, port, host, timeout=5.0):
    """Full TLS verification: chain + hostname against the real SNI."""
    ss = None
    try:
        raw = socket.create_connection((ip, port), timeout=timeout)
        ctx = ssl.create_default_context()
        ss = ctx.wrap_socket(raw, server_hostname=host)
        ss.close()
        return True
    except Exception:
        if ss is not None:
            try:
                ss.close()
            except Exception:
                pass
        return False


def _san_covers(der, host):
    """Best-effort SAN coverage check on the raw certificate (no network)."""
    if not der:
        return False
    try:
        from cryptography import x509
        cert = x509.load_der_x509_certificate(der)
        try:
            san = cert.extensions.get_extension_for_class(
                x509.SubjectAlternativeName)
            dns = san.value.get_values_for_type(x509.DNSName)
        except Exception:
            dns = []
    except Exception:
        return False
    h = (host or "").lower().rstrip(".")
    for v in dns:
        v = v.lower().rstrip(".")
        if v == h:
            return True
        if v.startswith("*."):
            base = v[2:]
            if h.endswith("." + base):
                rest = h[:-(len(base) + 1)]
                if rest and "." not in rest:
                    return True
    return False


def probe_domain_smart(domain, on_progress=None):
    """Diagnose why a domain is unreachable and find a strategy that works.

    Strategy kinds returned:
      - "direct":            the site answers directly; no rule needed.
      - "port_override":    alternate TLS port with the real SNI, strict TLS
                             verification passes (or the cert covers the host).
      - "port_override_pin": alternate TLS port serving a self-signed
                             certificate; applied with a SHA-256 cert pin.
      - "sni_rewrite":       legacy SNI masquerade — only accepted when the
                             edge answers a real HTTP response for the
                             target Host behind the mask.

    Calls `on_progress(step_message)` for live progress.
    """
    clean = _norm_domain(domain)
    if not clean:
        return {"success": False, "error": "请输入有效的域名"}

    bare = bare_domain(clean)

    def _prog(msg):
        if on_progress:
            on_progress(msg)

    # ------------------------------------------------ phase 0: DNS
    _prog(f"🔍 正在解析 {clean} 的 DNS 记录（系统 + 公共多路解析）...")
    ips = []
    for ip in resolve_system(clean) + resolve_domain(clean):
        if ip and ip not in ips:
            ips.append(ip)
    if not ips:
        return {
            "success": False,
            "domain": clean,
            "bare_domain": bare,
            "error": "DNS 解析失败：未找到有效 IP 地址，请检查拼写或网络连接",
        }
    ips = ips[:10]
    _prog(f"📡 DNS 解析成功，共 {len(ips)} 个候选边缘 IP：{', '.join(ips[:4])}")

    already_in_rules = is_blocked_domain(clean)

    # ------------------------------------------------ phase 1: direct check
    _prog("⚡ 正在实测直连（真实 SNI + HTTP 实请求验证）...")
    t0 = time.time()
    direct = _race(clean, [(ip, 443, clean) for ip in ips[:8]], deadline=8.0)
    direct_latency = round((time.time() - t0) * 1000, 1)
    if direct:
        d_ip, _p, _s, d_ev = direct
        _prog(f"✅ 直连正常（HTTP {d_ev['status']}，延迟 {direct_latency} ms），无需代理规则")
        return {
            "success": True,
            "strategy": "direct",
            "domain": clean,
            "bare_domain": bare,
            "is_blocked": False,
            "direct_ok": True,
            "direct_latency": direct_latency,
            "best_ip": d_ip,
            "best_sni": clean,
            "latency_ms": direct_latency,
            "verify_level": "host",
            "covers_host": True,
            "already_in_rules": already_in_rules,
            "http_status": d_ev["status"],
            "server_header": d_ev["server"],
            "recommended_suffix": clean,
            "message": (f"直连正常（HTTP {d_ev['status']}，{direct_latency} ms），"
                        "无需加入分流规则。若浏览器仍打不开，请检查浏览器代理设置。"),
        }
    _prog("⚠️ 直连 443 全部失败/被阻断：开始探测备用 TLS 端口与真实 SNI 路径...")

    # ------------------------------------------------ phase 2: alternate ports, real SNI
    _prog("🚀 正在并发探测备用 TLS 端口"
          f"（{', '.join(str(p) for p in ALT_TLS_PORTS)}）× 全部边缘 IP...")
    alt_cands = [(ip, port, clean)
                 for port in ALT_TLS_PORTS
                 for ip in ips[:8]]
    t0 = time.time()
    alt = _race(clean, alt_cands, deadline=14.0)
    elapsed = round((time.time() - t0) * 1000, 1)
    if alt:
        a_ip, a_port, _s, a_ev = alt
        strict = _strict_tls_ok(a_ip, a_port, clean)
        covers = _san_covers(a_ev["cert_der"], clean)
        pin = a_ev.get("cert_sha256") or ""
        if strict or covers:
            strategy = "port_override"
            level = "host"
            pin = None
            cert_desc = "CA 证书链有效，覆盖目标域名"
        elif pin:
            # 自签证书：没有指纹就无法锁定该路径，绝不能下发空指纹规则
            strategy = "port_override_pin"
            level = "pin"
            cert_desc = "自签证书，已按 SHA-256 指纹锁定"
        else:
            # 无法验证该路径（证书既不严格有效，也取不到指纹）：不可用，继续兜底
            _prog("⚠️ 备用端口路径无法验证证书，继续尝试 SNI 伪装兜底...")
            alt = None
    if alt:
        _prog(f"✅ 找到可用路径：{a_ip}:{a_port}（真实 SNI，HTTP {a_ev['status']}）")
        return {
            "success": True,
            "strategy": strategy,
            "domain": clean,
            "bare_domain": bare,
            "is_blocked": True,
            "direct_ok": False,
            "direct_latency": direct_latency,
            "best_ip": a_ip,
            "best_sni": clean,
            "port": a_port,
            "cert_pin": pin,
            "latency_ms": elapsed,
            "verify_level": level,
            "covers_host": covers,
            "already_in_rules": already_in_rules,
            "http_status": a_ev["status"],
            "server_header": a_ev["server"],
            # 备用端口规则按"精确主机"收口，避免误伤裸域的其他子域
            "recommended_suffix": clean,
            "message": (f"找到绕过路径：上游走 {a_ip}:{a_port}（真实 SNI，"
                        f"HTTP {a_ev['status']}，{cert_desc}）。"
                        "应用后将写入端口改写规则并加入分流。"),
        }

    # ------------------------------------------------ phase 3: SNI masquerade (legacy), HTTP-validated
    _prog("🎭 备用端口全部失败，正在尝试 SNI 伪装池（HTTP 实测验证）...")
    masks = []
    if clean in config.SNI_REWRITE:
        masks.append(config.SNI_REWRITE[clean])
    if bare != clean and bare not in masks:
        masks.append(bare)
    for s in config.ALLOWED_SNI_POOL:
        if s not in masks and s != clean:
            masks.append(s)
    mask_cands = [(ip, 443, m) for ip in ips[:6] for m in masks]
    t0 = time.time()
    mask = _race(clean, mask_cands, deadline=12.0)
    elapsed = round((time.time() - t0) * 1000, 1)
    if mask:
        m_ip, _p, m_sni, m_ev = mask
        covers = _san_covers(m_ev["cert_der"], clean)
        level = "host" if covers else "chain"
        _prog(f"✅ SNI 伪装测通：{m_ip} + SNI {m_sni}（HTTP {m_ev['status']}）")
        return {
            "success": True,
            "strategy": "sni_rewrite",
            "domain": clean,
            "bare_domain": bare,
            "is_blocked": True,
            "direct_ok": False,
            "direct_latency": direct_latency,
            "best_ip": m_ip,
            "best_sni": m_sni,
            "latency_ms": elapsed,
            "verify_level": level,
            "covers_host": covers,
            "already_in_rules": already_in_rules,
            "http_status": m_ev["status"],
            "server_header": m_ev["server"],
            "recommended_suffix": bare if len(bare.split(".")) >= 2 else clean,
            "message": (f"SNI 伪装测通：经 {m_ip} 使用伪装 SNI「{m_sni}」"
                        f"（HTTP {m_ev['status']}，{elapsed} ms）。"
                        "注意：该路径依赖目标边缘接受伪装 SNI，稳定性弱于端口改写方案。"),
        }

    # ------------------------------------------------ nothing worked
    _prog("❌ 探测完成：所有路径均未通过真实请求验证")
    return {
        "success": False,
        "domain": clean,
        "bare_domain": bare,
        "is_blocked": True,
        "direct_ok": False,
        "direct_latency": direct_latency,
        "error": ("全部边缘 IP 的 443 与备用端口（8443/2053/2083/2087/2096）"
                  "均未返回真实响应，SNI 伪装也遭目标服务器拒绝。"
                  "建议稍后重试（CDN 轮换可能换出可用 IP），"
                  "或在「SNI 伪装」页手动添加映射。"),
    }


def _write_cache_entry(domain, endpoints):
    """Persist endpoints into strategies.json and the live upstream cache."""
    cache = rules_manager.get_strategy_cache()
    cache[domain] = {"endpoints": endpoints, "fail_ts": None}
    try:
        with open(config.STRATEGY_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log_warning(f"failed to write strategies.json: {e}")
    try:
        with upstream._strategy_lock:
            upstream._strategy_cache[domain] = {
                "endpoints": [tuple(ep) for ep in endpoints],
                "fail_ts": None,
            }
    except Exception:
        pass


def apply_probe_result(result):
    """Save the probe result into rules.json / strategies.json and the PAC.

    Dispatches on result["strategy"]; results without a strategy key keep
    the legacy v1 behaviour (blocked suffix + optional SNI rewrite + cache).
    """
    if not result or not result.get("success"):
        return False, "无效的探测结果"

    domain = result["domain"]
    strategy = result.get("strategy")
    best_ip = result["best_ip"]
    best_sni = result["best_sni"]
    level = result.get("verify_level", "chain")

    if strategy == "direct":
        return True, f"{domain} 直连正常，无需添加分流规则。"

    if strategy in ("port_override", "port_override_pin"):
        port = int(result.get("port") or 443)
        pin = (result.get("cert_pin") or "").strip().lower() or None
        # 精确主机后缀：端口改写只对该主机及其子域生效，避免误伤同域兄弟站点
        rules_manager.add_blocked_suffix(domain)
        if port != 443:
            rules_manager.add_upstream_port_override(domain, port)
        if pin:
            rules_manager.add_upstream_cert_pin(domain, pin)
        # 丢弃旧的端点/失败缓存，写入实测可用的新端点
        rules_manager.delete_strategy_cache_entry(domain)
        _write_cache_entry(domain, [[best_ip, best_sni, "host"]])
        rules_manager.export_pac_file()
        log(f"  [OK] Probe rule applied: {domain} "
            f"(strategy={strategy}, port={port}, pin={bool(pin)})")
        msg = (f"已将 {domain} 加入分流规则：上游经 {best_ip}:{port} "
               f"使用真实 SNI 直连（HTTP {result.get('http_status', '')}）")
        if pin:
            msg += "，自签证书已按 SHA-256 指纹锁定"
        msg += "。若代理正在运行，请重启代理后生效。"
        return True, msg

    # ------------------------------------------ legacy / sni_rewrite path
    suffix = result.get("recommended_suffix", domain) or domain
    rules_manager.add_blocked_suffix(suffix)

    if best_sni != domain and domain.startswith("www."):
        rules_manager.add_sni_rewrite(domain, best_sni)

    rules_manager.delete_strategy_cache_entry(domain)
    _write_cache_entry(domain, [[best_ip, best_sni, level]])
    rules_manager.export_pac_file()
    log(f"  [OK] Probe rule applied: {domain} (suffix={suffix}, sni={best_sni})")
    return True, f"已成功将 {domain}（后缀 {suffix}）加入分流规则与最优策略缓存！"
