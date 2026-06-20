# broker/mt5_connection.py  —  Day 31 | MT5 Demo Connection Layer
# ============================================================
# AI Brain ↔ MetaTrader5 demo terminal-এর মধ্যে সংযোগ স্থাপন করে।
# এই module শুধু "connect/disconnect/status" নিয়ে কাজ করে —
# order placement থাকবে broker/mt5_executor.py-তে (Day 32-33)।
# ============================================================

import time
from datetime import datetime
from utils.logger import get_logger

log = get_logger("mt5_connection")

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    log.warning(
        "MetaTrader5 package not found — install with: pip install MetaTrader5 "
        "(Windows only; MT5 terminal-ও install করা থাকতে হবে)"
    )


class MT5Connection:
    """
    MT5 demo terminal-এর সাথে connection manage করে।

    গুরুত্বপূর্ণ:
      - MT5 desktop terminal চালু থাকতে হবে (mt5.initialize() সেটার সাথেই কথা বলে)
      - এটা শুধুমাত্র Windows-এ কাজ করে (MetaTrader5 package Windows-only)
      - Linux/Mac-এ চালাতে চাইলে Wine বা একটা remote Windows VM লাগবে

    Usage:
        conn = MT5Connection(login=12345678, password="xxxx", server="ICMarketsSC-Demo")
        if conn.connect():
            info = conn.get_account_info()
            conn.disconnect()
    """

    MAX_RETRIES = 3
    RETRY_DELAY_SEC = 5

    def __init__(self, login: int, password: str, server: str, path: str = None):
        self.login = login
        self.password = password
        self.server = server
        self.path = path          # MT5 terminal exe path (optional override)
        self.connected = False
        self.connected_at: datetime | None = None

    # ─────────────────────────────────────────────
    # CONNECT / DISCONNECT
    # ─────────────────────────────────────────────

    def connect(self) -> bool:
        """
        MT5 terminal initialize করে login করে।
        Retry logic সহ — broker server momentarily busy থাকলে আবার try করবে।
        """
        if not MT5_AVAILABLE:
            log.error("MetaTrader5 package নেই — connect করা সম্ভব নয়")
            return False

        for attempt in range(1, self.MAX_RETRIES + 1):
            ok = self._try_connect()
            if ok:
                return True
            log.warning(
                f"[MT5Connection] Attempt {attempt}/{self.MAX_RETRIES} failed — "
                f"retrying in {self.RETRY_DELAY_SEC}s"
            )
            time.sleep(self.RETRY_DELAY_SEC)

        log.error("[MT5Connection] সব retry শেষ — connect ব্যর্থ")
        return False

    def _try_connect(self) -> bool:
        init_kwargs = {}
        if self.path:
            init_kwargs["path"] = self.path

        if not mt5.initialize(**init_kwargs):
            err = mt5.last_error()
            log.error(f"[MT5Connection] mt5.initialize() failed: {err}")
            return False

        authorized = mt5.login(
            self.login,
            password=self.password,
            server=self.server,
        )

        if not authorized:
            err = mt5.last_error()
            log.error(f"[MT5Connection] Login failed: {err}")
            mt5.shutdown()
            return False

        self.connected = True
        self.connected_at = datetime.utcnow()
        self._print_connected_banner()
        return True

    def disconnect(self) -> None:
        if MT5_AVAILABLE and self.connected:
            mt5.shutdown()
        self.connected = False
        log.info("[MT5Connection] Disconnected")

    # ─────────────────────────────────────────────
    # ACCOUNT INFO
    # ─────────────────────────────────────────────

    def get_account_info(self) -> dict | None:
        """Account balance/equity/margin ফেরত দেয়। Connect না থাকলে None।"""
        if not self._require_connected():
            return None

        account = mt5.account_info()
        if account is None:
            log.error(f"[MT5Connection] account_info() failed: {mt5.last_error()}")
            return None

        info = {
            "login":        account.login,
            "balance":      account.balance,
            "equity":       account.equity,
            "margin":       account.margin,
            "free_margin":  account.margin_free,
            "margin_level": account.margin_level,
            "currency":     account.currency,
            "leverage":     account.leverage,
            "server":       account.server,
            "trade_allowed": account.trade_allowed,
        }
        return info

    def print_account_info(self) -> None:
        info = self.get_account_info()
        bar = "═" * 44
        if not info:
            log.warning("Account info পাওয়া যায়নি (connected?)")
            return
        log.info(bar)
        log.info("  💰  ACCOUNT INFORMATION")
        log.info(bar)
        log.info(f"  Balance      : ${info['balance']:.2f}")
        log.info(f"  Equity       : ${info['equity']:.2f}")
        log.info(f"  Margin       : ${info['margin']:.2f}")
        log.info(f"  Free Margin  : ${info['free_margin']:.2f}")
        log.info(f"  Margin Level : {info['margin_level']:.1f}%")
        log.info(f"  Trade Allowed: {info['trade_allowed']}")
        log.info(bar)

    # ─────────────────────────────────────────────
    # INTERNAL
    # ─────────────────────────────────────────────

    def _require_connected(self) -> bool:
        if not MT5_AVAILABLE:
            log.error("MetaTrader5 package নেই")
            return False
        if not self.connected:
            log.error("MT5-এর সাথে connected নয় — আগে connect() call করো")
            return False
        return True

    def _print_connected_banner(self) -> None:
        account = mt5.account_info()
        bar = "═" * 44
        log.info(bar)
        log.info("  🤖  AI TRADER — MT5 CONNECTION")
        log.info(bar)
        log.info(f"  Connected : {self.server}")
        log.info(f"  Account   : {self.login}")
        log.info(f"  Status    : ✅ Ready")
        if account:
            log.info(f"  Balance   : ${account.balance:.2f}")
        log.info(bar)


if __name__ == "__main__":
    # Quick manual test — .env থেকে credentials নেয়
    from config import MT5_LOGIN, MT5_PASSWORD, MT5_SERVER

    conn = MT5Connection(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER)
    if conn.connect():
        conn.print_account_info()
        conn.disconnect()