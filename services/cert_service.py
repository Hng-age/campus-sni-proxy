"""Certificate reading, trust-store checks and private-key hygiene reports.

X.509 fields are parsed with a tiny DER walker so no external crypto tool is
required for display; openssl is only needed when generating certificates.
"""

import base64
import datetime
import hashlib
import os
import re

from sni_proxy import config

from .util import run_hidden

_CN_OID = (2, 5, 4, 3)               # 2.5.4.3 commonName (decoded arcs)
_BOGUS_ACE = ("everyone", "users", "authenticated users", "guests",
              "anonymous", "everyone:")


class CertSummary:
    __slots__ = ("path", "subject_cn", "issuer_cn", "not_before",
                 "not_after", "sha1", "sha256", "exists")

    def days_left(self):
        if not self.not_after:
            return None
        return (self.not_after - datetime.datetime.now()).days

    def is_expired(self):
        dl = self.days_left()
        return dl is not None and dl < 0


# ---------------------------------------------------------------- DER walker

def _read_tlv(data, off):
    """Return (tag, value_bytes, next_offset) or None."""
    if off >= len(data):
        return None
    tag = data[off]
    off += 1
    if off >= len(data):
        return None
    first = data[off]
    off += 1
    if first & 0x80:
        n = first & 0x7F
        if n == 0 or off + n > len(data):
            return None
        length = int.from_bytes(data[off:off + n], "big")
        off += n
    else:
        length = first
    if off + length > len(data):
        return None
    return tag, data[off:off + length], off + length


def _children(value):
    out, off = [], 0
    while off < len(value):
        tlv = _read_tlv(value, off)
        if not tlv:
            break
        tag, val, off = tlv
        out.append((tag, val))
    return out


def _oid_bytes_to_tuple(raw):
    """Small helper: DER OID content bytes -> tuple of integers."""
    if not raw:
        return ()
    parts = [raw[0] // 40, raw[0] % 40]
    for b in raw[1:]:
        if b < 128:
            parts.append(b)
        else:
            # multi-byte arcs are not present in the OIDs we need; keep robust
            parts[-1] = parts[-1] * 128 + (b & 0x7F)
    return tuple(parts)


def _rdn_cn(sequence_value):
    """Pull the CN values from an RDNSequence."""
    names = []
    for _set_tag, set_val in _children(sequence_value):
        for _atv_tag, atv_val in _children(set_val):
            kids = _children(atv_val)
            if len(kids) < 2:
                continue
            oid_raw, val_raw = kids[0][1], kids[1][1]
            if _oid_bytes_to_tuple(oid_raw) == _CN_OID:
                try:
                    names.append(val_raw.decode("utf-8", errors="replace"))
                except Exception:
                    pass
    return ", ".join(n for n in names if n) or None


def _parse_time(tag, raw):
    try:
        text = raw.decode("ascii").strip()
    except Exception:
        return None
    if tag == 23:      # UTCTime YYMMDDHHMMSSZ
        if len(text) < 12:
            return None
        year = int(text[:2])
        year += 2000 if year < 50 else 1900
        rest = text[2:]
    elif tag == 24:    # GeneralizedTime YYYYMMDDHHMMSSZ
        if len(text) < 14:
            return None
        year = int(text[:4])
        rest = text[4:]
    else:
        return None
    try:
        return datetime.datetime(
            year, int(rest[0:2]), int(rest[2:4]),
            int(rest[4:6]), int(rest[6:8]), int(rest[8:10]))
    except ValueError:
        return None


def read_cert_summary(path=None):
    """Parse the first certificate of a PEM file without external tools."""
    path = path or config.CA_CERT
    s = CertSummary()
    s.path = path
    s.exists = os.path.exists(path)
    s.subject_cn = s.issuer_cn = s.not_before = s.not_after = None
    s.sha1 = s.sha256 = None
    if not s.exists:
        return s
    try:
        with open(path, "r", encoding="ascii", errors="ignore") as f:
            text = f.read()
        begin = text.index("-----BEGIN CERTIFICATE-----")
        end = text.index("-----END CERTIFICATE-----")
        body = text[begin + len("-----BEGIN CERTIFICATE-----"):end]
        der = base64.b64decode("".join(body.split()), validate=False)
        s.sha1 = hashlib.sha1(der).hexdigest().upper()
        s.sha256 = hashlib.sha256(der).hexdigest().upper()

        root = _read_tlv(der, 0)
        if not root:
            return s
        cert_val = root[1]
        top = _children(cert_val)
        if not top:
            return s
        tbs = top[0][1]
        fields = _children(tbs)
        idx = 0
        if fields and fields[0][0] == 0xA0:       # [0] EXPLICIT version
            idx = 1
        # idx: serial, sigalg, issuer, validity, subject, ...
        if len(fields) < idx + 5:
            return s
        s.issuer_cn = _rdn_cn(fields[idx + 2][1])
        for tag, val in _children(fields[idx + 3][1]):
            if s.not_before is None:
                s.not_before = _parse_time(tag, val)
            else:
                s.not_after = _parse_time(tag, val)
        s.subject_cn = _rdn_cn(fields[idx + 4][1])
    except Exception:
        pass
    return s


# ------------------------------------------------------------- trust stores

# certutil 在中文系统输出“证书哈希(sha1): ...”，英文系统输出
# “cert hash(sha1): ...”，只匹配 ASCII 的 (sha1): 部分才能兼容两种语言
_hash_re = re.compile(r"\(sha1\):\s*([0-9a-f ]+)", re.I)


def _store_thumbs(user_store=False):
    """Thumbprints installed in the Root store (machine or current user)."""
    cmd = ["certutil", "-user", "-store", "Root"] if user_store \
        else ["certutil", "-store", "Root"]
    code, out, _ = run_hidden(cmd, timeout=20)
    if code != 0:
        return None
    thumbs = set()
    for line in out.splitlines():
        m = _hash_re.search(line)
        if m:
            thumbs.add(m.group(1).replace(" ", "").upper())
    return thumbs


def ca_installed(thumb, user_store=False):
    """None = check failed; True/False = installed or not."""
    thumbs = _store_thumbs(user_store=user_store)
    if thumbs is None:
        return None
    return (thumb or "").upper() in thumbs


def install_report():
    """Machine + user Root store install state for the device CA."""
    summ = read_cert_summary()
    if not summ.exists or not summ.sha1:
        return {"exists": False, "machine": False, "user": False}
    return {"exists": True,
            "machine": ca_installed(summ.sha1, user_store=False),
            "user": ca_installed(summ.sha1, user_store=True)}


# ------------------------------------------------------------ key hygiene

def key_acl_report(path=None):
    """Check a private key file's DACL for over-broad grants."""
    from sni_proxy.config import CA_KEY
    path = path or CA_KEY
    if not os.path.exists(path):
        return {"exists": False, "grants": [], "restricted": None}
    code, out, _ = run_hidden(["icacls", path], timeout=15)
    if code != 0:
        return {"exists": True, "grants": [], "restricted": None}
    grants = []
    for line in out.splitlines():
        line = line.strip()
        if not line or ":" not in line or line.startswith(("Successfully",
                                                            "Failed",
                                                            "处理",
                                                            "已处理")):
            continue
        grants.append(line)
    lowered = " | ".join(grants).lower()
    bad = [ace for ace in _BOGUS_ACE if ace in lowered]
    return {"exists": True, "grants": grants,
            "restricted": (len(bad) == 0) if grants else None}


def wildcard_ready():
    return (os.path.exists(config.WILDCARD_CERT)
            and os.path.exists(config.WILDCARD_KEY))


def export_public_cert(src, dst):
    """Copy a public certificate file (never a key)."""
    if not src.lower().endswith((".crt", ".cer", ".pem")):
        raise ValueError("仅允许导出公开证书文件（.crt/.cer/.pem）")
    if not os.path.exists(src):
        raise FileNotFoundError(src)
    # 目标与源相同时，“wb” 会先截断源文件，导致 CA 证书被清空
    if os.path.normcase(os.path.abspath(src)) == \
            os.path.normcase(os.path.abspath(dst)):
        raise ValueError("导出目标不能与源证书相同")
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        fout.write(fin.read())
    return dst
