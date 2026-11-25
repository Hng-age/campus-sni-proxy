"""TUN/VPN virtual NIC proxy service backed by Mihomo (Clash Meta) core.

Designed for sharing-client scenarios (e.g. connecting to a LAN gost/SOCKS5/HTTP
proxy with IP, port, username and password) so all Windows apps and UDP/TCP
traffic route cleanly through the virtual TUN adapter with Rule/Global switching.
"""

import base64
import copy
import ipaddress
import json
import os
import shutil
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

from sni_proxy import config

from .util import BASE_DIR, NO_WINDOW, run_hidden

_lock = threading.Lock()

TUN_CONFIG_FILE = os.path.join(BASE_DIR, "tun_config.json")
TUN_YAML_FILE = os.path.join(BASE_DIR, "state", "tun_mihomo.yaml")
TUN_STATE_DIR = os.path.join(BASE_DIR, "state", "tun")
TUN_PID_FILE = os.path.join(BASE_DIR, "state", "tun.pid")
TUN_ACTIVE_FLAG = os.path.join(BASE_DIR, "state", "tun_active.flag")
TUN_LOG_FILE = os.path.join(config.LOG_DIR, "tun.log")
TUN_DEVICE_NAME = "SNI-Proxy-TUN"

RULE_TYPES = (
    "DOMAIN-SUFFIX",
    "DOMAIN",
    "DOMAIN-KEYWORD",
    "IP-CIDR",
    "DST-PORT",
    "PROCESS-NAME",
)
RULE_POLICIES = ("PROXY", "DIRECT", "REJECT")

RULE_PRESETS = {
    "campus_share_all": {
        "label": "校园共享全接管（内网/校园直连，其余全部走代理）",
        "bypass_lan": True,
        "final_policy": "PROXY",
        "rules": [
            {"enabled": True, "type": "DOMAIN-SUFFIX", "value": "edu.cn",
             "policy": "DIRECT", "comment": "高校内网/教务系统直连"},
            {"enabled": True, "type": "DOMAIN-SUFFIX", "value": "local",
             "policy": "DIRECT", "comment": "局域网本地域名直连"},
            {"enabled": True, "type": "PROCESS-NAME", "value": "gost.exe",
             "policy": "DIRECT", "comment": "防止本地服务端代理回环"},
        ],
    },
    "whitelist_proxy": {
        "label": "仅命中规则走代理（白名单分流，其余直连）",
        "bypass_lan": True,
        "final_policy": "DIRECT",
        "rules": [
            {"enabled": True, "type": "DOMAIN-SUFFIX", "value": "douyin.com",
             "policy": "PROXY", "comment": "抖音"},
            {"enabled": True, "type": "DOMAIN-SUFFIX", "value": "bilibili.com",
             "policy": "PROXY", "comment": "哔哩哔哩"},
            {"enabled": True, "type": "PROCESS-NAME", "value": "Telegram.exe",
             "policy": "PROXY", "comment": "Telegram 客户端"},
        ],
    },
    "apps_only": {
        "label": "仅指定桌面应用走共享代理（其余直连）",
        "bypass_lan": True,
        "final_policy": "DIRECT",
        "rules": [
            {"enabled": True, "type": "PROCESS-NAME", "value": "WeChat.exe",
             "policy": "PROXY", "comment": "微信桌面端"},
            {"enabled": True, "type": "PROCESS-NAME", "value": "QQ.exe",
             "policy": "PROXY", "comment": "QQ 桌面端"},
            {"enabled": True, "type": "PROCESS-NAME", "value": "Douyin.exe",
             "policy": "PROXY", "comment": "抖音桌面端"},
            {"enabled": True, "type": "PROCESS-NAME", "value": "Telegram.exe",
             "policy": "PROXY", "comment": "Telegram"},
        ],
    },
}

DEFAULT_TUN_CONFIG = {
    "version": "1.0",
    "active_profile_id": "",
    "profiles": [],
    "server": "",
    "port": 18081,
    "protocol": "socks5",       # socks5 | http
    "username": "",
    "password": "",
    "mode": "rule",             # rule | global
    "udp": True,
    "stack": "gvisor",          # gvisor | system | mixed
    "fake_ip": True,
    "dns_servers": ["223.5.5.5", "119.29.29.29"],
    "bypass_lan": True,
    "also_set_sys_proxy": True,
    "mixed_port": 17897,
    "api_port": 19090,
    "device_name": TUN_DEVICE_NAME,
    "final_policy": "PROXY",    # PROXY | DIRECT
    "rules": copy.deepcopy(RULE_PRESETS["campus_share_all"]["rules"]),
}


# ------------------------------------------------------------------ Discovery

def _clash_verge_candidates():
    cands = [
        r"D:\Clash Verge\verge-mihomo.exe",
        r"C:\Program Files\Clash Verge\verge-mihomo.exe",
        r"C:\Program Files (x86)\Clash Verge\verge-mihomo.exe",
    ]
    if os.name == "nt":
        try:
            import winreg
            roots = (
                (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
                (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
                (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            )
            for hive, sub in roots:
                try:
                    with winreg.OpenKey(hive, sub) as k:
                        i = 0
                        while True:
                            try:
                                name = winreg.EnumKey(k, i)
                                i += 1
                            except OSError:
                                break
                            try:
                                with winreg.OpenKey(k, name) as item:
                                    dn, _ = winreg.QueryValueEx(item, "DisplayName")
                                    if "clash" in str(dn).lower() and "verge" in str(dn).lower():
                                        loc, _ = winreg.QueryValueEx(item, "InstallLocation")
                                        loc = str(loc).strip('"')
                                        if loc:
                                            cands.append(os.path.join(loc, "verge-mihomo.exe"))
                            except OSError:
                                continue
                except OSError:
                    continue
        except Exception:
            pass
    return cands


def find_mihomo_exe():
    """Locate the bundled or installed Mihomo TUN core executable."""
    cands = [
        os.path.join(BASE_DIR, "bin", "mihomo.exe"),
        os.path.join(BASE_DIR, "bin", "verge-mihomo.exe"),
        os.path.join(BASE_DIR, "mihomo.exe"),
    ]
    if hasattr(sys, "_MEIPASS"):
        cands.extend([
            os.path.join(sys._MEIPASS, "bin", "mihomo.exe"),
            os.path.join(sys._MEIPASS, "mihomo.exe"),
        ])
    cands.extend(_clash_verge_candidates())
    for c in cands:
        if c and os.path.isfile(c):
            return os.path.abspath(c)
    for name in ("mihomo", "verge-mihomo"):
        found = shutil.which(name)
        if found:
            return found
    return None


# --------------------------------------------------------------- Config Store

def _normalize_profile(p, fallback_id=None):
    import uuid
    srv = str((p or {}).get("server") or "").strip()
    try:
        prt = max(1, min(65535, int((p or {}).get("port", 18081))))
    except (TypeError, ValueError):
        prt = 18081
    proto = str((p or {}).get("protocol") or "socks5").strip().lower()
    if proto not in ("socks5", "http"):
        proto = "socks5"
    pid = str((p or {}).get("id") or fallback_id or f"p_{uuid.uuid4().hex[:8]}").strip()
    name = str((p or {}).get("name") or f"{srv}:{prt}" or "未命名线路").strip()
    return {
        "id": pid,
        "name": name,
        "protocol": proto,
        "server": srv,
        "port": prt,
        "username": str((p or {}).get("username") or ""),
        "password": str((p or {}).get("password") or ""),
        "udp": bool((p or {}).get("udp", True)),
        "last_status": str((p or {}).get("last_status") or ""),
        "last_latency_ms": (p or {}).get("last_latency_ms"),
    }


def _sync_active_profile(cfg):
    profiles = cfg.get("profiles") or []
    active_id = str(cfg.get("active_profile_id") or "")
    chosen = next((p for p in profiles if p["id"] == active_id), None)
    if chosen is None and profiles:
        chosen = profiles[0]
        cfg["active_profile_id"] = chosen["id"]
    if chosen:
        cfg["server"] = chosen["server"]
        cfg["port"] = chosen["port"]
        cfg["protocol"] = chosen["protocol"]
        cfg["username"] = chosen["username"]
        cfg["password"] = chosen["password"]
        cfg["udp"] = chosen["udp"]
    return cfg


def _normalize_config(raw):
    cfg = copy.deepcopy(DEFAULT_TUN_CONFIG)
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k in cfg:
                cfg[k] = v

    cfg["server"] = str(cfg.get("server") or "").strip()
    try:
        cfg["port"] = max(1, min(65535, int(cfg.get("port", 18081))))
    except (TypeError, ValueError):
        cfg["port"] = 18081

    proto = str(cfg.get("protocol") or "socks5").strip().lower()
    cfg["protocol"] = proto if proto in ("socks5", "http") else "socks5"
    cfg["username"] = str(cfg.get("username") or "")
    cfg["password"] = str(cfg.get("password") or "")

    # Normalize saved proxy profiles; migrate legacy single-server config automatically
    clean_profiles = []
    seen_ids = set()
    for p in cfg.get("profiles") or []:
        if not isinstance(p, dict):
            continue
        np = _normalize_profile(p)
        if not np["server"]:
            continue
        if np["id"] in seen_ids:
            np = _normalize_profile(p, fallback_id=None)
        seen_ids.add(np["id"])
        clean_profiles.append(np)

    if not clean_profiles and cfg["server"]:
        migrated = _normalize_profile({
            "id": "default",
            "name": f"默认线路 ({cfg['server']})",
            "protocol": cfg["protocol"],
            "server": cfg["server"],
            "port": cfg["port"],
            "username": cfg["username"],
            "password": cfg["password"],
            "udp": cfg["udp"],
        })
        clean_profiles.append(migrated)
        cfg["active_profile_id"] = migrated["id"]

    cfg["profiles"] = clean_profiles
    cfg["active_profile_id"] = str(cfg.get("active_profile_id") or "")
    if clean_profiles:
        _sync_active_profile(cfg)

    mode = str(cfg.get("mode") or "rule").strip().lower()
    cfg["mode"] = mode if mode in ("rule", "global") else "rule"

    stack = str(cfg.get("stack") or "gvisor").strip().lower()
    cfg["stack"] = stack if stack in ("gvisor", "system", "mixed") else "gvisor"

    cfg["udp"] = bool(cfg.get("udp", True))
    cfg["fake_ip"] = bool(cfg.get("fake_ip", True))
    cfg["bypass_lan"] = bool(cfg.get("bypass_lan", True))
    cfg["also_set_sys_proxy"] = bool(cfg.get("also_set_sys_proxy", True))

    try:
        cfg["mixed_port"] = max(1024, min(65535, int(cfg.get("mixed_port", 17897))))
    except (TypeError, ValueError):
        cfg["mixed_port"] = 17897
    try:
        cfg["api_port"] = max(1024, min(65535, int(cfg.get("api_port", 19090))))
    except (TypeError, ValueError):
        cfg["api_port"] = 19090

    fp = str(cfg.get("final_policy") or "PROXY").strip().upper()
    cfg["final_policy"] = fp if fp in ("PROXY", "DIRECT") else "PROXY"

    clean_rules = []
    for r in cfg.get("rules") or []:
        if not isinstance(r, dict):
            continue
        rtype = str(r.get("type") or "").strip().upper()
        val = str(r.get("value") or "").strip()
        pol = str(r.get("policy") or "PROXY").strip().upper()
        if rtype not in RULE_TYPES or not val:
            continue
        if pol not in RULE_POLICIES:
            pol = "PROXY"
        clean_rules.append({
            "enabled": bool(r.get("enabled", True)),
            "type": rtype,
            "value": val,
            "policy": pol,
            "comment": str(r.get("comment") or "").strip(),
        })
    cfg["rules"] = clean_rules
    return cfg


def load_tun_config():
    """Load tun_config.json (creating default on first read if absent)."""
    with _lock:
        if not os.path.exists(TUN_CONFIG_FILE):
            cfg = copy.deepcopy(DEFAULT_TUN_CONFIG)
            try:
                with open(TUN_CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, indent=2, ensure_ascii=False)
            except OSError:
                pass
            return cfg
        try:
            with open(TUN_CONFIG_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            return _normalize_config(raw)
        except Exception:
            return copy.deepcopy(DEFAULT_TUN_CONFIG)


def save_tun_config(cfg):
    """Persist tun_config.json atomically and regenerate Mihomo YAML if valid."""
    clean = _normalize_config(cfg)
    with _lock:
        tmp = TUN_CONFIG_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(clean, f, indent=2, ensure_ascii=False)
        os.replace(tmp, TUN_CONFIG_FILE)
    if clean["server"]:
        try:
            export_mihomo_yaml(clean)
        except ValueError:
            pass
    return clean


def apply_rule_preset(cfg, preset_key):
    """Return a copy of `cfg` with preset rules, bypass_lan and final_policy applied."""
    preset = RULE_PRESETS.get(preset_key)
    if not preset:
        raise ValueError(f"Unknown preset: {preset_key}")
    out = _normalize_config(cfg)
    out["bypass_lan"] = preset["bypass_lan"]
    out["final_policy"] = preset["final_policy"]
    out["rules"] = copy.deepcopy(preset["rules"])
    return out


def upsert_profile(cfg, profile_data, activate=False):
    """Add or update a saved proxy line profile and persist config."""
    out = _normalize_config(cfg)
    pid = str(profile_data.get("id") or "").strip()
    np = _normalize_profile(profile_data, fallback_id=pid or None)
    if not np["server"]:
        raise ValueError("请填写服务器 IP 地址或域名")

    profiles = out.get("profiles") or []
    replaced = False
    for idx, existing in enumerate(profiles):
        if existing["id"] == np["id"]:
            # preserve last test status if server/port/auth unchanged
            if (existing["server"] == np["server"]
                    and existing["port"] == np["port"]
                    and existing["protocol"] == np["protocol"]
                    and existing["username"] == np["username"]
                    and existing["password"] == np["password"]
                    and not np.get("last_status")):
                np["last_status"] = existing.get("last_status", "")
                np["last_latency_ms"] = existing.get("last_latency_ms")
            profiles[idx] = np
            replaced = True
            break
    if not replaced:
        profiles.append(np)
    out["profiles"] = profiles

    if activate or not out.get("active_profile_id") or len(profiles) == 1:
        out["active_profile_id"] = np["id"]
    _sync_active_profile(out)
    return save_tun_config(out), np


def select_profile(cfg, profile_id):
    """Set the active proxy line and hot-reload Mihomo if running."""
    out = _normalize_config(cfg)
    profiles = out.get("profiles") or []
    target = next((p for p in profiles if p["id"] == profile_id), None)
    if not target:
        raise ValueError("未找到指定的代理线路")
    out["active_profile_id"] = target["id"]
    _sync_active_profile(out)
    return save_tun_config(out)


def delete_profile(cfg, profile_id):
    """Remove a saved proxy line profile."""
    out = _normalize_config(cfg)
    profiles = [p for p in (out.get("profiles") or []) if p["id"] != profile_id]
    out["profiles"] = profiles
    if out.get("active_profile_id") == profile_id:
        out["active_profile_id"] = profiles[0]["id"] if profiles else ""
        if not profiles:
            out["server"] = ""
            out["username"] = ""
            out["password"] = ""
    _sync_active_profile(out)
    return save_tun_config(out)


def update_profile_test_result(cfg, profile_id, res):
    """Store latest connectivity test summary onto a saved profile."""
    out = _normalize_config(cfg)
    for p in out.get("profiles") or []:
        if p["id"] == profile_id:
            if res and res.get("ok"):
                ms = res.get("latency_ms")
                p["last_status"] = f"✅ {ms} ms" if ms is not None else "✅ 可用"
                p["last_latency_ms"] = ms
            else:
                msg = (res or {}).get("message") or "测试失败"
                p["last_status"] = f"❌ {msg[:24]}"
                p["last_latency_ms"] = None
            break
    return save_tun_config(out)


# --------------------------------------------------------------- YAML Builder

def _yaml_str(s):
    """Safely quote any scalar string using JSON double-quoting (valid YAML 1.2)."""
    return json.dumps(str(s), ensure_ascii=False)


def _is_ipv4(addr):
    try:
        ipaddress.IPv4Address(addr)
        return True
    except ValueError:
        return False


def generate_mihomo_yaml(cfg):
    """Build complete Mihomo TUN YAML configuration from `cfg`."""
    c = _normalize_config(cfg)
    server = c["server"]
    if not server:
        raise ValueError("请先填写上游代理服务器 IP 地址或主机名")

    port = c["port"]
    proto = c["protocol"]
    dns_mode = "fake-ip" if c["fake_ip"] else "redir-host"
    dns_list = [d for d in (c.get("dns_servers") or ["223.5.5.5", "119.29.29.29"]) if str(d).strip()]
    if not dns_list:
        dns_list = ["223.5.5.5", "119.29.29.29"]

    exclude_cidrs = ["127.0.0.0/8"]
    if c["bypass_lan"]:
        exclude_cidrs.extend(["192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12"])
    server_is_ip = _is_ipv4(server)
    if server_is_ip:
        srv_cidr = f"{server}/32"
        if srv_cidr not in exclude_cidrs:
            exclude_cidrs.append(srv_cidr)

    lines = [
        f"mixed-port: {c['mixed_port']}",
        f"mode: {c['mode']}",
        "log-level: info",
        "allow-lan: false",
        f"external-controller: 127.0.0.1:{c['api_port']}",
        "",
        "dns:",
        "  enable: true",
        "  ipv6: false",
        f"  enhanced-mode: {dns_mode}",
        "  fake-ip-range: 198.18.0.1/16",
        "  nameserver:",
    ]
    for ns in dns_list:
        lines.append(f"    - {_yaml_str(ns)}")

    lines.extend([
        "",
        "tun:",
        "  enable: true",
        f"  stack: {c['stack']}",
        f"  device: {_yaml_str(c['device_name'] or TUN_DEVICE_NAME)}",
        "  auto-route: true",
        "  auto-detect-interface: true",
        "  strict-route: true",
        "  dns-hijack:",
        '    - "any:53"',
        "  route-exclude-address:",
    ])
    for cidr in exclude_cidrs:
        lines.append(f"    - {_yaml_str(cidr)}")

    lines.extend([
        "",
        "proxies:",
        '  - name: "LAN-PROXY"',
        f"    type: {proto}",
        f"    server: {_yaml_str(server)}",
        f"    port: {port}",
    ])
    if c["username"]:
        lines.append(f"    username: {_yaml_str(c['username'])}")
    if c["password"]:
        lines.append(f"    password: {_yaml_str(c['password'])}")
    if proto == "socks5":
        lines.append(f"    udp: {'true' if c['udp'] else 'false'}")

    lines.extend([
        "",
        "proxy-groups:",
        '  - name: "PROXY"',
        "    type: select",
        "    proxies:",
        '      - "LAN-PROXY"',
        '  - name: "GLOBAL"',
        "    type: select",
        "    proxies:",
        '      - "LAN-PROXY"',
        '      - "DIRECT"',
        "",
        "rules:",
    ])

    rule_lines = []
    if server_is_ip:
        rule_lines.append(f"IP-CIDR,{server}/32,DIRECT,no-resolve")
    if c["bypass_lan"]:
        rule_lines.extend([
            "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
            "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
            "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
            "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
        ])

    for r in c["rules"]:
        if not r.get("enabled", True):
            continue
        rtype = r["type"]
        val = r["value"]
        pol = r["policy"]
        if rtype in ("IP-CIDR", "IP-CIDR6") and ",no-resolve" not in val:
            rule_lines.append(f"{rtype},{val},{pol},no-resolve")
        else:
            rule_lines.append(f"{rtype},{val},{pol}")

    rule_lines.append(f"MATCH,{c['final_policy']}")
    for rl in rule_lines:
        lines.append(f"  - {_yaml_str(rl)}")

    return "\n".join(lines) + "\n"


def export_mihomo_yaml(cfg=None):
    """Write state/tun_mihomo.yaml and return its path."""
    c = _normalize_config(cfg if cfg is not None else load_tun_config())
    content = generate_mihomo_yaml(c)
    os.makedirs(os.path.dirname(TUN_YAML_FILE), exist_ok=True)
    os.makedirs(TUN_STATE_DIR, exist_ok=True)
    tmp = TUN_YAML_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, TUN_YAML_FILE)
    return TUN_YAML_FILE


def validate_mihomo_yaml(yaml_path=None):
    """Validate YAML with `mihomo.exe -t`. Returns (ok, output)."""
    exe = find_mihomo_exe()
    if not exe:
        return False, "未找到 Mihomo 内核 (bin/mihomo.exe)"
    path = yaml_path or TUN_YAML_FILE
    os.makedirs(TUN_STATE_DIR, exist_ok=True)
    code, out, err = run_hidden([exe, "-d", TUN_STATE_DIR, "-f", path, "-t"], timeout=15)
    msg = (out + "\n" + err).strip()
    return code == 0, msg


# ----------------------------------------------------------- Connectivity Test

def _recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("连接被对端关闭")
        buf.extend(chunk)
    return bytes(buf)


def test_upstream_proxy(cfg, timeout=5.0, probe_target=("223.5.5.5", 80)):
    """Verify TCP reachability, username/password auth and upstream forwarding."""
    c = _normalize_config(cfg)
    server = c["server"]
    port = c["port"]
    proto = c["protocol"]
    user = c["username"]
    password = c["password"]

    if not server:
        return {"ok": False, "auth_ok": False, "latency_ms": None,
                "message": "请填写服务器 IP 地址", "detail": ""}

    t0 = time.perf_counter()
    try:
        sock = socket.create_connection((server, port), timeout=timeout)
        sock.settimeout(timeout)
    except OSError as e:
        return {
            "ok": False, "auth_ok": False, "latency_ms": None,
            "message": f"无法连接 {server}:{port}（端口不可达或未启动）",
            "detail": f"请检查：1) 服务端是否已开机且代理运行中；2) 是否与服务端同处局域网；3) 服务端防火墙是否放行该端口。\n底层错误：{e}",
        }

    latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)

    try:
        if proto == "socks5":
            has_creds = bool(user or password)
            greeting = b"\x05\x02\x00\x02" if has_creds else b"\x05\x01\x00"
            sock.sendall(greeting)
            ver, method = _recv_exact(sock, 2)
            if ver != 5:
                return {"ok": False, "auth_ok": False, "latency_ms": latency_ms,
                        "message": f"端口 {port} 返回非 SOCKS5 响应（是不是填成了 HTTP 端口？）",
                        "detail": f"SOCKS version byte={ver}"}
            if method == 0xFF:
                return {"ok": False, "auth_ok": False, "latency_ms": latency_ms,
                        "message": "服务端要求账号密码认证，请填写账号和密码",
                        "detail": "SOCKS5 method negotiation returned 0xFF"}
            if method == 0x02:
                u_bytes = user.encode("utf-8")[:255]
                p_bytes = password.encode("utf-8")[:255]
                auth_pkt = bytes([1, len(u_bytes)]) + u_bytes + bytes([len(p_bytes)]) + p_bytes
                sock.sendall(auth_pkt)
                aver, status = _recv_exact(sock, 2)
                if aver != 1 or status != 0:
                    return {"ok": False, "auth_ok": False, "latency_ms": latency_ms,
                            "message": "SOCKS5 账号或密码错误（认证被拒绝）",
                            "detail": f"RFC 1929 status={status}"}

            # Test forwarding via SOCKS5 CONNECT to probe_target
            tgt_ip, tgt_port = probe_target
            ip_bytes = socket.inet_aton(tgt_ip)
            req = b"\x05\x01\x00\x01" + ip_bytes + tgt_port.to_bytes(2, "big")
            sock.sendall(req)
            rep = _recv_exact(sock, 4)
            if rep[1] != 0:
                return {"ok": True, "auth_ok": True, "latency_ms": latency_ms,
                        "message": f"认证通过 ({latency_ms} ms)，但目标转发测试返回错误码 {rep[1]}",
                        "detail": "代理本身认证正常，请确认服务端自身可访问外网。"}
            return {"ok": True, "auth_ok": True, "latency_ms": latency_ms,
                    "message": f"测试通过：SOCKS5 连接与账号认证正常（握手 {latency_ms} ms）",
                    "detail": f"已验证 {server}:{port} 可用并成功通过 {tgt_ip}:{tgt_port} 转发测试。"}

        # HTTP proxy test via CONNECT
        tgt_ip, tgt_port = probe_target
        headers = [
            f"CONNECT {tgt_ip}:{tgt_port} HTTP/1.1",
            f"Host: {tgt_ip}:{tgt_port}",
        ]
        if user or password:
            token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
            headers.append(f"Proxy-Authorization: Basic {token}")
        req_raw = ("\r\n".join(headers) + "\r\n\r\n").encode("ascii")
        sock.sendall(req_raw)
        resp = b""
        while b"\r\n\r\n" not in resp and len(resp) < 4096:
            chunk = sock.recv(1024)
            if not chunk:
                break
            resp += chunk
        first_line = resp.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")
        if " 407 " in first_line:
            return {"ok": False, "auth_ok": False, "latency_ms": latency_ms,
                    "message": "HTTP 407：代理账号或密码错误",
                    "detail": first_line}
        if " 200 " in first_line:
            return {"ok": True, "auth_ok": True, "latency_ms": latency_ms,
                    "message": f"测试通过：HTTP 代理与账号认证正常（延迟 {latency_ms} ms）",
                    "detail": first_line}
        return {"ok": False, "auth_ok": False, "latency_ms": latency_ms,
                "message": f"代理返回异常状态：{first_line or '无响应'}",
                "detail": resp.decode("latin-1", errors="replace")[:300]}
    except Exception as e:
        return {"ok": False, "auth_ok": False, "latency_ms": latency_ms,
                "message": f"协议探测失败：{e}", "detail": str(e)}
    finally:
        try:
            sock.close()
        except OSError:
            pass


# ----------------------------------------------------------- Live Runtime API

def _api_request(api_port, path, method="GET", payload=None, timeout=0.6):
    url = f"http://127.0.0.1:{api_port}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    # Bypass Windows system proxy for local controller API calls
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return json.loads(body) if body.strip() else {}


def _pid_alive(pid):
    if not pid:
        return False
    if os.name == "nt":
        try:
            import ctypes
            SYNCHRONIZE = 0x00100000
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = ctypes.windll.kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, int(pid))
            if not h:
                return False
            try:
                WAIT_TIMEOUT = 0x00000102
                res = ctypes.windll.kernel32.WaitForSingleObject(h, 0)
                return res == WAIT_TIMEOUT
            finally:
                ctypes.windll.kernel32.CloseHandle(h)
        except Exception:
            return False
    return False


def read_tun_pid():
    try:
        with open(TUN_PID_FILE, "r", encoding="ascii") as f:
            return int(f.read().strip())
    except Exception:
        return None


def get_tun_status():
    """Poll runtime state of Mihomo TUN core without blocking GUI."""
    cfg = load_tun_config()
    exe = find_mihomo_exe()
    api_port = cfg["api_port"]
    pid = read_tun_pid()
    alive = _pid_alive(pid) if pid else False

    out = {
        "mihomo_found": bool(exe),
        "mihomo_path": exe or "",
        "running": False,
        "pid": pid if alive else None,
        "mode": cfg["mode"],
        "tun_enabled": False,
        "device_name": cfg.get("device_name", TUN_DEVICE_NAME),
        "connections_count": 0,
        "upload_total": 0,
        "download_total": 0,
        "connections": [],
        "api_port": api_port,
        "mixed_port": cfg["mixed_port"],
    }

    try:
        confs = _api_request(api_port, "/configs", timeout=0.5)
        out["running"] = True
        out["mode"] = str(confs.get("mode", cfg["mode"])).lower()
        tun_info = confs.get("tun") or {}
        out["tun_enabled"] = bool(tun_info.get("enable", True))
        if tun_info.get("device"):
            out["device_name"] = tun_info["device"]
    except Exception:
        out["running"] = False

    if out["running"]:
        try:
            conns = _api_request(api_port, "/connections", timeout=0.6)
            items = conns.get("connections") or []
            out["connections_count"] = len(items)
            out["upload_total"] = int(conns.get("uploadTotal") or 0)
            out["download_total"] = int(conns.get("downloadTotal") or 0)
            out["connections"] = items[:120]
        except Exception:
            pass

    return out


def switch_live_mode(mode):
    """Persist mode ('rule' | 'global') and hot-patch running Mihomo API if active."""
    mode = str(mode).strip().lower()
    if mode not in ("rule", "global"):
        raise ValueError("Mode must be 'rule' or 'global'")
    cfg = load_tun_config()
    cfg["mode"] = mode
    save_tun_config(cfg)

    api_port = cfg["api_port"]
    try:
        _api_request(api_port, "/configs", method="PATCH", payload={"mode": mode}, timeout=1.0)
        if mode == "global":
            try:
                _api_request(api_port, "/proxies/GLOBAL", method="PUT",
                             payload={"name": "LAN-PROXY"}, timeout=1.0)
            except Exception:
                pass
        return True, f"已实时切换为{'全局代理' if mode == 'global' else '规则代理'}模式"
    except Exception:
        return True, f"已保存为{'全局代理' if mode == 'global' else '规则代理'}模式（将在启动 TUN 后生效）"


def reload_live_config(cfg=None):
    """Save config, validate YAML, and hot-reload running Mihomo if active."""
    clean = save_tun_config(cfg if cfg is not None else load_tun_config())
    if not clean["server"]:
        return False, "请先填写上游代理服务器 IP 地址"
    yaml_path = export_mihomo_yaml(clean)
    ok, msg = validate_mihomo_yaml(yaml_path)
    if not ok:
        return False, f"配置校验失败：\n{msg}"

    api_port = clean["api_port"]
    try:
        _api_request(api_port, "/configs?force=true", method="PUT",
                     payload={"path": yaml_path}, timeout=2.0)
        return True, "配置已保存并热重载至运行中的 TUN 内核！"
    except Exception:
        return True, "配置与分流规则已保存，点击「启动 TUN」即可生效。"


def close_all_connections():
    """Close all active connections in Mihomo via REST API."""
    cfg = load_tun_config()
    try:
        _api_request(cfg["api_port"], "/connections", method="DELETE", timeout=1.0)
        return True
    except Exception:
        return False


def get_tun_logs_tail(max_lines=120):
    if not os.path.exists(TUN_LOG_FILE):
        return ""
    try:
        with open(TUN_LOG_FILE, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 32768))
            text = f.read().decode("utf-8", errors="replace")
        return "\n".join(text.splitlines()[-max_lines:])
    except Exception:
        return ""


def fmt_bytes(n):
    n = float(max(0, n or 0))
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024.0
    return "0 B"
