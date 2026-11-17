"""Per-device CA, wildcard certificate and on-demand site certificates."""

import base64
import hashlib
import os
import shutil
import subprocess
import threading
import time

from . import config
from .config import NO_WINDOW
from .logsetup import log, log_error
from .netutil import wildcard_covers

_cert_lock = threading.Lock()

# cert generation failure tombstones: domain -> timestamp (avoid flash loops)
_cert_fail = {}
_CERT_FAIL_TTL = 60


def ensure_cert_dir():
    os.makedirs(config.CERT_DIR, exist_ok=True)


def generate_ca():
    ensure_cert_dir()
    if os.path.exists(config.CA_KEY) and os.path.exists(config.CA_CERT):
        return config.CA_KEY, config.CA_CERT

    log("  [*] Generating per-device CA certificate...")
    try:
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

    ext_file = os.path.join(config.CERT_DIR, "_wildcard.ext")
    csr_file = os.path.join(config.CERT_DIR, "_wildcard.csr")
    sans = ",".join("DNS:%s,DNS:*.%s" % (b, b) for b in config.WILDCARD_BASES)
    log("  [*] Generating shared wildcard certificate...")
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
        log(f"  [OK] wildcard cert: {config.WILDCARD_CERT}")
        return True
    except Exception as e:
        log_error(f"wildcard cert generation failed: {e}")
        return False
    finally:
        for f in (ext_file, csr_file):
            try:
                os.remove(f)
            except OSError:
                pass


def _file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _pem_thumbprint(path):
    """Windows-style SHA-1 thumbprint of the first PEM certificate."""
    text = open(path, "r", encoding="ascii", errors="ignore").read()
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
    ca_key, ca_cert = generate_ca()
    generate_wildcard()
    return ca_key, ca_cert


def generate_site_cert(domain):
    ensure_cert_dir()
    safe = domain.replace("*.", "wildcard_").replace(":", "_")
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
            _cert_fail.pop(domain, None)
            return cert_file, key_file
        except Exception as e:
            log_error(f"cert generation failed for {domain}: {e}")
            _cert_fail[domain] = time.time()
            return None, None
