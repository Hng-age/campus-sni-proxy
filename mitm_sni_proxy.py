#!/usr/bin/env python3
"""Entry point for the campus SNI proxy.

The implementation lives in the ``sni_proxy`` package:
  config.py    constants and paths
  logsetup.py  rotating file logging
  netutil.py   DNS, domain and certificate matching
  certs.py     per-device CA, wildcard and site certificates
  uplinks.py   multi-network uplink detection and binding
  upstream.py  TLS verification, SNI fallback, route cache
  server.py    CONNECT handling and forwarding
"""

import os
import sys

from sni_proxy.certs import ensure_identity
from sni_proxy.config import CA_CERT, WILDCARD_CERT
from sni_proxy.logsetup import log, log_error
from sni_proxy.server import main


if __name__ == "__main__":
    if "--init-certs" in sys.argv:
        try:
            ensure_identity()
            ok = os.path.exists(CA_CERT) and os.path.exists(WILDCARD_CERT)
            log(f"identity ready: ca={os.path.exists(CA_CERT)} "
                f"wildcard={os.path.exists(WILDCARD_CERT)}")
            sys.exit(0 if ok else 2)
        except Exception as e:
            log_error(f"init-certs failed: {e}")
            sys.exit(1)
    main()
