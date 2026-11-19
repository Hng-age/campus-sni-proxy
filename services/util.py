"""Shared helpers for the service layer (no Qt imports)."""

import os
import subprocess
import sys

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
    if not os.path.exists(os.path.join(BASE_DIR, "proxy_manager.ps1")):
        _parent_dir = os.path.dirname(BASE_DIR)
        if os.path.exists(os.path.join(_parent_dir, "proxy_manager.ps1")):
            BASE_DIR = _parent_dir
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# windows: do not flash console windows for subprocesses
NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def run_hidden(cmd, timeout=30, decode="utf-8"):
    """Run a command without a console window.

    Returns (exit_code, stdout_text, stderr_text); timeouts return (124, ...).
    """
    try:
        p = subprocess.run(
            cmd, capture_output=True, timeout=timeout, creationflags=NO_WINDOW)
        return (p.returncode,
                p.stdout.decode(decode, errors="replace"),
                p.stderr.decode(decode, errors="replace"))
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except OSError as e:
        return 127, "", str(e)


def is_admin():
    """True when the current process has an elevated token."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def fmt_age(seconds):
    """Format an uptime/duration in a compact human readable form."""
    if seconds is None or seconds < 0:
        return "--"
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        return f"{d}天 {h}小时 {m}分"
    if h:
        return f"{h}小时 {m}分 {s}秒"
    if m:
        return f"{m}分 {s}秒"
    return f"{s}秒"
