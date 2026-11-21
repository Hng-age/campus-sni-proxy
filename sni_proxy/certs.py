"""Per-device CA, wildcard certificate and on-demand site certificates."""

import base64
import ctypes
import datetime
import hashlib
import os
import shutil
import subprocess
import threading
import time

from ctypes import wintypes

try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    HAVE_CRYPTOGRAPHY = True
except ImportError:
    HAVE_CRYPTOGRAPHY = False

from . import config
from .config import NO_WINDOW
from .logsetup import log, log_error, log_warning
from .netutil import wildcard_covers

_cert_lock = threading.Lock()

# cert generation failure tombstones: domain -> timestamp (avoid flash loops)
_cert_fail = {}
_CERT_FAIL_TTL = 60

if os.name == "nt":
    _SE_FILE_OBJECT = 1
    _DACL_SECURITY_INFORMATION = 0x00000004
    _PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
    _SET_ACCESS = 2
    _NO_INHERITANCE = 0
    _TRUSTEE_IS_SID = 0
    _TRUSTEE_IS_UNKNOWN = 0
    _FILE_ALL_ACCESS = 0x1F01FF

    class _TRUSTEE_W(ctypes.Structure):
        _fields_ = [
            ("pMultipleTrustee", ctypes.c_void_p),
            ("MultipleTrusteeOperation", ctypes.c_int),
            ("TrusteeForm", ctypes.c_int),
            ("TrusteeType", ctypes.c_int),
            ("ptstrName", ctypes.c_void_p),
        ]

    class _EXPLICIT_ACCESS_W(ctypes.Structure):
        _fields_ = [
            ("grfAccessPermissions", wintypes.DWORD),
            ("grfAccessMode", ctypes.c_int),
            ("grfInheritance", wintypes.DWORD),
            ("Trustee", _TRUSTEE_W),
        ]

    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _advapi32.ConvertStringSidToSidW.argtypes = [
        wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    _advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
    _advapi32.SetEntriesInAclW.argtypes = [
        wintypes.ULONG, ctypes.POINTER(_EXPLICIT_ACCESS_W),
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    _advapi32.SetEntriesInAclW.restype = wintypes.DWORD
    _advapi32.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    _advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p


def ensure_cert_dir():
    os.makedirs(config.CERT_DIR, exist_ok=True)


def _current_user_sid():
    """Return the current Windows user SID, or None."""
    try:
        raw = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            capture_output=True, timeout=8,
            creationflags=NO_WINDOW).stdout
        out = raw.decode("utf-8", errors="replace")
        for part in out.replace('"', "").split(","):
            part = part.strip()
            if part.startswith("S-1-5-"):
                return part
    except Exception:
        pass
    return None


def _set_restricted_dacl(path, sid):
    """Replace the file DACL, leaving the SACL/integrity label untouched."""
    psids = []
    try:
        for s in (sid, "S-1-5-18", "S-1-5-32-544"):
            p = ctypes.c_void_p()
            if not _advapi32.ConvertStringSidToSidW(s, ctypes.byref(p)):
                raise ctypes.WinError(ctypes.get_last_error())
            psids.append(p)

        entries = (_EXPLICIT_ACCESS_W * len(psids))()
        for i, p in enumerate(psids):
            entries[i].grfAccessPermissions = _FILE_ALL_ACCESS
            entries[i].grfAccessMode = _SET_ACCESS
            entries[i].grfInheritance = _NO_INHERITANCE
            entries[i].Trustee.MultipleTrusteeOperation = 0
            entries[i].Trustee.TrusteeForm = _TRUSTEE_IS_SID
            entries[i].Trustee.TrusteeType = _TRUSTEE_IS_UNKNOWN
            entries[i].Trustee.ptstrName = p

        acl = ctypes.c_void_p()
        res = _advapi32.SetEntriesInAclW(
            len(psids), entries, None, ctypes.byref(acl))
        if res:
            raise ctypes.WinError(res)
        try:
            res = _advapi32.SetNamedSecurityInfoW(
                path, _SE_FILE_OBJECT,
                _DACL_SECURITY_INFORMATION | _PROTECTED_DACL_SECURITY_INFORMATION,
                None, None, acl, None)
            if res:
                raise ctypes.WinError(res)
        finally:
            _kernel32.LocalFree(acl)
    finally:
        for p in psids:
            _kernel32.LocalFree(p)


def harden_key_acl(path):
    """Restrict a private key file to current user + Administrators + SYSTEM."""
    if os.name != "nt" or not os.path.exists(path):
        return False
    sid = _current_user_sid()
    if not sid:
        log_warning(f"cannot resolve current user SID for {os.path.basename(path)}")
        return False
    try:
        _set_restricted_dacl(path, sid)
        return True
    except Exception as e:
        log_warning(f"cannot harden ACL for {os.path.basename(path)}: {e}")
        return False


def harden_existing_keys():
    """Apply the restricted ACL to private keys already on disk (once)."""
    if not os.path.isdir(config.CERT_DIR):
        return 0
    marker = os.path.join(config.CERT_DIR, ".acl_hardened")
    if os.path.exists(marker):
        return 0
    count = 0
    for name in os.listdir(config.CERT_DIR):
        if name.endswith(".key") and harden_key_acl(
                os.path.join(config.CERT_DIR, name)):
            count += 1
    try:
        with open(marker, "w", encoding="ascii") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
    except Exception:
        pass
    if count:
        log(f"  [OK] hardened ACL on {count} private key file(s)")
    return count


def _secure_delete(path):
    """Overwrite then delete a private key (best effort on Windows)."""
    try:
        size = os.path.getsize(path)
        with open(path, "r+b") as f:
            f.write(os.urandom(size))
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        pass
    try:
        os.remove(path)
        return True
    except Exception as e:
        log_warning(f"cannot dispose {os.path.basename(path)}: {e}")
        return False


def dispose_legacy_private_keys():
    """Destroy archived 1.0.2 private keys.

    Kept separate from migrate_legacy_identity(): migration is about trust
    and certificates, disposal is about not keeping a leaked key forever.
    """
    if not os.path.isdir(config.LEGACY_DIR):
        return 0
    count = 0
    for root, _dirs, files in os.walk(config.LEGACY_DIR):
        for name in files:
            if name.lower().endswith((".key", ".pfx", ".p12")):
                if _secure_delete(os.path.join(root, name)):
                    count += 1
    if count:
        log(f"  [OK] securely disposed {count} legacy private key file(s)")
        try:
            with open(os.path.join(config.LEGACY_DIR, "KEYS_DISPOSED.txt"),
                      "w", encoding="ascii") as f:
                f.write("Legacy 1.0.2 private keys were deleted at "
                        + time.strftime("%Y-%m-%d %H:%M:%S") + "\n")
        except Exception:
            pass
    return count


def _generate_ca_crypto():
    """Pure-Python CA generation via cryptography library (no openssl.exe needed)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "MITM SNI Proxy CA"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SNI Proxy"),
        x509.NameAttribute(NameOID.COUNTRY_NAME, "CN"),
    ])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=False,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    with open(config.CA_KEY, "wb") as f:
        f.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ))
    with open(config.CA_CERT, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))


def _generate_wildcard_crypto():
    """Pure-Python multi-SAN wildcard generation via cryptography library."""
    with open(config.CA_KEY, "rb") as f:
        ca_key = serialization.load_pem_private_key(f.read(), password=None)
    with open(config.CA_CERT, "rb") as f:
        ca_cert = x509.load_pem_x509_certificate(f.read())

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "SNI Proxy Wildcard"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SNI Proxy"),
    ])

    san_list = []
    for b in config.WILDCARD_BASES:
        san_list.append(x509.DNSName(b))
        san_list.append(x509.DNSName(f"*.{b}"))

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, key_encipherment=True,
            key_cert_sign=False, crl_sign=False, content_commitment=False,
            data_encipherment=False, key_agreement=False,
            encipher_only=False, decipher_only=False
        ), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectAlternativeName(san_list), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    with open(config.WILDCARD_KEY, "wb") as f:
        f.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ))
    with open(config.WILDCARD_CERT, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))


def _generate_site_cert_crypto(domain, key_file, cert_file):
    """Pure-Python on-demand site certificate generation via cryptography library."""
    with open(config.CA_KEY, "rb") as f:
        ca_key = serialization.load_pem_private_key(f.read(), password=None)
    with open(config.CA_CERT, "rb") as f:
        ca_cert = x509.load_pem_x509_certificate(f.read())

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, domain),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SNI Proxy"),
    ])

    san_list = [x509.DNSName(domain)]
    if not domain.startswith("*."):
        san_list.append(x509.DNSName(f"*.{domain}"))

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, key_encipherment=True,
            key_cert_sign=False, crl_sign=False, content_commitment=False,
            data_encipherment=False, key_agreement=False,
            encipher_only=False, decipher_only=False
        ), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectAlternativeName(san_list), critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    with open(key_file, "wb") as f:
        f.write(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ))
    with open(cert_file, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))


def generate_ca():
    ensure_cert_dir()
    if os.path.exists(config.CA_KEY) and os.path.exists(config.CA_CERT):
        return config.CA_KEY, config.CA_CERT

    log("  [*] Generating per-device CA certificate...")
    try:
        if HAVE_CRYPTOGRAPHY:
            _generate_ca_crypto()
        else:
            subprocess.run([config.OPENSSL, "genrsa", "-out", config.CA_KEY, "2048"],
                           capture_output=True, check=True, creationflags=NO_WINDOW)
            subprocess.run(
                [config.OPENSSL, "req", "-x509", "-new", "-nodes",
                 "-key", config.CA_KEY, "-sha256", "-days", "3650",
                 "-out", config.CA_CERT,
                 "-subj", "/CN=MITM SNI Proxy CA/O=SNI Proxy/C=CN"],
                capture_output=True, check=True, creationflags=NO_WINDOW)
    except Exception as e:
        log_error(f"CA generation failed: {e}")
        raise
    harden_key_acl(config.CA_KEY)
    log(f"  [OK] CA cert: {config.CA_CERT}")
    return config.CA_KEY, config.CA_CERT


def generate_wildcard():
    """Sign the shared multi-SAN wildcard cert with this device's CA."""
    ensure_cert_dir()
    if (os.path.exists(config.WILDCARD_CERT)
            and os.path.exists(config.WILDCARD_KEY)):
        return True
    if not (os.path.exists(config.CA_KEY) and os.path.exists(config.CA_CERT)):
        return False

    log("  [*] Generating shared wildcard certificate...")
    try:
        if HAVE_CRYPTOGRAPHY:
            _generate_wildcard_crypto()
        else:
            ext_file = os.path.join(config.CERT_DIR, "_wildcard.ext")
            csr_file = os.path.join(config.CERT_DIR, "_wildcard.csr")
            sans = ",".join("DNS:%s,DNS:*.%s" % (b, b) for b in config.WILDCARD_BASES)
            try:
                subprocess.run([config.OPENSSL, "genrsa", "-out", config.WILDCARD_KEY, "2048"],
                               capture_output=True, check=True, creationflags=NO_WINDOW)
                subprocess.run(
                    [config.OPENSSL, "req", "-new", "-key", config.WILDCARD_KEY,
                     "-out", csr_file, "-subj", "/CN=SNI Proxy Wildcard/O=SNI Proxy"],
                    capture_output=True, check=True, creationflags=NO_WINDOW)
                with open(ext_file, "w") as f:
                    f.write("basicConstraints=CA:FALSE\n")
                    f.write("keyUsage=digitalSignature,keyEncipherment\n")
                    f.write("extendedKeyUsage=serverAuth\n")
                    f.write(f"subjectAltName={sans}\n")
                subprocess.run(
                    [config.OPENSSL, "x509", "-req", "-in", csr_file,
                     "-CA", config.CA_CERT, "-CAkey", config.CA_KEY, "-CAcreateserial",
                     "-out", config.WILDCARD_CERT, "-days", "365", "-sha256",
                     "-extfile", ext_file],
                    capture_output=True, check=True, creationflags=NO_WINDOW)
            finally:
                for f in (ext_file, csr_file):
                    try:
                        os.remove(f)
                    except OSError:
                        pass
        harden_key_acl(config.WILDCARD_KEY)
        log(f"  [OK] wildcard cert: {config.WILDCARD_CERT}")
        return True
    except Exception as e:
        log_error(f"wildcard cert generation failed: {e}")
        return False


def _file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _pem_thumbprint(path):
    """Windows-style SHA-1 thumbprint of the first PEM certificate."""
    with open(path, "r", encoding="ascii", errors="ignore") as f:
        text = f.read()
    begin = "-----BEGIN CERTIFICATE-----"
    end = "-----END CERTIFICATE-----"
    start = text.index(begin) + len(begin)
    stop = text.index(end)
    der = base64.b64decode("".join(text[start:stop].split()))
    return hashlib.sha1(der).hexdigest().upper()


def migrate_legacy_identity():
    """Archive certs signed by the shared 1.0.2 CA and record its thumbprint."""
    if not os.path.exists(config.CA_CERT):
        return
    try:
        if _file_sha256(config.CA_CERT) != config.LEGACY_CA_SHA256:
            return
    except Exception:
        return

    log("  [*] 1.0.2 shared CA detected, rotating to a per-device CA...")
    try:
        os.makedirs(config.LEGACY_DIR, exist_ok=True)
        try:
            with open(config.LEGACY_THUMB_FILE, "w", encoding="ascii") as f:
                f.write(_pem_thumbprint(config.CA_CERT))
        except Exception as e:
            log_error(f"cannot write legacy CA thumbprint: {e}")

        for name in list(os.listdir(config.CERT_DIR)):
            if name.endswith((".crt", ".key", ".srl")):
                src = os.path.join(config.CERT_DIR, name)
                dst = os.path.join(config.LEGACY_DIR, name)
                try:
                    os.replace(src, dst)
                except Exception:
                    try:
                        shutil.move(src, dst)
                    except Exception as e:
                        log_error(f"cannot archive {name}: {e}")
        log(f"  [OK] legacy certificates archived to {config.LEGACY_DIR}")
    except Exception as e:
        log_error(f"legacy certificate migration failed: {e}")


def ensure_identity():
    """Create (or migrate to) a unique CA and wildcard cert on this device."""
    ensure_cert_dir()
    migrate_legacy_identity()
    # Separate step: the leaked 1.0.2 private keys must not be kept around.
    dispose_legacy_private_keys()
    ca_key, ca_cert = generate_ca()
    generate_wildcard()
    harden_existing_keys()
    return ca_key, ca_cert


def generate_site_cert(domain):
    ensure_cert_dir()
    # domain 来自客户端 CONNECT 请求，必须过滤路径分隔符等非法字符，
    # 否则构造的域名可能把证书文件写到 CERT_DIR 之外
    safe = domain.replace("*.", "wildcard_")
    safe = "".join(c if c.isalnum() or c in ".-_" else "_" for c in safe)
    key_file = os.path.join(config.CERT_DIR, f"{safe}.key")
    cert_file = os.path.join(config.CERT_DIR, f"{safe}.crt")
    csr_file = os.path.join(config.CERT_DIR, f"{safe}.csr")
    ext_file = os.path.join(config.CERT_DIR, f"{safe}.ext")

    if os.path.exists(key_file) and os.path.exists(cert_file):
        return cert_file, key_file

    # shared wildcard cert covers this host: skip openssl entirely
    if (os.path.exists(config.WILDCARD_CERT)
            and os.path.exists(config.WILDCARD_KEY)
            and wildcard_covers(domain)):
        return config.WILDCARD_CERT, config.WILDCARD_KEY

    # tombstone: recently failed domains retry at most once per TTL,
    # otherwise a broken domain causes a flash/CPU loop
    last_fail = _cert_fail.get(domain)
    if last_fail and time.time() - last_fail < _CERT_FAIL_TTL:
        return None, None

    with _cert_lock:
        if os.path.exists(key_file) and os.path.exists(cert_file):
            return cert_file, key_file
        try:
            if HAVE_CRYPTOGRAPHY:
                _generate_site_cert_crypto(domain, key_file, cert_file)
            else:
                subprocess.run([config.OPENSSL, "genrsa", "-out", key_file, "2048"],
                               capture_output=True, check=True, timeout=15,
                               creationflags=NO_WINDOW)
                subprocess.run(
                    [config.OPENSSL, "req", "-new", "-key", key_file,
                     "-out", csr_file, "-subj", f"/CN={domain}/O=SNI Proxy"],
                    capture_output=True, check=True, timeout=15,
                    creationflags=NO_WINDOW)

                sans = f"DNS:{domain}"
                if not domain.startswith("*."):
                    sans += f",DNS:*.{domain}"
                with open(ext_file, "w") as f:
                    f.write("basicConstraints=CA:FALSE\n")
                    f.write("keyUsage=digitalSignature,keyEncipherment\n")
                    f.write("extendedKeyUsage=serverAuth\n")
                    f.write(f"subjectAltName={sans}\n")

                subprocess.run(
                    [config.OPENSSL, "x509", "-req", "-in", csr_file,
                     "-CA", config.CA_CERT, "-CAkey", config.CA_KEY, "-CAcreateserial",
                     "-out", cert_file, "-days", "365", "-sha256",
                     "-extfile", ext_file],
                    capture_output=True, check=True, timeout=15,
                    creationflags=NO_WINDOW)

                try:
                    os.remove(csr_file)
                    os.remove(ext_file)
                except OSError:
                    pass
            harden_key_acl(key_file)
            _cert_fail.pop(domain, None)
            return cert_file, key_file
        except Exception as e:
            log_error(f"cert generation failed for {domain}: {e}")
            _cert_fail[domain] = time.time()
            return None, None
