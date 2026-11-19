"""Network Speed Test Service: latency, jitter, download & upload bandwidth measurements.

Supports:
- Direct mode & local SNI Proxy mode (127.0.0.1:8888);
- Multi-sample TCP-handshake latency and jitter calculation;
- Real single-stream HTTP Range download sampling with candidate probing;
- Real HTTP POST upload sampling (chunked, streamed);
- Real-time progress and instantaneous speed callbacks for UI animations;
- Cooperative cancellation.

All measurements are real network measurements. When a measurement cannot be
performed the corresponding method returns ``None`` and records the reason in
``self.*_error`` / ``self.detail`` so the UI can show an explicit failure
instead of a fabricated ``0.00``.
"""

import http.client
import logging
import os
import socket
import ssl
import threading
import time
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# --- Download tuning -------------------------------------------------------
DOWNLOAD_CHUNK = 64 * 1024
PROBE_BYTES = 16 * 1024
MAX_DOWNLOAD_BYTES = 30 * 1024 * 1024   # single-stream cap for one run
DOWNLOAD_DURATION = 6.0
PROBE_TIMEOUT = 5.0
DOWNLOAD_TIMEOUT = 12.0

# --- Upload tuning ---------------------------------------------------------
UPLOAD_CHUNK = 32 * 1024
UPLOAD_PROBE_BYTES = 8 * 1024
MAX_UPLOAD_BYTES = 32 * 1024 * 1024
UPLOAD_DURATION = 2.5
UPLOAD_TIMEOUT = 10.0
# Probes run in parallel so that endpoints whose TLS handshake is blackholed
# cannot eat the whole upload phase one after another.
UPLOAD_PROBE_TIMEOUT = 2.5      # per-endpoint probe timeout
UPLOAD_PROBE_BUDGET = 3.0       # wall clock budget for probing all endpoints
UPLOAD_RESPONSE_TIMEOUT = 1.5   # wait for the reply after the body was sent
UPLOAD_PHASE_BUDGET = 6.5       # whole upload phase (probe + measurement)

# Domestic mirror sources (preferred first). Mirrors exposed over HTTPS are
# reachable from most mainland networks; the list is probed before use.
DOMESTIC_DOWNLOAD_URLS = [
    "https://mirrors.cloud.tencent.com/ubuntu/ls-lR.gz",
    "https://mirrors.huaweicloud.com/ubuntu/ls-lR.gz",
    "https://mirrors.aliyun.com/ubuntu/ls-lR.gz",
    "https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ls-lR.gz",
    "https://mirrors.ustc.edu.cn/ubuntu/ls-lR.gz",
    "https://mirrors.aliyun.com/centos/7/os/x86_64/Packages/kernel-3.10.0-1160.el7.x86_64.rpm",
]

# Public endpoints that accept a POST body (used for real upload sampling).
# Ordered by preference: HTTPS first (most accurate when reachable), then
# plain-HTTP fallbacks for networks that block foreign TLS (e.g. campus
# gateways) but still allow port 80. ``max_bytes`` keeps a single request
# below the server's body limit (413 otherwise); ``limited`` marks nodes whose
# reply/throughput caps the measurement, so the result can be labelled as an
# estimate while still reporting the real measured rate.
UPLOAD_ENDPOINTS = [
    {"url": "https://speed.cloudflare.com/__up",
     "max_bytes": 16 * 1024 * 1024, "limited": False},
    # httpbin rejects bodies above ~1MB (HTTP 413); postman-echo echoes the
    # body back, so its read/echo rate caps the measured send speed.
    {"url": "https://httpbin.org/post",
     "max_bytes": 1024 * 1024, "limited": True},
    {"url": "https://postman-echo.com/post",
     "max_bytes": 1024 * 1024, "limited": True},
    # Plain HTTP fallbacks (reachable when outbound HTTPS is blocked).
    {"url": "http://httpbin.org/post",
     "max_bytes": 1024 * 1024, "limited": True},
    {"url": "http://postman-echo.com/post",
     "max_bytes": 256 * 1024, "limited": True},
    # Domestic httpbin mirror: rejects bodies above 32KB, last-resort only.
    {"url": "http://httpbin.zcorky.com/post",
     "max_bytes": 32 * 1024, "limited": True},
]

# Fallback TCP latency targets, used only when the configured target is down.
LATENCY_FALLBACK_HOSTS = [
    "www.baidu.com",
    "mirrors.cloud.tencent.com",
    "183.2.172.185",  # www.baidu.com edge IP
    "223.5.5.5",
]

SPEED_TARGETS = [
    {
        "name": "国内镜像自动选择",
        "ping_url": "https://mirrors.cloud.tencent.com",
        "download_urls": list(DOMESTIC_DOWNLOAD_URLS),
    },
    {
        "name": "阿里云开源镜像站 (Aliyun)",
        "ping_url": "http://mirrors.aliyun.com",
        "download_urls": [
            "https://mirrors.aliyun.com/ubuntu/ls-lR.gz",
            "https://mirrors.aliyun.com/centos/7/os/x86_64/Packages/kernel-3.10.0-1160.el7.x86_64.rpm",
        ] + [u for u in DOMESTIC_DOWNLOAD_URLS
             if "mirrors.aliyun.com" not in u],
    },
    {
        "name": "清华大学开源镜像站 (Tsinghua)",
        "ping_url": "https://mirrors.tuna.tsinghua.edu.cn",
        "download_urls": [
            "https://mirrors.tuna.tsinghua.edu.cn/ubuntu/ls-lR.gz",
        ] + [u for u in DOMESTIC_DOWNLOAD_URLS
             if "tuna.tsinghua" not in u],
    },
    {
        "name": "中国科学技术大学镜像站 (USTC)",
        "ping_url": "https://mirrors.ustc.edu.cn",
        "download_urls": [
            "https://mirrors.ustc.edu.cn/ubuntu/ls-lR.gz",
        ] + [u for u in DOMESTIC_DOWNLOAD_URLS
             if "mirrors.ustc.edu.cn" not in u],
    },
]


def _make_ssl_context():
    """Create a permissive SSL context for speed tests that tolerates internal gateway certs."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def get_network_info():
    """Detect local IP and host network info."""
    local_ip = "127.0.0.1"
    host_name = socket.gethostname()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("223.5.5.5", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass
    return {
        "hostname": host_name,
        "local_ip": local_ip,
        "proxy_endpoint": "127.0.0.1:8888",
    }


class SpeedTester:
    """Speed test worker instance with cancellation support."""

    def __init__(self, target_idx=0, use_proxy=False, proxy_host="127.0.0.1",
                 proxy_port=8888, custom_url=None):
        self.target_idx = target_idx
        self.use_proxy = use_proxy
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port
        self.custom_url = custom_url
        self._cancelled = False

        # Failure reasons / chosen endpoints, consumed by run() and the GUI.
        self.download_error = None
        self.upload_error = None
        self.download_source = None
        self.upload_endpoint = None
        self.detail = {}

    def cancel(self):
        self._cancelled = True

    def _get_opener(self):
        ctx = _make_ssl_context()
        https_handler = urllib.request.HTTPSHandler(context=ctx)
        if self.use_proxy:
            proxy_url = f"http://{self.proxy_host}:{self.proxy_port}"
            proxy_handler = urllib.request.ProxyHandler({
                "http": proxy_url,
                "https": proxy_url,
            })
            opener = urllib.request.build_opener(proxy_handler, https_handler)
        else:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}), https_handler)
        opener.addheaders = [("User-Agent", USER_AGENT)]
        return opener

    # ------------------------------------------------------------------
    # Latency / jitter
    # ------------------------------------------------------------------
    def _latency_targets(self, ping_url):
        targets = []
        try:
            parsed = urllib.parse.urlsplit(ping_url or "")
            host = parsed.hostname
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if host:
                targets.append((host, port))
        except Exception:
            pass
        for host in LATENCY_FALLBACK_HOSTS:
            if all(host != h for h, _ in targets):
                targets.append((host, 443))
        return targets

    def _tcp_latency_samples(self, host, port, count, on_progress=None):
        """Sample TCP handshake RTT (SYN -> SYN/ACK) to host:port."""
        try:
            infos = socket.getaddrinfo(host, port, socket.AF_INET,
                                       socket.SOCK_STREAM)
        except OSError as e:
            logger.debug("延迟测试 DNS 解析失败 %s: %s", host, e)
            return []
        ips = []
        for info in infos:
            ip = info[4][0]
            if ip not in ips:
                ips.append(ip)
        if not ips:
            return []

        samples = []
        for i in range(count):
            if self._cancelled:
                break
            ip = ips[i % len(ips)]
            t0 = time.perf_counter()
            sock = None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2.5)
                sock.connect((ip, port))
                samples.append((time.perf_counter() - t0) * 1000.0)
            except OSError as e:
                logger.debug("延迟测试连接失败 %s (%s): %s", host, ip, e)
                if not samples:
                    # Target unreachable: stop early so the next candidate is
                    # tried instead of waiting 5 x timeout.
                    return []
            finally:
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass

            if on_progress:
                on_progress({
                    "phase": "ping",
                    "progress": int((i + 1) / max(1, count) * 20),
                    "current_sample": samples[-1] if samples else None,
                    "msg": f"正在测试网络延迟 ({i + 1}/{count})...",
                })
            time.sleep(0.05)
        return samples

    def _http_latency_samples(self, ping_url, count, on_progress=None):
        """Sample HTTP HEAD round trips (used in proxy mode)."""
        opener = self._get_opener()
        samples = []
        for i in range(count):
            if self._cancelled:
                break
            t0 = time.perf_counter()
            try:
                req = urllib.request.Request(ping_url, method="HEAD")
                with opener.open(req, timeout=4.0) as resp:
                    resp.read(64)
                samples.append((time.perf_counter() - t0) * 1000.0)
            except Exception as e:
                logger.debug("代理模式延迟测试失败 %s: %s", ping_url, e)
                try:
                    req = urllib.request.Request(ping_url)
                    with opener.open(req, timeout=4.0) as resp:
                        resp.read(64)
                    samples.append((time.perf_counter() - t0) * 1000.0)
                except Exception as e2:
                    logger.debug("代理模式延迟测试 GET 亦失败: %s", e2)

            if on_progress:
                on_progress({
                    "phase": "ping",
                    "progress": int((i + 1) / max(1, count) * 20),
                    "current_sample": samples[-1] if samples else None,
                    "msg": f"正在测试网络延迟 ({i + 1}/{count})...",
                })
            time.sleep(0.05)
        return samples

    def measure_latency_and_jitter(self, ping_url, count=5, on_progress=None):
        """Measure average latency (ms) and jitter (ms).

        Returns ``(None, None)`` when no sample could be collected.
        """
        samples = []
        if self.use_proxy:
            samples = self._http_latency_samples(ping_url, count, on_progress)
        else:
            for host, port in self._latency_targets(ping_url):
                if self._cancelled:
                    break
                samples = self._tcp_latency_samples(
                    host, port, count, on_progress)
                if samples:
                    logger.debug("延迟测试使用目标 %s:%s", host, port)
                    break
                logger.debug("延迟测试目标不可用：%s:%s", host, port)

        if not samples:
            self.detail["ping_error"] = "无可用延迟测试目标"
            return None, None

        avg_latency = sum(samples) / len(samples)
        if len(samples) > 1:
            diffs = [abs(samples[j] - samples[j - 1])
                     for j in range(1, len(samples))]
            jitter = sum(diffs) / len(diffs)
        else:
            jitter = 0.0

        return round(avg_latency, 1), round(jitter, 1)

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------
    def _download_candidates(self, download_urls):
        urls = []
        if self.custom_url:
            urls.append(self.custom_url)
        for url in list(download_urls or []) + DOMESTIC_DOWNLOAD_URLS:
            if url and url not in urls:
                urls.append(url)
        return urls

    def _probe_download_url(self, url):
        """Short Range GET probe. Returns (ok, reason, range_supported)."""
        opener = self._get_opener()
        last_reason = "未知错误"
        for use_range in (True, False):
            headers = {
                "User-Agent": USER_AGENT,
                "Accept-Encoding": "identity",
            }
            if use_range:
                headers["Range"] = f"bytes=0-{PROBE_BYTES - 1}"
            t0 = time.perf_counter()
            try:
                req = urllib.request.Request(url, headers=headers)
                with opener.open(req, timeout=PROBE_TIMEOUT) as resp:
                    code = resp.getcode()
                    if code not in (200, 206):
                        last_reason = f"HTTP {code}"
                        continue
                    data = resp.read(PROBE_BYTES)
                    if not data:
                        last_reason = "响应为空"
                        continue
                    ranged = bool(use_range and code == 206
                                  and resp.headers.get("Content-Range"))
                    reason = (f"HTTP {code}，首包 "
                              f"{(time.perf_counter() - t0) * 1000:.0f} ms")
                    return True, reason, ranged
            except Exception as e:
                last_reason = f"{type(e).__name__}: {e}"
                logger.debug("下载候选探测失败 %s (Range=%s): %s",
                             url, use_range, last_reason)
        return False, last_reason, False

    def measure_download(self, download_urls, duration=DOWNLOAD_DURATION,
                         on_progress=None):
        """Measure real download throughput (Mbps).

        Returns ``None`` when no candidate is usable or no data was received;
        the reason is stored in ``self.download_error``.
        """
        self.download_error = None
        self.download_source = None
        if self._cancelled:
            return None

        candidates = self._download_candidates(download_urls)
        chosen_url = None
        range_supported = False
        reasons = []
        for url in candidates:
            if self._cancelled:
                return None
            ok, reason, ranged = self._probe_download_url(url)
            logger.debug("下载测速候选 %s -> %s（%s）", url, ok, reason)
            if ok:
                chosen_url = url
                range_supported = ranged
                break
            reasons.append(f"{urllib.parse.urlsplit(url).hostname}: {reason}")

        if not chosen_url:
            self.download_error = (
                "无可用的下载测速节点（已探测 "
                f"{len(candidates)} 个源）：" + "；".join(reasons[:4]))
            return None

        self.download_source = chosen_url
        opener = self._get_opener()
        headers = {
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "identity",
        }
        if range_supported:
            headers["Range"] = f"bytes=0-{MAX_DOWNLOAD_BYTES - 1}"

        total_bytes = 0
        first_byte_ts = None
        last_tick = None
        last_bytes = 0
        error = None

        try:
            req = urllib.request.Request(chosen_url, headers=headers)
            with opener.open(req, timeout=DOWNLOAD_TIMEOUT) as resp:
                code = resp.getcode()
                if code not in (200, 206):
                    self.download_error = f"下载节点返回 HTTP {code}"
                    return None
                while total_bytes < MAX_DOWNLOAD_BYTES:
                    if self._cancelled:
                        break
                    chunk = resp.read(DOWNLOAD_CHUNK)
                    if not chunk:
                        break
                    now = time.perf_counter()
                    if first_byte_ts is None:
                        first_byte_ts = now      # exclude connect/TLS setup
                        last_tick = now
                    total_bytes += len(chunk)
                    elapsed = now - first_byte_ts

                    if now - last_tick >= 0.15:
                        inst_sec = max(0.001, now - last_tick)
                        inst_mbps = ((total_bytes - last_bytes) * 8.0
                                     / (1024 * 1024) / inst_sec)
                        if on_progress:
                            on_progress({
                                "phase": "download",
                                "progress": min(75, 20 + int(elapsed / duration * 55)),
                                "speed_mbps": round(inst_mbps, 2),
                                "downloaded_mb": round(
                                    total_bytes / (1024 * 1024), 2),
                                "msg": (f"正在测试下载带宽... "
                                        f"({elapsed:.1f}s / {duration:.0f}s)"),
                            })
                        last_tick = now
                        last_bytes = total_bytes

                    if elapsed >= duration:
                        break
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            logger.debug("下载测速中断 %s: %s", chosen_url, error)

        if first_byte_ts is None or total_bytes == 0:
            self.download_error = error or "未收到任何数据"
            return None

        elapsed = max(0.05, time.perf_counter() - first_byte_ts)
        mbps = (total_bytes * 8.0 / (1024 * 1024)) / elapsed

        if error and total_bytes < 512 * 1024:
            self.download_error = error
            return None
        if error:
            # Partial but still meaningful measurement.
            self.detail["download_warning"] = error

        self.detail["download_bytes"] = total_bytes
        self.detail["download_elapsed"] = round(elapsed, 2)
        return round(mbps, 2)

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------
    def _open_upload_conn(self, scheme, host, port, timeout):
        ctx = _make_ssl_context()
        if self.use_proxy:
            if scheme == "https":
                conn = http.client.HTTPSConnection(
                    self.proxy_host, self.proxy_port, timeout=timeout,
                    context=ctx)
                conn.set_tunnel(host, port)
            else:
                conn = http.client.HTTPConnection(
                    self.proxy_host, self.proxy_port, timeout=timeout)
            return conn
        if scheme == "https":
            return http.client.HTTPSConnection(
                host, port, timeout=timeout, context=ctx)
        return http.client.HTTPConnection(host, port, timeout=timeout)

    def _upload_request_path(self, scheme, host, port, path):
        if self.use_proxy and scheme == "http":
            return f"http://{host}:{port}{path}"
        return path

    @staticmethod
    def _split_endpoint(url):
        parsed = urllib.parse.urlsplit(url)
        scheme = parsed.scheme or "https"
        host = parsed.hostname
        port = parsed.port or (443 if scheme == "https" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        return scheme, host, port, path

    def _probe_upload_endpoint(self, url, timeout=PROBE_TIMEOUT):
        """Tiny chunked POST probe. Returns (ok, reason)."""
        scheme, host, port, path = self._split_endpoint(url)
        if not host:
            return False, "无效端点"
        conn = None
        t0 = time.perf_counter()
        try:
            conn = self._open_upload_conn(scheme, host, port, timeout)
            conn.putrequest("POST", self._upload_request_path(
                scheme, host, port, path), skip_accept_encoding=True)
            conn.putheader("Transfer-Encoding", "chunked")
            conn.putheader("Content-Type", "application/octet-stream")
            conn.putheader("User-Agent", USER_AGENT)
            conn.endheaders()
            payload = b"\x00" * UPLOAD_PROBE_BYTES
            conn.send(b"%x\r\n" % len(payload) + payload + b"\r\n")
            conn.send(b"0\r\n\r\n")
            resp = conn.getresponse()
            resp.read(256)
            if resp.status >= 400:
                return False, f"HTTP {resp.status}"
            return True, (f"HTTP {resp.status}，"
                          f"{(time.perf_counter() - t0) * 1000:.0f} ms")
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    @staticmethod
    def _upload_specs():
        """Normalise ``UPLOAD_ENDPOINTS`` into dicts (plain URLs still work)."""
        specs = []
        for item in UPLOAD_ENDPOINTS:
            if isinstance(item, str):
                specs.append({"url": item, "max_bytes": MAX_UPLOAD_BYTES,
                              "limited": False})
            elif isinstance(item, dict) and item.get("url"):
                specs.append({
                    "url": item["url"],
                    "max_bytes": max(UPLOAD_PROBE_BYTES, min(
                        int(item.get("max_bytes", MAX_UPLOAD_BYTES)),
                        MAX_UPLOAD_BYTES)),
                    "limited": bool(item.get("limited", False)),
                })
        return specs

    def _probe_upload_endpoints(self, specs, budget=UPLOAD_PROBE_BUDGET):
        """Probe all upload candidates in parallel, preserving list order.

        Parallel probing matters on networks where outbound TLS is blackholed:
        a sequential probe would spend the entire budget on handshake
        timeouts before ever reaching the plain-HTTP fallbacks.
        """
        results = [(False, "探测未完成（超出时间预算）")] * len(specs)
        lock = threading.Lock()

        def worker(idx, url):
            outcome = self._probe_upload_endpoint(
                url, timeout=UPLOAD_PROBE_TIMEOUT)
            with lock:
                results[idx] = outcome

        threads = []
        for idx, spec in enumerate(specs):
            thread = threading.Thread(target=worker, args=(idx, spec["url"]),
                                      daemon=True)
            thread.start()
            threads.append(thread)

        deadline = time.perf_counter() + budget
        for thread in threads:
            remaining = deadline - time.perf_counter()
            if remaining <= 0 or self._cancelled:
                break
            thread.join(remaining)
        return results

    def _upload_once(self, spec, deadline, duration, on_progress=None):
        """Stream one chunked POST and time the send phase.

        Returns a dict with keys ``ok``, ``mbps``, ``bytes``, ``elapsed``,
        ``status``, ``error`` (send failure) and ``warning`` (reply unconfirmed).
        """
        url = spec["url"]
        scheme, host, port, path = self._split_endpoint(url)
        max_bytes = spec["max_bytes"]
        chunk_size = min(UPLOAD_CHUNK, max_bytes)
        payload = os.urandom(chunk_size)
        # Keep a little of the phase budget for the server reply so a 200/413
        # can confirm the request instead of timing out.
        remaining = deadline - time.perf_counter()
        send_budget = max(0.8, min(duration, remaining - 1.0))

        result = {
            "ok": False, "mbps": None, "bytes": 0, "elapsed": 0.0,
            "status": None, "error": None, "warning": None,
            "node_limited": bool(spec.get("limited")),
        }
        conn = None
        total_bytes = 0
        t_start = None
        status = None
        error = None
        warning = None

        try:
            conn_timeout = max(1.0, min(UPLOAD_TIMEOUT,
                                        deadline - time.perf_counter()))
            conn = self._open_upload_conn(scheme, host, port, conn_timeout)
            conn.putrequest("POST", self._upload_request_path(
                scheme, host, port, path), skip_accept_encoding=True)
            conn.putheader("Transfer-Encoding", "chunked")
            conn.putheader("Content-Type", "application/octet-stream")
            conn.putheader("User-Agent", USER_AGENT)
            conn.endheaders()

            t_start = time.perf_counter()
            last_tick = t_start
            last_bytes = 0
            while total_bytes < max_bytes:
                if self._cancelled:
                    break
                now = time.perf_counter()
                remaining = deadline - now
                if now - t_start >= send_budget or remaining <= 0.2:
                    break
                conn.sock.settimeout(max(0.5, min(UPLOAD_TIMEOUT, remaining)))
                try:
                    conn.send(b"%x\r\n" % len(payload) + payload + b"\r\n")
                except socket.timeout:
                    error = "上传发送超时"
                    break
                total_bytes += len(payload)
                now = time.perf_counter()
                elapsed = now - t_start

                if now - last_tick >= 0.15:
                    inst_sec = max(0.001, now - last_tick)
                    inst_mbps = ((total_bytes - last_bytes) * 8.0
                                 / (1024 * 1024) / inst_sec)
                    if on_progress:
                        on_progress({
                            "phase": "upload",
                            "progress": min(99, 75 + int(
                                elapsed / max(0.1, send_budget) * 24)),
                            "speed_mbps": round(inst_mbps, 2),
                            "uploaded_mb": round(
                                total_bytes / (1024 * 1024), 2),
                            "msg": (f"正在测试上传带宽... "
                                    f"({elapsed:.1f}s / {send_budget:.0f}s)"),
                        })
                    last_tick = now
                    last_bytes = total_bytes

            result["bytes"] = total_bytes
            send_elapsed = max(0.05, time.perf_counter() - t_start)
            # Finish the chunked body, then wait briefly for the reply.
            conn.sock.settimeout(max(0.5, min(
                UPLOAD_RESPONSE_TIMEOUT, deadline - time.perf_counter())))
            try:
                conn.send(b"0\r\n\r\n")
                resp = conn.getresponse()
                status = resp.status
                resp.read(256)
            except socket.timeout:
                warning = "等待服务器响应超时（未确认完整接收请求体）"
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            logger.debug("上传测速中断 %s: %s", url, error)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

        result["status"] = status
        result["warning"] = warning
        if t_start is None or total_bytes == 0:
            result["error"] = error or "未能向服务器发送任何数据"
            return result
        if error is not None:
            result["bytes"] = total_bytes
            result["error"] = error
            return result
        if status is not None and status >= 400:
            result["error"] = f"服务器拒绝上传（HTTP {status}）"
            return result
        if status is None and warning is None:
            warning = "未收到服务器响应"
            result["warning"] = warning

        result["ok"] = True
        result["elapsed"] = send_elapsed
        result["mbps"] = ((total_bytes * 8.0 / (1024 * 1024))
                          / send_elapsed)
        return result

    def measure_upload(self, duration=UPLOAD_DURATION, on_progress=None):
        """Measure real upload throughput (Mbps) via streaming HTTP POST.

        HTTPS endpoints are tried first; when they are unreachable (e.g. a
        campus gateway blocking foreign TLS) plain-HTTP endpoints on port 80
        are used instead. Returns ``None`` when no endpoint is usable, with the
        reason stored in ``self.upload_error``.
        """
        self.upload_error = None
        self.upload_endpoint = None
        for key in ("upload_note", "upload_estimated", "upload_warning",
                    "upload_bytes", "upload_elapsed", "upload_protocol"):
            self.detail.pop(key, None)
        if self._cancelled:
            return None

        specs = self._upload_specs()
        if not specs:
            self.upload_error = "未配置上传测速端点"
            return None

        phase_deadline = time.perf_counter() + UPLOAD_PHASE_BUDGET
        probes = self._probe_upload_endpoints(specs)
        if self._cancelled:
            return None

        usable = []
        reasons = []
        for spec, (ok, reason) in zip(specs, probes):
            scheme, host, _, _ = self._split_endpoint(spec["url"])
            logger.debug("上传测速端点 %s -> %s（%s）", spec["url"], ok, reason)
            if ok:
                usable.append(spec)
            else:
                reasons.append(f"{host}({scheme}): {reason}")

        if not usable:
            self.upload_error = (
                f"无可用上传测速端点（已探测 {len(specs)} 个）："
                + "；".join(reasons))
            return None

        failures = []
        for attempt, spec in enumerate(usable):
            if self._cancelled:
                return None
            if attempt >= 2:
                break
            if phase_deadline - time.perf_counter() < 1.0:
                failures.append("上传阶段时间预算用尽")
                break

            self.upload_endpoint = spec["url"]
            res = self._upload_once(spec, phase_deadline, duration, on_progress)
            if self._cancelled:
                return None
            if not res["ok"]:
                host = urllib.parse.urlsplit(spec["url"]).hostname
                failures.append(f"{host}: {res['error']}")
                logger.debug("上传实测失败 %s: %s", spec["url"], res["error"])
                continue

            scheme = self._split_endpoint(spec["url"])[0]
            self.detail["upload_bytes"] = res["bytes"]
            self.detail["upload_elapsed"] = round(res["elapsed"], 2)
            self.detail["upload_protocol"] = scheme
            self.detail["upload_estimated"] = bool(
                res["node_limited"] or res["warning"])
            if res["node_limited"]:
                self.detail["upload_note"] = (
                    "该端点回显/限速较慢，数值为实测发送速率，"
                    "受测速节点限制，仅作估算")
            if res["warning"]:
                self.detail["upload_warning"] = res["warning"]
                if not res["node_limited"]:
                    self.detail["upload_note"] = (
                        "未确认服务器完整接收请求体，数值为发送阶段估算")
            return round(res["mbps"], 2)

        self.upload_error = (
            f"上传测速失败（已探测 {len(specs)} 个端点，可用 {len(usable)} 个）："
            + "；".join(failures + reasons[:3]))
        return None

    # ------------------------------------------------------------------
    # Full workflow
    # ------------------------------------------------------------------
    def run(self, on_progress=None):
        """Run the complete speed test workflow and return summary dictionary."""
        target = SPEED_TARGETS[min(len(SPEED_TARGETS) - 1,
                                   max(0, self.target_idx))]
        net_info = get_network_info()
        self.detail = {}

        if on_progress:
            on_progress({
                "phase": "init",
                "progress": 5,
                "msg": f"正在准备测速环境（{net_info['local_ip']}）...",
            })

        # 1. Latency & Jitter
        ping_ms, jitter_ms = self.measure_latency_and_jitter(
            target["ping_url"], count=5, on_progress=on_progress)
        if self._cancelled:
            return None

        # 2. Download speed
        dl_mbps = self.measure_download(
            target["download_urls"], duration=DOWNLOAD_DURATION,
            on_progress=on_progress)
        if self._cancelled:
            return None

        # 3. Upload speed
        ul_mbps = self.measure_upload(
            duration=UPLOAD_DURATION, on_progress=on_progress)
        if self._cancelled:
            return None

        errors = []
        if dl_mbps is None:
            errors.append(f"下载测速失败：{self.download_error or '未知原因'}")
        if ul_mbps is None:
            errors.append(f"上传测速失败：{self.upload_error or '未知原因'}")
        if ping_ms is None:
            errors.append("延迟测量失败：无可用目标")

        now_str = time.strftime("%Y-%m-%d %H:%M:%S")
        res = {
            "timestamp": now_str,
            "target_name": target["name"],
            "mode": "代理通道" if self.use_proxy else "直连测速",
            "download_mbps": dl_mbps,
            "upload_mbps": ul_mbps,
            "ping_ms": ping_ms,
            "jitter_ms": jitter_ms,
            "net_info": net_info,
            "ok": not errors,
            "error": "；".join(errors),
            "detail": {
                "download_source": self.download_source,
                "download_error": self.download_error,
                "upload_endpoint": self.upload_endpoint,
                "upload_error": self.upload_error,
                **self.detail,
            },
        }

        if on_progress:
            on_progress({
                "phase": "done",
                "progress": 100,
                "result": res,
                "msg": "测速完成！" if not errors else "测速结束，部分项目失败",
            })

        return res
