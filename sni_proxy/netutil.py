"""DNS resolution, domain matching and certificate hostname matching."""

import random
import socket
import struct
import threading
import time

from . import config

# The campus resolver and the public resolvers return different CDN edges for
# the same host (one set can be half-dead). Querying them in parallel and
# merging the answers is what makes live.douyin.com reachable reliably.
DNS_SERVERS = ("223.5.5.5", "114.114.114.114", "119.29.29.29", "180.76.76.76")

_dns_memo = {}
_dns_memo_lock = threading.Lock()
_DNS_MEMO_TTL = 30


def matches_suffix(domain, suffixes):
    """Exact suffix match: douyin.com matches, notdouyin.com does not."""
    d = domain.lower().rstrip(".")
    return any(d == s or d.endswith("." + s) for s in suffixes)


def _read_name(data, off):
    """Decode a (possibly compressed) DNS name; return (name, next_offset)."""
    labels = []
    end = None
    hops = 0
    while off < len(data) and hops < 32:
        hops += 1
        length = data[off]
        if length == 0:
            off += 1
            if end is None:
                end = off
            break
        if length & 0xC0 == 0xC0:
            if off + 1 >= len(data):
                break
            if end is None:
                end = off + 2
            off = ((length & 0x3F) << 8) | data[off + 1]
            continue
        labels.append(data[off + 1:off + 1 + length].decode("ascii", "ignore"))
        off += 1 + length
    return ".".join(labels), (end if end is not None else off)


def _udp_lookup(domain):
    """Ask every resolver in parallel; return (ip_list, cname_list).

    CDN answers are CNAME chains, and the resolver-flattened A records can be
    a dead pool while the CNAME target still points at the live one
    (e.g. live.douyin.com -> *.w.cdngslb.com), so targets are returned too.
    """
    answers = []
    lock = threading.Lock()

    def query(server):
        ips, cnames = [], []
        s = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(2.5)
            qid = random.randint(1, 0xFFFF)
            q = struct.pack('>HHHHHH', qid, 0x0100, 1, 0, 0, 0)
            for part in domain.split('.'):
                q += bytes([len(part)]) + part.encode()
            q += b'\x00' + struct.pack('>HH', 1, 1)
            s.sendto(q, (server, 53))
            data, _ = s.recvfrom(4096)

            if len(data) < 12 or struct.unpack('>H', data[:2])[0] != qid:
                return ips, cnames

            qdcount = struct.unpack('>H', data[4:6])[0]
            ancount = struct.unpack('>H', data[6:8])[0]
            pos = 12
            for _ in range(qdcount):
                _, pos = _read_name(data, pos)
                pos += 4

            for _ in range(ancount):
                _, pos = _read_name(data, pos)
                if pos + 10 > len(data):
                    break
                rtype, _rclass, _ttl, rdlen = struct.unpack(
                    ">HHIH", data[pos:pos + 10])
                pos += 10
                rdata = pos
                if rtype == 1 and rdlen == 4:
                    ips.append('.'.join(str(b) for b in data[rdata:rdata + 4]))
                elif rtype == 5:
                    cname, _ = _read_name(data, rdata)
                    if cname:
                        cnames.append(cname)
                pos = rdata + rdlen
        except Exception:
            pass
        finally:
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass
        return ips, cnames

    def worker(server):
        res = query(server)
        with lock:
            answers.append(res)

    threads = [threading.Thread(target=worker, args=(srv,), daemon=True)
               for srv in DNS_SERVERS]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=3)

    ips, cnames = [], []
    for got_ips, got_cnames in answers:
        ips.extend(got_ips)
        cnames.extend(got_cnames)
    return ips, cnames


def resolve_domain(domain):
    """UDP DNS A lookup: all resolvers in parallel, CNAME targets followed."""
    now = time.time()
    with _dns_memo_lock:
        hit = _dns_memo.get(domain)
        if hit and now - hit[0] < _DNS_MEMO_TTL:
            return list(hit[1])

    merged = []
    seen = set()

    def add(ips):
        for ip in ips:
            if ip not in seen:
                seen.add(ip)
                merged.append(ip)

    ips, cnames = _udp_lookup(domain)
    add(ips)

    # follow CNAME targets (one extra level is enough for ByteDance CDNs)
    visited = {domain}
    frontier = [c for c in dict.fromkeys(cnames) if c not in visited][:4]
    for _ in range(2):
        if not frontier:
            break
        visited.update(frontier)
        next_frontier = []
        threads = []
        results = []
        lock = threading.Lock()

        def follow(target):
            got_ips, got_cnames = _udp_lookup(target)
            with lock:
                results.append((got_ips, got_cnames))

        for target in frontier:
            t = threading.Thread(target=follow, args=(target,), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join(timeout=3)
        for got_ips, got_cnames in results:
            add(got_ips)
            for c in got_cnames:
                if c not in visited and c not in next_frontier:
                    next_frontier.append(c)
        frontier = next_frontier[:4]

    if not merged:
        # campus networks sometimes drop direct UDP/53 to public resolvers
        return resolve_system(domain)
    with _dns_memo_lock:
        _dns_memo[domain] = (now, list(merged))
    return merged


def resolve_system(domain):
    """Resolve via the OS resolver (correct DNS for passthrough traffic)."""
    try:
        infos = socket.getaddrinfo(
            domain, None, socket.AF_INET, socket.SOCK_STREAM)
        ips = []
        for info in infos:
            ip = info[4][0]
            if ip not in ips:
                ips.append(ip)
        return ips
    except Exception:
        return []


# 常见多级公共后缀：直接取最后两段会把 example.edu.cn 截成 edu.cn，
# 导致自动学习把整个教育网加入分流规则。这里做最小可用的后缀识别。
_MULTI_LEVEL_SUFFIXES = {
    "com.cn", "net.cn", "org.cn", "gov.cn", "edu.cn", "ac.cn", "mil.cn",
    "com.hk", "net.hk", "org.hk", "edu.hk", "gov.hk",
    "com.tw", "net.tw", "org.tw", "edu.tw", "gov.tw",
    "com.mo", "net.mo", "org.mo", "edu.mo", "gov.mo",
    "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "net.uk",
    "com.au", "net.au", "org.au", "edu.au", "gov.au",
    "co.jp", "ne.jp", "or.jp", "ac.jp", "go.jp",
    "com.sg", "net.sg", "org.sg", "edu.sg", "gov.sg",
    "com.kr", "net.kr", "org.kr", "co.kr", "or.kr", "ac.kr", "go.kr",
    "com.br", "com.mx", "com.ar", "com.tr", "com.ru", "com.ua",
    "co.nz", "net.nz", "org.nz", "com.my", "com.ph", "com.vn",
    "co.in", "net.in", "org.in", "co.id", "co.th", "co.za",
}


def bare_domain(domain):
    parts = domain.split('.')
    if len(parts) >= 3 and ".".join(parts[-2:]) in _MULTI_LEVEL_SUFFIXES:
        return ".".join(parts[-3:])
    return '.'.join(parts[-2:]) if len(parts) >= 2 else domain


def is_fake_ip(ip):
    """True for RFC 2544 benchmarking addresses used by Clash/Surge fake-IP.

    When a透明代理 runs in TUN fake-IP mode, DNS answers point at
    198.18.0.0/15. Such addresses must be routed by the OS through the TUN
    device and must never be bound to a physical uplink's source address.
    """
    return bool(ip) and (ip.startswith("198.18.") or ip.startswith("198.19."))


def is_blocked_domain(domain):
    d = domain.lower().rstrip(".")
    if d in config.SNI_REWRITE:
        return True
    return matches_suffix(d, config.BLOCKED_SUFFIXES)


def is_passthrough_domain(domain):
    """True for domains the PAC routes here but we must not MITM."""
    return matches_suffix(domain.lower().rstrip("."), config.PASSTHROUGH_SUFFIXES)


def wildcard_covers(domain):
    """True if the shared wildcard cert has a SAN matching this host."""
    h = domain.lower().rstrip(".")
    for base in config.WILDCARD_BASES:
        if h == base:
            return True
        if h.endswith("." + base):
            rest = h[:-len(base) - 1]
            if rest and "." not in rest:
                return True
    return False


def cert_covers(cert, host):
    """Check a decoded peer certificate against a hostname (wildcards ok)."""
    h = host.lower().rstrip(".")
    for kind, value in cert.get("subjectAltName", []):
        if kind != "DNS":
            continue
        v = value.lower().rstrip(".")
        if v == h:
            return True
        if v.startswith("*."):
            base = v[2:]
            if h.endswith("." + base):
                rest = h[:-len(base) - 1]
                if rest and "." not in rest:
                    return True
    return False
