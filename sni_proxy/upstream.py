"""Upstream TLS connection, certificate verification and SNI fallback."""

import json
import os
import queue
import socket
import ssl
import threading
import time

from .config import (
    ALLOWED_SNI_POOL,
    ASSET_COMPAT,
    ASSET_COMPAT_SUFFIXES,
    ATTEMPT_TIMEOUT,
    CDN_FAMILIES,
    CDN_SIBLING_HOSTS,
    NEG_CACHE_TTL,
    SNI_REWRITE,
    STRATEGY_FILE,
    STRICT_UPSTREAM,
)
from .logsetup import log, log_debug, log_error
from .netutil import (
    bare_domain,
    cert_covers,
    matches_suffix,
    resolve_domain,
    resolve_system,
)
from .uplinks import connect_tcp

_strategy_lock = threading.Lock()
_save_lock = threading.Lock()
_tls_ctx = None
_tls_ctx_lock = threading.Lock()


def allow_chain_route(domain):
    """Chain-only routes are acceptable for static assets in strict mode."""
    if not STRICT_UPSTREAM:
        return True
    return ASSET_COMPAT and matches_suffix(domain, ASSET_COMPAT_SUFFIXES)


def _client_tls_context():
    """Build the verifying client context once (load_default_certs is slow)."""
    global _tls_ctx
    if _tls_ctx is None:
        with _tls_ctx_lock:
            if _tls_ctx is None:
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_REQUIRED
                ctx.load_default_certs()
                _tls_ctx = ctx
    return _tls_ctx

# domain -> {"endpoints": [(ip, sni, level), ...], "fail_ts": float|None}
_strategy_cache = {}

# short-lived DNS memo so cache validation does not re-query on every request
_dns_cache = {}
_dns_lock = threading.Lock()


def _current_ip_set(domain, ttl=60):
    """Union of system + public DNS answers, memoized for `ttl` seconds."""
    now = time.time()
    with _dns_lock:
        hit = _dns_cache.get(domain)
        if hit and now - hit[0] < ttl:
            return set(hit[1])
    ips = set(resolve_system(domain))
    ips.update(resolve_domain(domain))
    with _dns_lock:
        _dns_cache[domain] = (now, ips)
    return set(ips)


def _drop_stale_endpoints(domain, endpoints):
    """Discard cached IPs that DNS no longer returns (rotated / wrong edge).

    A stale edge can still complete TLS and answer 404 for the real host,
    so failure-only invalidation is not enough. Mapped routes legitimately
    use IPs of the bare domain, so both answer sets are considered.
    """
    fresh = _current_ip_set(domain)
    bare = bare_domain(domain)
    if bare != domain:
        fresh |= _current_ip_set(bare)
    if not fresh:
        return endpoints
    kept = [ep for ep in endpoints if ep[0] in fresh]
    if len(kept) != len(endpoints):
        log_debug(f"cache prune {domain}: dropped "
                  f"{len(endpoints) - len(kept)} stale ip(s)")
    return kept


# IPs seen on any blocked-domain edge, most recent first, grouped by CDN
# family. Edge pools are shared between hosts of the same family only: a
# ByteDance edge answers TLS for *.xiaohongshu.com but then drops the
# connection (HTTP 000 in browsers), so cross-family reuse is forbidden.
_ip_pool = {}
_ip_pool_lock = threading.Lock()
_IP_POOL_MAX = 24
_POOL_CANDIDATES = 12


def _family_of(domain):
    for family, suffixes in CDN_FAMILIES.items():
        if matches_suffix(domain, suffixes):
            return family
    return None


def _remember_ips(ips, family):
    if not family:
        return
    with _ip_pool_lock:
        pool = _ip_pool.setdefault(family, [])
        for ip in ips:
            if not ip:
                continue
            try:
                pool.remove(ip)
            except ValueError:
                pass
            pool.insert(0, ip)
        del pool[_IP_POOL_MAX:]


def _pool_snapshot(family):
    if not family:
        return []
    with _ip_pool_lock:
        return list(_ip_pool.get(family, [])[:_POOL_CANDIDATES])


def try_tls(ip, sni, timeout=ATTEMPT_TIMEOUT, verify_host=None):
    """TLS handshake with upstream certificate-chain verification.
    verify_host: when set, the certificate must also cover this hostname."""
    sock, uplink = connect_tcp(ip, 443, timeout)
    if sock is None:
        return None
    try:
        ctx = _client_tls_context()
        ssock = ctx.wrap_socket(sock, server_hostname=sni)
        if verify_host:
            try:
                cert = ssock.getpeercert()
            except Exception:
                cert = None
            if not cert or not cert_covers(cert, verify_host):
                try:
                    ssock.close()
                except Exception:
                    pass
                return None
        return ssock
    except Exception:
        try:
            sock.close()
        except Exception:
            pass
        return None


def probe_first(candidates, timeout=ATTEMPT_TIMEOUT, workers=12, deadline=12,
                verify_host=None):
    """Probe (ip, sni, how) candidates concurrently; first success wins.
    Returns (ssock, ip, sni, how) or (None, None, None, None)."""
    if not candidates:
        return None, None, None, None

    todo = queue.Queue()
    for c in candidates:
        todo.put(c)

    winner = threading.Event()
    result = []
    result_lock = threading.Lock()

    def worker():
        while not winner.is_set():
            try:
                ip, sni, how = todo.get(timeout=0.2)
            except queue.Empty:
                return
            ssock = try_tls(ip, sni, timeout, verify_host=verify_host)
            if ssock:
                with result_lock:
                    if winner.is_set():
                        try:
                            ssock.close()
                        except Exception:
                            pass
                    else:
                        result.append((ssock, ip, sni, how))
                        winner.set()
                return

    threads = [threading.Thread(target=worker, daemon=True)
               for _ in range(min(workers, len(candidates)))]
    for t in threads:
        t.start()

    winner.wait(deadline)
    winner.set()
    with result_lock:
        if result:
            return result[0]
    return None, None, None, None


def build_candidates(domain):
    """Build ordered (ip, sni, how) candidate list for a blocked domain.
    CDN IP rotation means we must try several IPs x several SNIs."""
    cands = []
    own_ips = resolve_system(domain)
    for ip in resolve_domain(domain):
        if ip not in own_ips:
            own_ips.append(ip)
    bare = bare_domain(domain)
    bare_ips = resolve_system(bare) if bare != domain else []
    if bare != domain:
        for ip in resolve_domain(bare):
            if ip not in bare_ips:
                bare_ips.append(ip)

    # Edge pools are shared between sibling hosts of the same CDN family.
    # When this host's own DNS answers point at a dead pool (mobile-only
    # edges), the siblings' IPs are probed with the real SNI; the certificate
    # check rejects wrong edges.
    family = _family_of(domain)
    for sibling in CDN_SIBLING_HOSTS.get(bare, []):
        _remember_ips(resolve_system(sibling) + resolve_domain(sibling),
                      _family_of(sibling))

    first_sni = SNI_REWRITE.get(domain) or bare

    # 0. own IP + real host SNI: works when the firewall allows the real SNI,
    #    and avoids wrong-edge 404s (e.g. live.douyin.com)
    for ip in own_ips[:16]:
        cands.append((ip, domain, "own+host"))
    for ip in _pool_snapshot(family):
        if ip not in own_ips[:16]:
            cands.append((ip, domain, "pool+host"))

    # 1. own IP + mapped/bare SNI - all resolved IPs (DNS rotation tolerance)
    for ip in own_ips[:16]:
        cands.append((ip, first_sni, "own+map"))

    # 2. bare IP + bare SNI (own edge is often fully blocked)
    if bare != domain and bare_ips:
        for ip in bare_ips[:4]:
            cands.append((ip, bare, "bare+map"))

    # 3. bare IP + allowed SNI pool - video CDNs often only accept the
    #    bare-domain edge with a whitelisted SNI; try this early
    if bare != domain and bare_ips:
        for ip in bare_ips[:3]:
            for sni in ALLOWED_SNI_POOL:
                cands.append((ip, sni, "bare+pool"))

    # 4. own IP + allowed SNI pool (CDN edges accepting foreign SNI)
    for ip in own_ips[:3]:
        for sni in ALLOWED_SNI_POOL:
            cands.append((ip, sni, "own+pool"))

    # de-duplicate identical (ip, sni) attempts
    seen = set()
    unique = []
    for ip, sni, how in cands:
        key = (ip, sni)
        if key not in seen:
            seen.add(key)
            unique.append((ip, sni, how))
    return unique


def save_strategy_cache():
    """Persist endpoint cache to disk so restarts skip the probe chain."""
    try:
        data = {}
        with _strategy_lock:
            for domain, entry in _strategy_cache.items():
                data[domain] = {
                    "endpoints": [list(ep) for ep in entry.get("endpoints", [])],
                    "fail_ts": entry.get("fail_ts"),
                }
        tmp = STRATEGY_FILE + ".tmp"
        with _save_lock:
            os.makedirs(os.path.dirname(STRATEGY_FILE), exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            for _ in range(3):
                try:
                    os.replace(tmp, STRATEGY_FILE)
                    break
                except PermissionError:
                    time.sleep(0.05)
            else:
                raise PermissionError("strategy cache is locked by another process")
    except Exception as e:
        log_error(f"save strategy cache failed: {e}")


def load_strategy_cache():
    try:
        if not os.path.exists(STRATEGY_FILE):
            return
        with open(STRATEGY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        with _strategy_lock:
            for domain, entry in data.items():
                # drop fail_ts on load: transient failures should not
                # short-circuit a fresh process to 204 without probing
                endpoints = []
                for ep in entry.get("endpoints", []):
                    if len(ep) >= 3:
                        endpoints.append((ep[0], ep[1], ep[2]))
                    elif len(ep) == 2:
                        # 1.0.2 cache entries were chain-only routes
                        endpoints.append((ep[0], ep[1], "chain"))
                _strategy_cache[domain] = {
                    "endpoints": endpoints,
                    "fail_ts": None,
                }
    except Exception as e:
        log_error(f"load strategy cache failed: {e}")


def connect_upstream(domain, port):
    """Connect upstream with SNI fallback.
    Returns (ssl_sock, sni_used) or (None, reason)."""
    if port != 443:
        # plain TCP, no TLS involved
        try:
            ips = resolve_domain(domain)
            if not ips:
                return None, "dns fail"
            sock, _src = connect_tcp(ips[0], port, timeout=10)
            if sock is None:
                return None, "connect fail"
            sock.settimeout(None)
            return sock, f"tcp:{port}"
        except Exception as e:
            return None, str(e)

    # cached endpoints first: verified routes, then chain-verified fallback
    with _strategy_lock:
        entry = _strategy_cache.get(domain)
    if entry:
        raw_eps = [ep for ep in entry.get("endpoints", []) if ep and ep[0]]
        eps = _drop_stale_endpoints(domain, raw_eps)
        if len(eps) != len(raw_eps):
            entry = {"endpoints": eps, "fail_ts": None}
            with _strategy_lock:
                _strategy_cache[domain] = entry
            save_strategy_cache()

        host_cached = []
        chain_cached = []
        for ep in eps:
            level = ep[2] if len(ep) >= 3 else "chain"
            if level == "host":
                host_cached.append((ep[0], ep[1], "cache"))
            else:
                chain_cached.append((ep[0], ep[1], "cache"))

        if host_cached:
            ssock, _ip, sni, _how = probe_first(
                host_cached, timeout=3, workers=4, deadline=6,
                verify_host=domain)
            if ssock:
                ssock.settimeout(None)
                log(f"  [OK] {domain} via {_ip} SNI={sni} (cache, host)")
                return ssock, sni
        if chain_cached and allow_chain_route(domain):
            ssock, _ip, sni, _how = probe_first(
                chain_cached, timeout=3, workers=4, deadline=8)
            if ssock:
                ssock.settimeout(None)
                log(f"  [OK] {domain} via {_ip} SNI={sni} (cache, chain)")
                return ssock, sni

        # cached endpoints all dead
        if entry.get("fail_ts") and time.time() - entry["fail_ts"] < NEG_CACHE_TTL:
            return None, "cached-fail"
        with _strategy_lock:
            _strategy_cache[domain] = {"endpoints": [], "fail_ts": None}

    # full fallback chain: prefer routes whose certificate covers the host
    cands = [(ip, sni, how) for ip, sni, how in build_candidates(domain) if ip]
    tried = len(cands)
    bare = bare_domain(domain)
    family = _family_of(domain)
    host_snis = {domain.lower(), bare.lower()}
    mapped = SNI_REWRITE.get(domain)
    if mapped:
        host_snis.add(mapped.lower())
    verified_cands = [c for c in cands if c[1].lower() in host_snis]

    # Phase 1: real hostname SNI only. This avoids a wrong CDN edge that
    # completes TLS but returns 404 (e.g. live.douyin.com).
    real_host_cands = [c for c in cands if c[1].lower() == domain.lower()]
    if real_host_cands:
        # launch every candidate at once: a single slow IP must not delay the
        # one good edge (campus drops most IPs with a 2.5s SYN timeout)
        ssock, ip, sni, how = probe_first(
            real_host_cands, timeout=2.0,
            workers=min(32, len(real_host_cands)), deadline=2.5,
            verify_host=domain)
        if ssock:
            ssock.settimeout(None)
            _remember_ips([ip], family)
            with _strategy_lock:
                entry = _strategy_cache.setdefault(
                    domain, {"endpoints": [], "fail_ts": None})
                if not any(ep[0] == ip and ep[1] == sni
                           for ep in entry["endpoints"]):
                    entry["endpoints"].insert(0, (ip, sni, "host"))
                    del entry["endpoints"][5:]
                entry["fail_ts"] = None
            save_strategy_cache()
            log(f"  [OK] {domain} via {ip} SNI={sni} ({how}, host)")
            return ssock, sni

    ssock, ip, sni, how = probe_first(
        verified_cands, timeout=ATTEMPT_TIMEOUT,
        workers=min(20, len(verified_cands)), deadline=5,
        verify_host=domain)
    level = "host"
    if not ssock and allow_chain_route(domain):
        # compatibility fallback: many campus CDN edges return a shared
        # certificate that does not cover the target host
        level = "chain"
        ssock, ip, sni, how = probe_first(
            cands, timeout=ATTEMPT_TIMEOUT,
            workers=min(20, len(cands)), deadline=8)

    if ssock:
        ssock.settimeout(None)
        _remember_ips([ip], family)
        with _strategy_lock:
            entry = _strategy_cache.setdefault(
                domain, {"endpoints": [], "fail_ts": None})
            if not any(ep[0] == ip and ep[1] == sni for ep in entry["endpoints"]):
                entry["endpoints"].insert(0, (ip, sni, level))
                del entry["endpoints"][5:]
            entry["fail_ts"] = None
        save_strategy_cache()
        log(f"  [OK] {domain} via {ip} SNI={sni} ({how}, {level})")
        return ssock, sni

    # sibling rescue: try endpoints cached from other subdomains of the
    # same bare domain (e.g. lf-douyin-pc-web via lf-douyin-pc-web-back)
    if bare != domain and allow_chain_route(domain):
        with _strategy_lock:
            sib_eps = []
            for d, e in _strategy_cache.items():
                if d != domain and d.endswith("." + bare) and e.get("endpoints"):
                    for ep in e["endpoints"]:
                        pair = (ep[0], ep[1])
                        if pair not in sib_eps:
                            sib_eps.append(pair)
        sib_cands = [(ip, sni, "sib") for ip, sni in sib_eps[:6]]
        ssock, ip, sni, _how = probe_first(
            sib_cands, timeout=3, workers=4, deadline=8)
        if ssock:
            ssock.settimeout(None)
            with _strategy_lock:
                entry = _strategy_cache.setdefault(
                    domain, {"endpoints": [], "fail_ts": None})
                if not any(ep[0] == ip and ep[1] == sni for ep in entry["endpoints"]):
                    entry["endpoints"].insert(0, (ip, sni, "chain"))
                entry["fail_ts"] = None
            save_strategy_cache()
            log(f"  [OK] {domain} via sibling {ip} SNI={sni} (sib)")
            return ssock, sni

    # nothing worked
    with _strategy_lock:
        _strategy_cache[domain] = {"endpoints": [], "fail_ts": time.time()}
    save_strategy_cache()
    return None, f"all {tried} strategies failed"
