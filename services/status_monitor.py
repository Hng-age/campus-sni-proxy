"""Periodic read-only status collection (no Qt, callable from any thread)."""

import os
import re
import time

from sni_proxy import config

from . import cert_service, process_manager
from .util import fmt_age, is_admin, run_hidden

LOG_FILE = config.LOG_FILE
ERROR_LINE_RE = re.compile(r"\[(ERROR|WARNING)\]")


def _log_tail(path, max_bytes=65536, max_lines=400):
    """Tail a text file without loading it whole."""
    if not os.path.exists(path):
        return []
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                f.readline()  # drop the partial line
            data = f.read()
        text = data.decode("utf-8", errors="replace")
        lines = [ln for ln in text.splitlines() if ln.strip()]
        return lines[-max_lines:]
    except Exception:
        return []


def _parse_log_ts(line):
    # "2026-11-18 20:11:22 [ERROR] ..."
    try:
        return line[:19].strip()
    except Exception:
        return ""


def _log_highlights():
    """(last_run_ts, last_error_ts, last_error_line) from the log tail."""
    tail = _log_tail(LOG_FILE)
    last_run = ""
    last_err = ""
    last_err_line = ""
    banner = re.compile(r"MITM SNI Proxy v")
    for line in tail:
        if banner.search(line):
            last_run = _parse_log_ts(line)
        if "[ERROR]" in line:
            last_err = _parse_log_ts(line)
            last_err_line = line
    return last_run, last_err, last_err_line


def _proxy_reg_state():
    """HKCU system proxy settings via winreg (read-only)."""
    state = {"enabled": False, "server": "", "override": "", "autoconfig": ""}
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
        try:
            def get(name, default=""):
                try:
                    v, _ = winreg.QueryValueEx(key, name)
                    return v
                except OSError:
                    return default
            state["enabled"] = bool(get("ProxyEnable", 0))
            state["server"] = str(get("ProxyServer", ""))
            state["override"] = str(get("ProxyOverride", ""))
            state["autoconfig"] = str(get("AutoConfigURL", ""))
        finally:
            winreg.CloseKey(key)
    except Exception:
        pass
    return state


# certutil store scans are ~100x costlier than a file stat; cache briefly
_cert_cache = {"key": None, "ts": 0.0, "value": None}
_CERT_CACHE_TTL = 10.0


def _cached_cert_state():
    key = (config.CA_CERT, os.path.getmtime(config.CA_CERT)
           if os.path.exists(config.CA_CERT) else -1)
    now = time.time()
    if (_cert_cache["key"] == key
            and now - _cert_cache["ts"] < _CERT_CACHE_TTL):
        return _cert_cache["value"]
    summ = cert_service.read_cert_summary()
    value = {
        "exists": summ.exists,
        "subject_cn": summ.subject_cn,
        "issuer_cn": summ.issuer_cn,
        "not_after": summ.not_after,
        "not_before": summ.not_before,
        "sha256": summ.sha256,
        "sha1": summ.sha1,
        "days_left": summ.days_left(),
        "expired": summ.is_expired(),
        "installed_machine": None,
        "installed_user": None,
        "wildcard": cert_service.wildcard_ready(),
    }
    if summ.exists and summ.sha1:
        value["installed_machine"] = cert_service.ca_installed(
            summ.sha1, user_store=False)
        value["installed_user"] = cert_service.ca_installed(
            summ.sha1, user_store=True)
    _cert_cache.update(key=key, ts=now, value=value)
    return value


def collect_snapshot():
    """One consistent read-only snapshot of everything the GUI shows."""
    snap = {}
    snap["ts"] = time.time()

    listener_pid = process_manager.find_listener_pid()
    ident = process_manager.proxy_identity(listener_pid)
    snap["listener_pid"] = listener_pid
    snap["proc_name"] = ident["proc_name"]
    snap["identity"] = ident["identity"]
    snap["running"] = ident["running"]
    snap["start_ts"] = ident["start_ts"]
    snap["uptime"] = (time.time() - ident["start_ts"]
                      if ident["running"] and ident["start_ts"] else None)
    snap["uptime_str"] = fmt_age(snap["uptime"])
    snap["listen_addr"] = f"{config.LISTEN_HOST}:{config.LISTEN_PORT}"

    snap["pid_file_pid"] = process_manager.pid_file_pid()

    snap["proxy"] = _proxy_reg_state()
    snap["proxy_points_at_us"] = (
        snap["proxy"]["enabled"]
        and config.LISTEN_HOST in snap["proxy"]["server"]
        and str(config.LISTEN_PORT) in snap["proxy"]["server"])
    snap["backup_exists"] = os.path.exists(
        os.path.join(config.BASE_DIR, "state", "proxy_state.json"))
    snap["watchdog_flag"] = os.path.exists(
        os.path.join(config.BASE_DIR, "state", "proxy_active.flag"))

    snap["cert"] = _cached_cert_state()
    snap["admin"] = is_admin()

    last_run, last_err, last_err_line = _log_highlights()
    snap["log_last_run"] = last_run
    snap["log_last_error"] = last_err
    snap["log_last_error_line"] = last_err_line
    snap["log_size"] = (os.path.getsize(LOG_FILE)
                        if os.path.exists(LOG_FILE) else 0)

    snap["ok"] = bool(snap["running"] and snap["proxy"]["enabled"]
                     and snap["proxy_points_at_us"])
    return snap
