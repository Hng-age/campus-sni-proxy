"""Multi-path uplink detection and binding (campus + phone tether)."""

import itertools
import socket
import subprocess
import threading
import time

from .config import NO_WINDOW
from .logsetup import log

_uplinks = []                     # list of source IPs with default routes
_uplink_lock = threading.Lock()
_uplink_rr = itertools.count()
_uplink_fail = {}                 # ip -> fail timestamp
_uplink_scan_ts = 0.0
_UPLINK_RESCAN = 30               # rescan routes every 30s
_UPLINK_FAIL_PENALTY = 30         # park a dead uplink for 30s


def scan_uplinks():
    """Detect local source IPs that own a default route (internet uplinks)."""
    global _uplinks, _uplink_scan_ts
    try:
        # route.exe prints in the OEM code page (cp936 on zh-CN), not UTF-8
        out = subprocess.run(
            ["route", "print", "-4"], capture_output=True,
            timeout=10, creationflags=NO_WINDOW).stdout.decode("oem", errors="replace")
        found = []
        for line in out.splitlines():
            parts = line.split()
            # "0.0.0.0  0.0.0.0  <gateway>  <interface_ip>  <metric>"
            if len(parts) >= 5 and parts[0] == "0.0.0.0" and parts[1] == "0.0.0.0":
                src = parts[3]
                if src.startswith(("127.", "169.254.")):
                    continue
                if src not in found:
                    found.append(src)
        if found:
            with _uplink_lock:
                old = _uplinks
                _uplinks = found
                if old != found:
                    log(f"  [PATH] uplinks now: {found}")
        _uplink_scan_ts = time.time()
    except Exception:
        pass


def next_uplink():
    """Next healthy uplink source IP (round-robin), or None."""
    global _uplink_scan_ts
    if time.time() - _uplink_scan_ts > _UPLINK_RESCAN:
        need_scan = False
        with _uplink_lock:
            if time.time() - _uplink_scan_ts > _UPLINK_RESCAN:
                _uplink_scan_ts = time.time()
                need_scan = True
        if need_scan:
            scan_uplinks()
    with _uplink_lock:
        cands = [ip for ip in _uplinks
                 if time.time() - _uplink_fail.get(ip, 0) > _UPLINK_FAIL_PENALTY]
    if len(cands) <= 1:
        # single uplink: OS default routing is equivalent, skip binding
        return None
    return cands[next(_uplink_rr) % len(cands)]


def mark_uplink_fail(ip):
    if ip:
        _uplink_fail[ip] = time.time()


def bind_sock(sock, uplink):
    """Bind socket to the chosen uplink source IP."""
    if uplink:
        try:
            sock.bind((uplink, 0))
        except Exception:
            pass  # fall back to default routing


def connect_tcp(ip, port, timeout=10):
    """TCP connect with multi-path round-robin and quick failover.
    Returns (sock, uplink_used) or (None, None)."""
    uplink = next_uplink()
    order = [uplink] if uplink else [None]
    if uplink:
        # failover candidates: other uplinks, then unbound
        with _uplink_lock:
            others = [u for u in _uplinks if u != uplink]
        order += others[:1] + [None]

    for src in order:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            bind_sock(sock, src)
            sock.connect((ip, port))
            return sock, src
        except (socket.timeout, TimeoutError):
            # firewall drop / unreachable target: not the uplink's fault
            # for the FIRST attempt; try next path anyway
            continue
        except OSError:
            if src:
                mark_uplink_fail(src)
            continue
    return None, None


def connect_tcp_bound(ip, port, src=None, timeout=4):
    """TCP connect bound to a specific source IP (None = OS default)."""
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        bind_sock(sock, src)
        sock.connect((ip, port))
        return sock
    except Exception:
        try:
            if sock:
                sock.close()
        except Exception:
            pass
        return None


def connect_host_direct(host, port, timeout=8):
    """Fallback: let the OS resolver + routing choose, like a direct client."""
    try:
        return socket.create_connection((host, port), timeout=timeout)
    except Exception:
        return None


def connect_any(ips, port, timeout=4, deadline=7):
    """Try every IP x every uplink concurrently; first success wins.

    Passthrough must behave like a direct connection even when the proxy
    process has a different default route (multi-NIC / session 0).
    """
    if not _uplinks:
        scan_uplinks()
    with _uplink_lock:
        sources = [None] + list(_uplinks)
    seen = set()
    cands = []
    for ip in ips[:6]:
        for src in sources:
            key = (ip, src)
            if key not in seen:
                seen.add(key)
                cands.append(key)

    winner = threading.Event()
    result = []
    lock = threading.Lock()

    def worker(ip, src):
        if winner.is_set():
            return
        sock = connect_tcp_bound(ip, port, src, timeout)
        if sock:
            with lock:
                if winner.is_set():
                    try:
                        sock.close()
                    except Exception:
                        pass
                else:
                    result.append(sock)
                    winner.set()

    threads = [threading.Thread(target=worker, args=(ip, src), daemon=True)
               for ip, src in cands]
    for t in threads:
        t.start()
    winner.wait(deadline)
    winner.set()
    with lock:
        return result[0] if result else None
