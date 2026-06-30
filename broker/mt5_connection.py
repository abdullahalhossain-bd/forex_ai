# broker/mt5_connection.py

import time
from datetime import datetime
from threading import Lock
from utils.logger import get_logger

log = get_logger("mt5_connection")

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    log.warning(
        "MetaTrader5 package not found. Install with: pip install MetaTrader5"
    )


class MT5Connection:
    MAX_RETRIES = 3
    RETRY_DELAY_SEC = 5

    # Day 90+ hotfix: health-check tuning.
    # Previously is_alive() called BOTH terminal_info() AND account_info()
    # under the same lock on every check, and marked the connection dead
    # on the very first None result. With multiple AITrader instances
    # (one per pair) all hammering the same MT5 terminal through this
    # shared lock, terminal_info()/account_info() would occasionally
    # return None just from momentary contention/latency — not a real
    # disconnect. That caused the "MT5 connection lost" flapping seen
    # in logs every 5-10 minutes even though MT5 was actually fine.
    HEALTH_CHECK_RETRIES = 2          # extra in-place retries before declaring dead
    HEALTH_CHECK_RETRY_DELAY = 0.5    # seconds between in-place retries

    MT5_LOCK = Lock()

    def __init__(
        self,
        login: int,
        password: str,
        server: str,
        path: str = None
    ):
        self.login = login
        self.password = password
        self.server = server
        self.path = path

        self.connected = False
        self.connected_at = None
        self.last_ping = None

        # Day 90+ hotfix: track consecutive health-check failures so we
        # can distinguish "one flaky call" from "actually disconnected".
        self._consecutive_failures = 0

    # ==========================================================
    # CONNECT
    # ==========================================================

    def connect(self) -> bool:
        if not MT5_AVAILABLE:
            log.error("MetaTrader5 package not installed")
            return False

        for attempt in range(1, self.MAX_RETRIES + 1):

            if self._try_connect():
                return True

            log.warning(
                f"[MT5Connection] Attempt "
                f"{attempt}/{self.MAX_RETRIES} failed "
                f"retrying in {self.RETRY_DELAY_SEC}s"
            )

            time.sleep(self.RETRY_DELAY_SEC)

        log.error("[MT5Connection] Connection failed")
        return False

    def _try_connect(self) -> bool:
        try:
            with self.MT5_LOCK:
                mt5.shutdown()
                time.sleep(1)

                init_kwargs = {}

                if self.path:
                    init_kwargs["path"] = self.path

                if not mt5.initialize(**init_kwargs):
                    err = mt5.last_error()
                    log.error(
                        f"[MT5Connection] initialize failed: {err}"
                    )
                    return False

                authorized = mt5.login(
                    self.login,
                    password=self.password,
                    server=self.server
                )

                if not authorized:
                    err = mt5.last_error()
                    log.error(
                        f"[MT5Connection] Login failed: {err}"
                    )
                    mt5.shutdown()
                    return False

            self.connected = True
            self.connected_at = datetime.utcnow()
            self.last_ping = datetime.utcnow()
            self._consecutive_failures = 0

            self._print_connected_banner()
            return True

        except Exception as e:
            log.exception(
                f"[MT5Connection] Connect exception: {e}"
            )
            return False

    # ==========================================================
    # DISCONNECT
    # ==========================================================

    def disconnect(self):
        try:
            with self.MT5_LOCK:
                if MT5_AVAILABLE:
                    mt5.shutdown()
        except Exception:
            pass

        self.connected = False
        self.connected_at = None
        self.last_ping = None

        log.info("[MT5Connection] Disconnected")

    # ==========================================================
    # HEALTH CHECK
    # ==========================================================

    def is_alive(self) -> bool:
        """Day 90+ hotfix: lenient health check.

        Old behavior: grabbed the lock, called terminal_info() AND
        account_info() back-to-back, and immediately marked the
        connection dead if either returned None — even on a single
        transient hiccup. With several AITrader instances sharing one
        MT5 terminal via MT5_LOCK, that produced frequent false-positive
        "disconnect" events (visible in logs every 5-10 min) even though
        the terminal was actually fine moments later.

        New behavior:
          - Only call terminal_info() (account_info() is checked
            separately, on demand, by get_account_info() — no need to
            pay for both calls on every health check).
          - On a None result, retry in-place up to
            HEALTH_CHECK_RETRIES times with a short delay before
            declaring the connection dead.
          - Track consecutive failures for visibility/debugging.
        """
        if not MT5_AVAILABLE:
            return False

        attempts = 1 + self.HEALTH_CHECK_RETRIES

        for attempt in range(1, attempts + 1):
            try:
                with self.MT5_LOCK:
                    terminal = mt5.terminal_info()

                if terminal is not None:
                    self.last_ping = datetime.utcnow()
                    self._consecutive_failures = 0
                    return True

                if attempt < attempts:
                    time.sleep(self.HEALTH_CHECK_RETRY_DELAY)

            except Exception as e:
                log.warning(
                    f"[MT5Connection] Health check error "
                    f"(attempt {attempt}/{attempts}): {e}"
                )
                if attempt < attempts:
                    time.sleep(self.HEALTH_CHECK_RETRY_DELAY)

        # All attempts exhausted — genuinely consider it down
        self._consecutive_failures += 1
        self.connected = False
        log.warning(
            f"[MT5Connection] Health check failed after {attempts} "
            f"attempts (consecutive_failures={self._consecutive_failures})"
        )
        return False

    # ==========================================================
    # ACCOUNT INFO
    # ==========================================================

    def get_account_info(self):
        if not self._require_connected():
            return None

        try:
            with self.MT5_LOCK:
                account = mt5.account_info()

            if account is None:
                log.error(
                    f"account_info failed: {mt5.last_error()}"
                )
                return None

            return {
                "login": account.login,
                "balance": account.balance,
                "equity": account.equity,
                "margin": account.margin,
                "free_margin": account.margin_free,
                "margin_level": account.margin_level,
                "currency": account.currency,
                "leverage": account.leverage,
                "server": account.server,
                "trade_allowed": account.trade_allowed,
            }

        except Exception as e:
            log.exception(
                f"[MT5Connection] account info error: {e}"
            )
            return None

    # ==========================================================
    # INTERNAL
    # ==========================================================

    def _require_connected(self):
        if not self.connected:
            return False

        if not self.is_alive():
            self.connected = False
            return False

        return True

    # ==========================================================
    # TICK SAFE
    # ==========================================================

    def get_tick(self, symbol):
        if not self._require_connected():
            return None

        try:
            with self.MT5_LOCK:
                tick = mt5.symbol_info_tick(symbol)

            if tick is None:
                log.warning(
                    f"[MT5Connection] No tick for {symbol}"
                )
                return None

            return tick

        except Exception as e:
            log.exception(
                f"[MT5Connection] Tick error: {e}"
            )
            return None

    # ==========================================================
    # RECONNECT
    # ==========================================================

    def reconnect(self):
        log.warning(
            "[MT5Connection] Reconnecting..."
        )

        self.disconnect()

        time.sleep(2)

        return self.connect()

    # ==========================================================
    # BANNER
    # ==========================================================

    def _print_connected_banner(self):
        try:
            with self.MT5_LOCK:
                account = mt5.account_info()

            bar = "═" * 44

            log.info(bar)
            log.info(
                "  🤖  AI TRADER — MT5 CONNECTION"
            )
            log.info(bar)
            log.info(
                f"  Connected : {self.server}"
            )
            log.info(
                f"  Account   : {self.login}"
            )
            log.info(
                "  Status    : ✅ Ready"
            )

            if account:
                log.info(
                    f"  Balance   : ${account.balance:.2f}"
                )

            log.info(bar)

        except Exception:
            pass