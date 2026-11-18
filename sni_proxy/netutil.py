"""DNS resolution, domain matching and certificate hostname matching."""

import random
import socket
import struct

from .config import SNI_REWRITE, BLOCKED_SUFFIXES, WILDCARD_BASES


def matches_suffix(domain, suffixes):
    """Exact suffix match: douyin.com matches, notdouyin.com does not."""
    d = domain.lower().rstrip(".")
    return any(d == s or d.endswith("." + s) for s in suffixes)


def resolve_domain(domain):
    """UDP DNS A record lookup - merge results from 2 public resolvers."""

    def query(server):
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
            s.close()

            if len(data) < 12 or struct.unpack('>H', data[:2])[0] != qid:
                return []

            ips = []
            pos = 12
            while pos < len(data):
                if data[pos] & 0xC0 == 0xC0:
                    pos += 2
                elif data[pos] == 0:
                    pos += 1
                    break
                else:
                    pos += data[pos] + 1
            pos += 4

            ancount = struct.unpack('>H', data[6:8])[0]
            for _ in range(ancount):
                try:
                    if data[pos] & 0xC0 == 0xC0:
                        pos += 2
                    else:
                        while data[pos] != 0:
                            pos += data[pos] + 1
                        pos += 1
                    rtype = struct.unpack('>H', data[pos:pos + 2])[0]
                    pos += 8
                    rdlen = struct.unpack('>H', data[pos:pos + 2])[0]
                    pos += 2
                    if rtype == 1:
                        ips.append('.'.join(str(b) for b in data[pos:pos + 4]))
                    pos += rdlen
                except Exception:
                    break
            return ips
        except Exception:
            return []

    merged = []
    seen = set()
    for server in ("223.5.5.5", "114.114.114.114"):
        for ip in query(server):
            if ip not in seen:
                seen.add(ip)
                merged.append(ip)
        if len(merged) >= 8:
            break
    if not merged:
        # campus networks sometimes drop direct UDP/53 to public resolvers
        return resolve_system(domain)
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


def bare_domain(domain):
    parts = domain.split('.')
    return '.'.join(parts[-2:]) if len(parts) >= 2 else domain


def is_blocked_domain(domain):
    d = domain.lower().rstrip(".")
    if d in SNI_REWRITE:
        return True
    return matches_suffix(d, BLOCKED_SUFFIXES)


def wildcard_covers(domain):
    """True if the shared wildcard cert has a SAN matching this host."""
    h = domain.lower().rstrip(".")
    for base in WILDCARD_BASES:
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
