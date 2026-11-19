"""Proxy process discovery, identity checks and lifecycle actions.

Write operations (start/stop/...) are delegated to proxy_manager.ps1 -Action
so the CLI logic, its system-proxy backup/restore rules and the watchdog stay
in exactly one place. The GUI only reads live state itself.
"""

import os
import subprocess
import sys
import threading

from sni_proxy import config

from .util import BASE_DIR, NO_WINDOW, run_hidden

PWSH = "powershell.exe"
PROXY_MANAGER = os.path.join(BASE_DIR, "proxy_manager.ps1")
if not os.path.exists(PROXY_MANAGER) and hasattr(sys, "_MEIPASS"):
    _mei_pm = os.path.join(sys._MEIPASS, "proxy_manager.ps1")
    if os.path.exists(_mei_pm):
        PROXY_MANAGER = _mei_pm

PID_FILE = config.PID_FILE


def _find_listener_pid_netstat(port):
    """Return the PID owning a LISTEN socket on 127.0.0.1:port (netstat)."""
    code, out, _ = run_hidden(
        ["netstat", "-ano", "-p", "tcp"], timeout=15, decode="mbcs")
    if code != 0:
        return None
    for line in out.splitlines():
        parts = line.split()
        # Proto Local Foreign State PID  (states: LISTENING)
        if len(parts) >= 5 and parts[3] == "LISTENING" and len(parts) == 5:
            local = parts[1]
            if local.endswith(f":{port}"):
                try:
                    return int(parts[4])
                except ValueError:
                    return None
    return None


def find_listener_pid(port=None):
    """PID of the process listening on the configured port, or None."""
    port = port or config.LISTEN_PORT
    return _find_listener_pid_netstat(port)


def pid_file_pid():
    """PID recorded by the proxy itself (strong identity signal)."""
    try:
        with open(PID_FILE, "r", encoding="ascii") as f:
            return int(f.read().strip())
    except Exception:
        return None


def _process_name_and_start(pid):
    """Process image name + creation unix ts via the Win32 API (no wmic)."""
    name, start_ts = None, None
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if h:
                try:
                    buf = ctypes.create_unicode_buffer(1024)
                    size = wintypes.DWORD(len(buf))
                    if ctypes.windll.kernel32.QueryFullProcessImageNameW(
                            h, 0, buf, ctypes.byref(size)):
                        name = os.path.basename(buf.value)
                    # creation time
                    class FT(ctypes.Structure):
                        _fields_ = [("dwLowDateTime", wintypes.DWORD),
                                    ("dwHighDateTime", wintypes.DWORD)]
                    ct, et, kt, ut = FT(), FT(), FT(), FT()
                    if ctypes.windll.kernel32.GetProcessTimes(
                            h, ctypes.byref(ct), ctypes.byref(et),
                            ctypes.byref(kt), ctypes.byref(ut)):
                        val = ct.dwHighDateTime << 32 | ct.dwLowDateTime
                        # FILETIME (100ns since 1601-01-01) -> unix
                        start_ts = (val - 116444736000000000) / 1e7
                finally:
                    ctypes.windll.kernel32.CloseHandle(h)
        except Exception:
            pass
    return name, start_ts


def proxy_identity(listener_pid):
    """Classify the listener on the proxy port.

    Returns dict(running, identity, proc_name, pid, start_ts):
      identity: "pidfile" (pid file written by the proxy matches),
                "py" (python process but unverified),
                "foreign" (another program owns the port),
                "none"
    """
    if not listener_pid:
        return {"running": False, "identity": "none", "proc_name": None,
                "pid": None, "start_ts": None}
    name, start_ts = _process_name_and_start(listener_pid)
    saved = pid_file_pid()
    if saved == listener_pid:
        return {"running": True, "identity": "pidfile", "proc_name": name,
                "pid": listener_pid, "start_ts": start_ts}
    if name and name.lower().startswith("python"):
        return {"running": False, "identity": "py", "proc_name": name,
                "pid": listener_pid, "start_ts": start_ts}
    return {"running": False, "identity": "foreign", "proc_name": name,
            "pid": listener_pid, "start_ts": start_ts}


def watchdog_running():
    """True when the watchdog powershell loop is alive (best effort)."""
    code, out, _ = run_hidden(
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_Process -Filter \"Name='powershell.exe'\" | "
         "Where-Object { $_.CommandLine -like '*proxy_watchdog*' }).Count"],
        timeout=15)
    try:
        return code == 0 and int(out.strip()) > 0
    except Exception:
        return False


class ActionRun:
    """Run proxy_manager.ps1 -Action <name> in the current process.

    `on_line` is called (from the worker thread) for each output line.
    Returns (ok: bool, exit_code: int). The manager self-elevates when the
    caller is not admin, so this works from an unelevated GUI too (UAC).
    """

    def __init__(self, action, on_line=None, timeout=600):
        self.action = action
        self.on_line = on_line
        self.timeout = timeout
        self._proc = None
        self.cancelled = False

    def cancel(self):
        self.cancelled = True
        p = self._proc
        if p:
            try:
                p.kill()
            except Exception:
                pass

    def run(self):
        cmd = [PWSH, "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-File", PROXY_MANAGER, "-Action", self.action,
               "-NonInteractive"]
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                creationflags=NO_WINDOW)
        except OSError as e:
            if self.on_line:
                self.on_line(f"[!!] 无法启动管理器进程：{e}")
            return False, 127

        ok = True

        def _pump_output():
            try:
                for raw in self._proc.stdout:
                    line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                    if self.on_line and line:
                        self.on_line(line)
            except Exception:
                pass

        # 输出必须放在独立线程里读：客户端只按行检查超时，一旦管理器
        # 卡住不输出（例如 UAC 弹窗一直无人点），主线程会永久阻塞。
        reader = threading.Thread(target=_pump_output, daemon=True,
                                  name=f"sni-action-out-{self.action}")
        reader.start()
        try:
            code = self._proc.wait(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            if self.on_line:
                self.on_line("[!!] 操作超时，已请求终止管理器进程")
            self.cancel()
            ok = False
            try:
                code = self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                code = 124
        except Exception as e:
            if self.on_line:
                self.on_line(f"[!!] 执行失败：{e}")
            code = 1
            ok = False
        reader.join(timeout=3)
        if self.cancelled:
            ok = False
        return ok and code == 0, code


def run_action_async(action, on_line=None, on_done=None, timeout=600):
    """Fire an ActionRun in a daemon thread; callbacks run on that thread."""
    runner = ActionRun(action, on_line=on_line, timeout=timeout)

    def _wrap():
        ok, code = runner.run()
        if on_done:
            on_done(ok, code)

    t = threading.Thread(target=_wrap, daemon=True, name=f"sni-action-{action}")
    t.start()
    return runner
