# utils/logger.py
# ============================================================
# AI Trader — Centralized Logging System
# print() এর বদলে এটা ব্যবহার করো — সব logs file-এ save হবে
# ============================================================

import logging
import os
from datetime import datetime

LOG_DIR  = "logs"
LOG_FILE = os.path.join(LOG_DIR, "trader.log")

os.makedirs(LOG_DIR, exist_ok=True)


def get_logger(name: str) -> logging.Logger:
    """
    যেকোনো module থেকে call করো:
        from utils.logger import get_logger
        log = get_logger(__name__)
        log.info("Data fetched")
        log.warning("Missing candles")
        log.error("Fetch failed")
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger   # already configured

    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)-25s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── File handler (DEBUG+) ──
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    # ── Console handler (INFO+) ──
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger