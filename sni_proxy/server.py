"""Proxy server: CONNECT handling, MITM/passthrough forwarding, main loop."""

import os
import socket
import ssl
import sys
import threading

from . import config
from .certs import ensure_identity, generate_site_cert
from .logsetup import log, log_debug, log_error, log_warning
from .netutil import is_blocked_domain, resolve_domain, resolve_system
from .upstream import connect_upstream, load_strategy_cache
from .uplinks import connect_any, connect_host_direct, connect_tcp


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
    t1 = threading.Thread(target=pump, args=(a, b), daemon=True)
    t2 = threading.Thread(target=pump, args=(b, a), daemon=True)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    for s in (a, b):
        try:
            s.close()
        except Exception:
            pass


def soft_fail_mitm(client_sock, host):
    """Upstream totally dead: complete TLS with browser, answer 204 for everything.
    Page JS treats telemetry endpoints as done; rendering is not affected."""
    try:
        client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        cert_file, key_file = generate_site_cert(host)
        if not cert_file:
            client_sock.close()
            return
        server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_ctx.load_cert_chain(cert_file, key_file)
        try:
            server_ctx.set_alpn_protocols(["http/1.1"])
        except Exception:
            pass
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
            log(f"  [SOFT] {host}: {sni_used} -> 204 soft-fail")
            soft_fail_mitm(client_sock, host)
            return

        client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")

        cert_file, key_file = generate_site_cert(host)
        if not cert_file:
            client_sock.close()
            upstream.close()
            return

        server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_ctx.load_cert_chain(cert_file, key_file)
        try:
            server_ctx.set_alpn_protocols(["http/1.1"])
        except Exception:
            pass

        try:
            tls_client = server_ctx.wrap_socket(client_sock, server_side=True)
        except ssl.SSLError:
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
            server_sock = connect_host_direct(host, port, timeout=8)
        if server_sock is None:
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


def handle_http_request(client_sock, request):
    try:
        from urllib.parse import urlparse
        first_line = request.split("\r\n")[0]
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

        lines = request.split("\r\n")
        lines[0] = f"{first_line.split(' ')[0]} {path} HTTP/1.1"
        new_request = "\r\n".join(lines)

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
            server_sock = connect_host_direct(host, port, timeout=8)
        if server_sock is None:
            client_sock.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            client_sock.close()
            return
        server_sock.sendall(new_request.encode())
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

        request_str = request.decode(errors="replace")
        first_line = request_str.split("\r\n")[0]

        if first_line.startswith("CONNECT"):
            parts = first_line.split()
            if len(parts) >= 2:
                host_port = parts[1]
                if ":" in host_port:
                    host, port = host_port.rsplit(":", 1)
                    port = int(port)
                else:
                    host, port = host_port, 443

                if is_blocked_domain(host):
                    handle_https_mitm(client_sock, host, port)
                else:
                    handle_passthrough(client_sock, host, port)
                return
        else:
            handle_http_request(client_sock, request_str)
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
    ensure_identity()
    load_strategy_cache()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((config.LISTEN_HOST, config.LISTEN_PORT))
    server.listen(200)

    log("=" * 60)
    log(f"  MITM SNI Proxy v{config.VERSION} - Campus Network Bypass")
    log(f"  Listening: {config.LISTEN_HOST}:{config.LISTEN_PORT}")
    log("  Upstream TLS: certificate chain required"
        + (" + hostname (strict)" if config.STRICT_UPSTREAM
           else " + hostname when possible"))
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
