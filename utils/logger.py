# utils/logger.py
# ============================================================
# AI Trader — Centralized Logging System
# print() এর বদলে এটা ব্যবহার করো — সব logs file-এ save হবে
#
# Hotfix: console handler now writes through a UTF-8-wrapped stdout
# stream instead of the bare default. On Windows, plain sys.stdout uses
# the cp1252 codepage, which can't encode emoji/box-drawing characters
# (✅ ❌ ⛔ 🟡 ═ ━ → etc.) used throughout the log messages — every such
# line was raising UnicodeEncodeError ("--- Logging error ---") and
# spamming the console while losing the actual log content. The file
# handler was already safe (encoding="utf-8" was set there); only the
# console handler was missing the equivalent fix.
# ============================================================

import io
import logging
import os
import sys
from datetime import datetime

LOG_DIR  = "logs"
LOG_FILE = os.path.join(LOG_DIR, "trader.log")

os.makedirs(LOG_DIR, exist_ok=True)


def _utf8_console_stream():
    """
    Wrap sys.stdout so console output is encoded as UTF-8 regardless of
    the OS-default codepage (cp1252 on most Windows setups). Falls back
    to the raw stream if stdout doesn't expose a .buffer (e.g. when
    stdout has already been redirected/wrapped, or in some IDE/test
    runners) so logging never breaks even in unusual environments.
    """
    try:
        return io.TextIOWrapper(
            sys.stdout.buffer,
            encoding="utf-8",
            errors="replace",
            line_buffering=True,
        )
    except (AttributeError, ValueError):
        return sys.stdout


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
    # UTF-8 wrapped stream so emoji/box-drawing chars never raise
    # UnicodeEncodeError on Windows' cp1252 console codepage.
    ch = logging.StreamHandler(_utf8_console_stream())
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)

    # Stop records from also bubbling up to the root logger. If anything
    # else in the process (main.py, a third-party lib like python-telegram-
    # bot, or a stray logging.basicConfig() call) has attached its own
    # StreamHandler to the root logger, every message from THIS logger
    # would otherwise be emitted twice: once through our UTF-8-safe
    # console handler above, and once through that other handler — which,
    # if it doesn't specify an encoding, hits the same cp1252 crash on
    # Windows. Disabling propagation makes this logger fully self-
    # contained so its own handlers are the only ones that ever run.
    logger.propagate = False

    return logger