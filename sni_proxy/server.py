"""Proxy server: CONNECT handling, MITM/passthrough forwarding, main loop."""

import os
import re
import socket
import ssl
import sys
import threading

from . import config
from .certs import ensure_identity, generate_site_cert
from .logsetup import log, log_debug, log_error, log_warning
from .netutil import (is_blocked_domain, is_passthrough_domain, matches_suffix,
                      resolve_domain, resolve_system)
from .upstream import connect_upstream, load_strategy_cache
from .uplinks import connect_any, connect_tcp


def _is_disconnect(exc):
    """Common peer-closed / reset / client TLS-alert errors are not failures."""
    if isinstance(exc, (ConnectionResetError, ConnectionAbortedError,
                        BrokenPipeError, ssl.SSLError)):
        return True
    return getattr(exc, "winerror", None) in (10053, 10054, 10058)


def pump(src, dst):
    """Copy src -> dst until either side dies. 180s inactivity reaper."""
    try:
        try:
            src.settimeout(180)
        except Exception:
            pass
        while True:
            data = src.recv(65536)
            if not data:
                return
            dst.sendall(data)
    except Exception:
        return


def forward_bidirectional(a, b):
    # Enable TCP_NODELAY for lower latency and smoother streaming
    for s in (a, b):
        try:
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass

    t = threading.Thread(target=pump, args=(a, b), daemon=True)
    t.start()
    pump(b, a)
    for s in (a, b):
        try:
            s.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            s.close()
        except Exception:
            pass


_server_ctx_cache = {}
_server_ctx_lock = threading.Lock()


def _server_context(cert_file, key_file):
    """Cache server-side SSL contexts per certificate pair."""
    key = (cert_file, key_file)
    with _server_ctx_lock:
        ctx = _server_ctx_cache.get(key)
        if ctx is None:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(cert_file, key_file)
            try:
                ctx.set_alpn_protocols(["http/1.1"])
            except Exception:
                pass
            _server_ctx_cache[key] = ctx
    return ctx


def _drop_server_context(cert_file, key_file):
    """Forget a context that failed to handshake so the next attempt reloads."""
    with _server_ctx_lock:
        _server_ctx_cache.pop((cert_file, key_file), None)


def soft_fail_mitm(client_sock, host):
    """Upstream totally dead: complete TLS with browser, answer 204 for everything.
    Page JS treats telemetry endpoints as done; rendering is not affected."""
    try:
        client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        cert_file, key_file = generate_site_cert(host)
        if not cert_file:
            client_sock.close()
            return
        server_ctx = _server_context(cert_file, key_file)
        tls_client = server_ctx.wrap_socket(client_sock, server_side=True)
        tls_client.settimeout(10)
        try:
            while True:
                data = tls_client.recv(65536)
                if not data:
                    break
                tls_client.sendall(
                    b"HTTP/1.1 204 No Content\r\nContent-Length: 0\r\n"
                    b"Connection: close\r\n\r\n")
                break
        except Exception:
            pass
        tls_client.close()
    except Exception as e:
        if _is_disconnect(e):
            log_debug(f"soft-fail mitm {host} closed: {e}")
        else:
            log_error(f"soft-fail mitm {host}: {e}")
        try:
            client_sock.close()
        except Exception:
            pass


def handle_https_mitm(client_sock, host, port):
    upstream = None
    try:
        upstream, sni_used = connect_upstream(host, port)
        if not upstream:
            msg = f"  [SOFT] {host}: {sni_used} -> 204 soft-fail"
            if matches_suffix(host, ("zijieapi.com",)):
                log_debug(msg)
            else:
                log(msg)
            soft_fail_mitm(client_sock, host)
            return

        client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")

        cert_file, key_file = generate_site_cert(host)
        if not cert_file:
            log_debug(f"mitm {host}: no certificate available")
            client_sock.close()
            upstream.close()
            return

        try:
            server_ctx = _server_context(cert_file, key_file)
            tls_client = server_ctx.wrap_socket(client_sock, server_side=True)
        except ssl.SSLError as e:
            # a cached context can be stale (cert files regenerated); reload once
            log_debug(f"mitm {host}: client TLS failed ({e}), reloading context")
            _drop_server_context(cert_file, key_file)
            try:
                server_ctx = _server_context(cert_file, key_file)
                tls_client = server_ctx.wrap_socket(client_sock, server_side=True)
            except Exception as e2:
                log_debug(f"mitm {host}: client TLS failed after reload: {e2}")
                upstream.close()
                return

        forward_bidirectional(tls_client, upstream)

    except Exception as e:
        if _is_disconnect(e):
            log_debug(f"mitm {host} closed: {e}")
        else:
            log_error(f"mitm {host}: {e}")
    finally:
        for s in [client_sock, upstream]:
            try:
                if s:
                    s.close()
            except Exception:
                pass


def handle_passthrough(client_sock, host, port):
    server_sock = None
    try:
        ips = resolve_system(host)
        for ip in resolve_domain(host):
            if ip not in ips:
                ips.append(ip)
        if not ips:
            client_sock.sendall(b"HTTP/1.1 502 DNS Fail\r\n\r\n")
            client_sock.close()
            return

        # try every IP x every uplink concurrently; passthrough must behave
        # like a direct connection even when the proxy's default route differs
        server_sock = connect_any(ips, port, timeout=4, deadline=7)
        if server_sock is None:
            log_debug(f"passthrough {host}: connect failed ({len(ips)} ips)")
            client_sock.sendall(b"HTTP/1.1 502 Connect Fail\r\n\r\n")
            client_sock.close()
            return
        server_sock.settimeout(None)

        client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        forward_bidirectional(client_sock, server_sock)

    except Exception as e:
        if _is_disconnect(e):
            log_debug(f"passthrough {host} closed: {e}")
        else:
            log_error(f"passthrough {host}: {e}")
    finally:
        for s in [client_sock, server_sock]:
            try:
                if s:
                    s.close()
            except Exception:
                pass


def _read_http_body(client_sock, initial, lines):
    """Read the rest of a plain-HTTP body (Content-Length or chunked)."""
    length = 0
    chunked = False
    for line in lines[1:]:
        lower = line.lower()
        if lower.startswith("content-length:"):
            try:
                length = int(line.split(":", 1)[1].strip())
            except ValueError:
                length = 0
        elif lower.startswith("transfer-encoding:") and "chunked" in lower:
            chunked = True

    body = initial
    if chunked:
        while b"\r\n0\r\n\r\n" not in body and not body.endswith(b"0\r\n\r\n"):
            chunk = client_sock.recv(65536)
            if not chunk:
                break
            body += chunk
    elif length > len(body):
        need = length - len(body)
        buf = bytearray(body)
        while need > 0:
            chunk = client_sock.recv(min(65536, need))
            if not chunk:
                break
            buf.extend(chunk)
            need -= len(chunk)
        body = bytes(buf)
    return body


_upgrade_ctx = None
_upgrade_ctx_lock = threading.Lock()


def _upgrade_context():
    """TLS context for HTTP→HTTPS upgrades.

    Video CDN edges serve the original Host over TLS with a shared edge
    certificate (e.g. *.cdn.myqcloud.com), so the chain is verified but the
    hostname is not: the certificate never covers the per-video CDN alias.
    """
    global _upgrade_ctx
    with _upgrade_ctx_lock:
        if _upgrade_ctx is None:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_REQUIRED
            try:
                ctx.set_alpn_protocols(["http/1.1"])
            except Exception:
                pass
            _upgrade_ctx = ctx
        return _upgrade_ctx


_PLAYLIST_MAX = 8 * 1024 * 1024
_PLAYLIST_URI_RX = re.compile(rb"https://([A-Za-z0-9.\-]+)")


def _read_playlist_response(tls):
    """Read the response head; return (lines, body, raw).

    ``body`` is only set for a rewriteable 200 response; otherwise ``raw``
    carries the bytes already received so the caller can relay them as-is.
    """
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = tls.recv(65536)
        if not chunk:
            return None, None, buf
        buf += chunk
        if len(buf) > 65536:
            return None, None, buf

    head, _, rest = buf.partition(b"\r\n\r\n")
    raw = head + b"\r\n\r\n" + rest
    lines = head.decode("iso-8859-1").split("\r\n")
    status = lines[0].split(" ", 2)
    if len(status) < 2 or status[1] != "200":
        return None, None, raw

    length = None
    for line in lines[1:]:
        lower = line.lower()
        if lower.startswith("transfer-encoding:") and "chunked" in lower:
            return None, None, raw
        if lower.startswith("content-length:"):
            try:
                length = int(line.split(":", 1)[1].strip())
            except ValueError:
                return None, None, raw
    if length is None or length > _PLAYLIST_MAX:
        return None, None, raw

    body = rest
    while len(body) < length:
        chunk = tls.recv(65536)
        if not chunk:
            return None, None, raw
        body += chunk
    return lines, body[:length], raw


def _rewrite_playlist(host, body):
    """Downgrade URIs of hosts whose TLS edge is black-holed (see config)."""
    suffixes = config.HTTP_DOWNGRADE_SUFFIXES
    if not suffixes:
        return None

    def repl(match):
        target = match.group(1).decode("ascii", "ignore").lower()
        if matches_suffix(target, suffixes):
            return b"http://" + match.group(1)
        return match.group(0)

    rewritten = _PLAYLIST_URI_RX.sub(repl, body)
    if rewritten == body:
        return None
    log_debug(f"playlist downgrade {host}: {len(body)} -> {len(rewritten)} bytes")
    return rewritten


def _send_rewritten_playlist(client_sock, lines, body):
    kept = [lines[0]]
    for line in lines[1:]:
        lower = line.lower()
        if lower.startswith(("content-length:", "connection:",
                             "transfer-encoding:")):
            continue
        kept.append(line)
    kept.append("Content-Length: " + str(len(body)))
    kept.append("Connection: close")
    client_sock.sendall(("\r\n".join(kept) + "\r\n\r\n").encode("iso-8859-1")
                        + body)


def handle_http_upgrade(client_sock, host, path, lines, body):
    """Re-issue a plain-HTTP request over TLS (port 443) and relay the reply."""
    tls = None
    raw = None
    try:
        ips = resolve_system(host)
        for ip in resolve_domain(host):
            if ip not in ips:
                ips.append(ip)
        if not ips:
            client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            client_sock.close()
            return

        is_playlist = path.split("?")[0].lower().endswith(".m3u8")
        headers = []
        has_host = False
        for line in lines[1:]:
            lower = line.lower()
            if lower.startswith(("proxy-connection:", "proxy-authorization:",
                                 "connection:")):
                continue
            # 播放器探测时必带 Range: bytes=0-，CDN 会回 206 分片响应，
            # 无法整体改写；去掉 Range 拿 200 完整播放列表。
            if is_playlist and lower.startswith("range:"):
                continue
            if lower.startswith("host:"):
                has_host = True
            headers.append(line)
        if not has_host:
            headers.insert(0, f"Host: {host}")
        # 每个升级请求翻成一个独立的短连接，响应读完即关，转发放到
        # forward_bidirectional 里直到任一端断开
        headers.append("Connection: close")
        payload = (lines[0] + "\r\n" + "\r\n".join(headers)
                   + "\r\n\r\n").encode("iso-8859-1") + body

        raw = connect_any(ips, 443, timeout=4, deadline=7)
        if raw is None:
            log_debug(f"http->https {host}: connect failed ({len(ips)} ips)")
            client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            client_sock.close()
            return

        try:
            tls = _upgrade_context().wrap_socket(raw, server_hostname=host)
        finally:
            if tls is None:
                raw.close()
        raw = None
        tls.sendall(payload)
        tls.settimeout(20)
        log_debug(f"http->https upgrade {host}{path}")

        # m3u8 里可能出现 443 被黑洞、80 可用的主机（如 AES key），
        # 把小体积播放列表完整读回并改写后再发给播放器。
        if is_playlist:
            resp_lines, resp_body, resp_raw = _read_playlist_response(tls)
            if resp_lines is not None:
                rewritten = _rewrite_playlist(host, resp_body)
                _send_rewritten_playlist(
                    client_sock, resp_lines, rewritten or resp_body)
                return
            if resp_raw:
                client_sock.sendall(resp_raw)
                tls.settimeout(None)
                forward_bidirectional(client_sock, tls)
                tls = None
            return

        tls.settimeout(None)
        forward_bidirectional(client_sock, tls)
        tls = None
    except Exception as e:
        if _is_disconnect(e):
            log_debug(f"http->https {host} closed: {e}")
        else:
            log_error(f"http->https {host}: {e}")
    finally:
        for s in (client_sock, tls, raw):
            try:
                if s:
                    s.close()
            except Exception:
                pass


def handle_http_request(client_sock, request):
    try:
        from urllib.parse import urlparse
        head, body = request.split(b"\r\n\r\n", 1)
        lines = head.decode("iso-8859-1").split("\r\n")
        first_line = lines[0]
        url = first_line.split(" ")[1] if " " in first_line else ""
        if not url.startswith("http://"):
            client_sock.close()
            return

        parsed = urlparse(url)
        host = parsed.hostname
        port = parsed.port or 80
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query

        body = _read_http_body(client_sock, body, lines)
        lines[0] = f"{first_line.split(' ')[0]} {path} HTTP/1.1"

        # 校园网 DPI 对明文 HTTP 的视频地址（.m3u8/.ts）只放行握手、随后
        # 丢弃请求，客户端因此永远等不到响应；同一 CDN 的 TLS 端口不受
        # 影响，这里把请求原样改走 HTTPS 重新发起。
        if port == 80 and host and matches_suffix(
                host, config.HTTP_UPGRADE_SUFFIXES):
            handle_http_upgrade(client_sock, host, path, lines, body)
            return

        payload = ("\r\n".join(lines).encode("iso-8859-1")
                   + b"\r\n\r\n" + body)

        ips = resolve_system(host)
        for ip in resolve_domain(host):
            if ip not in ips:
                ips.append(ip)
        if not ips:
            client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            client_sock.close()
            return

        server_sock = connect_any(ips, port, timeout=4, deadline=7)
        if server_sock is None:
            log_debug(f"http {host}: connect failed ({len(ips)} ips)")
            client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            client_sock.close()
            return
        server_sock.sendall(payload)
        server_sock.settimeout(None)
        forward_bidirectional(client_sock, server_sock)
    except Exception as e:
        if _is_disconnect(e):
            log_debug(f"http request closed: {e}")
        else:
            log_error(f"http request failed: {e}")
        try:
            client_sock.close()
        except Exception:
            pass


def handle_client(client_sock, addr):
    try:
        client_sock.settimeout(30)
        request = b""
        while b"\r\n\r\n" not in request:
            chunk = client_sock.recv(65536)
            if not chunk:
                client_sock.close()
                return
            request += chunk
        client_sock.settimeout(None)

        first_line = request.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
        parts = first_line.split()
        method = parts[0] if parts else ""
        raw_target = parts[1] if len(parts) > 1 else ""

        # 智能 PAC 分流分发服务：浏览器或系统拉取 PAC 脚本。
        # 只接受 origin-form 路径（以 / 开头），否则全局代理模式下访问
        # 任意 http://host/pac 都会被错误地替换成本地 PAC 脚本。
        if method == "GET" and raw_target.startswith("/") and (
            raw_target in ("/proxy.pac", "/pac", "/wpad.dat")
            or raw_target.endswith("/proxy.pac")
            or raw_target.endswith("/pac")
        ):
            from . import rules_manager
            pac_text = rules_manager.generate_pac_script(
                port=config.LISTEN_PORT,
                blocked_suffixes=config.BLOCKED_SUFFIXES,
                rewrites=config.SNI_REWRITE,
                passthrough_suffixes=config.PASSTHROUGH_SUFFIXES
            )
            pac_bytes = pac_text.encode("utf-8")
            resp = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/x-ns-proxy-autoconfig; charset=utf-8\r\n"
                b"Content-Length: " + str(len(pac_bytes)).encode("ascii") + b"\r\n"
                b"Cache-Control: no-cache, no-store, must-revalidate\r\n"
                b"Access-Control-Allow-Origin: *\r\n"
                b"Connection: close\r\n\r\n" + pac_bytes
            )
            client_sock.sendall(resp)
            client_sock.close()
            return

        if first_line.startswith("CONNECT"):
            if len(parts) >= 2:
                host_port = parts[1]
                if ":" in host_port:
                    host, port = host_port.rsplit(":", 1)
                    port = int(port)
                else:
                    host, port = host_port, 443

                if is_passthrough_domain(host):
                    handle_passthrough(client_sock, host, port)
                elif is_blocked_domain(host):
                    handle_https_mitm(client_sock, host, port)
                else:
                    handle_passthrough(client_sock, host, port)
                return
        else:
            handle_http_request(client_sock, request)
            return

        client_sock.close()
    except Exception as e:
        if _is_disconnect(e):
            log_debug(f"client {addr} closed: {e}")
        else:
            log_error(f"client {addr}: {e}")
        try:
            client_sock.close()
        except Exception:
            pass


def _write_pid():
    try:
        os.makedirs(os.path.dirname(config.PID_FILE), exist_ok=True)
        with open(config.PID_FILE, "w", encoding="ascii") as f:
            f.write(str(os.getpid()))
    except Exception as e:
        log_warning(f"cannot write pid file: {e}")


def _remove_pid():
    try:
        if os.path.exists(config.PID_FILE):
            with open(config.PID_FILE, "r", encoding="ascii") as f:
                if f.read().strip() == str(os.getpid()):
                    os.remove(config.PID_FILE)
    except Exception:
        pass


def main():
    from . import rules_manager
    rules_manager.load_rules()
    rules_manager.export_pac_file()

    ensure_identity()
    load_strategy_cache()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((config.LISTEN_HOST, config.LISTEN_PORT))
    server.listen(200)

    log("=" * 60)
    log(f"  MITM SNI Proxy v{config.VERSION} - Campus Network Bypass")
    log(f"  Listening: {config.LISTEN_HOST}:{config.LISTEN_PORT}")
    if config.STRICT_UPSTREAM:
        mode = "strict" + (", static assets compat"
                           if config.ASSET_COMPAT else "")
        log(f"  Upstream TLS: certificate chain + hostname ({mode})")
    else:
        log("  Upstream TLS: certificate chain + hostname when possible")
    log(f"  MITM suffix list: {len(config.BLOCKED_SUFFIXES)} entries")
    log(f"  Allowed SNI pool: {', '.join(config.ALLOWED_SNI_POOL)}")
    log("  Waiting for connections...")
    log("-" * 60)
    if sys.stdout:
        try:
            print(f"MITM SNI Proxy v{config.VERSION} listening on "
                  f"{config.LISTEN_HOST}:{config.LISTEN_PORT}", flush=True)
        except Exception:
            pass

    _write_pid()
    try:
        while True:
            try:
                client_sock, addr = server.accept()
                t = threading.Thread(target=handle_client, args=(client_sock, addr))
                t.daemon = True
                t.start()
            except KeyboardInterrupt:
                log("Stopped")
                break
            except Exception as e:
                log_error(f"accept: {e}")
    finally:
        _remove_pid()
