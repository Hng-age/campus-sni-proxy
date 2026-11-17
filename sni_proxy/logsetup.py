"""Rotating file logging with timestamps and levels."""

import logging
import logging.handlers
import os
import sys

from . import config


def setup_logging():
    """Create the rotating file logger (2 MB x 3 backups)."""
    os.makedirs(config.LOG_DIR, exist_ok=True)
    logger = logging.getLogger("sni_proxy")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            "%Y-%m-%d %H:%M:%S")
    try:
        fh = logging.handlers.RotatingFileHandler(
            config.LOG_FILE, maxBytes=2 * 1024 * 1024,
            backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except Exception:
        pass
    if sys.stderr:
        try:
            ch = logging.StreamHandler()
            ch.setFormatter(fmt)
            logger.addHandler(ch)
        except Exception:
            pass
    return logger


LOGGER = setup_logging()


def log(msg):
    try:
        LOGGER.info(msg)
    except Exception:
        pass


def log_error(msg):
    try:
        LOGGER.error(msg)
    except Exception:
        pass


def log_warning(msg):
    try:
        LOGGER.warning(msg)
    except Exception:
        pass


def log_debug(msg):
    try:
        LOGGER.debug(msg)
    except Exception:
        pass
