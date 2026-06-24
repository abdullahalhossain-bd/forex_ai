# execution/execution_router.py  —  Day 31 | Paper vs MT5 Demo Switch
# ============================================================
# DecisionAgent-এর output এখানে আসে, আর এই module ঠিক করে সেটা
# PaperTrader-এ যাবে নাকি real MT5 demo broker-এ যাবে।
#
#         AI Decision
#              ↓
#         Risk Engine
#              ↓
#       Execution Router  ⭐ (এই ফাইল)
#         /         \
#   Paper Mode   MT5 Demo Mode
#         \         /
#          Trade Result
#              ↓
#       Memory + Learning
#
# একই interface রাখা হয়েছে যাতে DecisionAgent বা circuit breaker
# কোনো change ছাড়াই কাজ করতে পারে — mode পাল্টালে শুধু .env-এ
# EXECUTION_MODE পাল্টাবে।
#
# Day 37 fix: __init__ এখন একটা existing PaperTrader instance accept করে
# (`paper_trader=`)। আগে এই router নিজের আলাদা PaperTrader বানাতো।
#
# Day 38 fix: mt5_demo mode আগে শুধু permission check করে PENDING_EXECUTOR
# stub রিটার্ন করত — কোনো real order যেত না। এখন broker/order_manager.py
# (Day 33-এ বানানো, কিন্তু এতদিন wire হয়নি) দিয়ে real mt5.order_send()
# কল করে, এবং broker/journal_bridge.py দিয়ে DB-তে log করে।
# ============================================================

from utils.logger import get_logger
from config import validate_mt5_config

log = get_logger("execution_router")


def _check_absolute_safety(symbol: str) -> tuple[bool, str]:
    """Day 81+ ABSOLUTE_SAFETY hard gate.

    These checks run BEFORE any trade is sent to MT5, regardless of
    TRADING_MODE / TEST_MODE.  They are the last line of defense
    against:
      - broker disconnect
      - spread explosion (news just hit)
      - market closed

    Returns (safe, reason).  When ABSOLUTE_SAFETY=false, this function
    is skipped entirely (returns True).
    """
    try:
        from config import ABSOLUTE_SAFETY
        if not ABSOLUTE_SAFETY:
            return True, "ABSOLUTE_SAFETY disabled"
    except Exception:
        pass  # if config can't be imported, default to running the check

    try:
        from data.live_feed import get_live_feed
        feed = get_live_feed()
        safe, reason = feed.is_safe_to_trade(symbol)
        if not safe:
            log.warning(f"[ABSOLUTE_SAFETY] BLOCKED {symbol}: {reason}")
        return safe, reason
    except Exception as e:
        log.debug(f"[ABSOLUTE_SAFETY] check failed (allowing): {e}")
        return True, "safety check unavailable"


class ExecutionRouter:
    """
    Single entry point — DecisionAgent-এর result dict নিয়ে MT5 demo
    broker-এ পাঠায়।

    Usage:
        router = ExecutionRouter(db=db)
        trade = router.execute(decision_result)
    """

    def __init__(self, mode: str = None, db=None, paper_trader = None):
        # Mode is always mt5_demo now - paper trading removed
        self.mode = "mt5_demo"
        self._mt5_executor = None
        self._db = db

        if self.mode == "mt5_demo":
            validate_mt5_config()
            # Lazy import — MT5 package না থাকলেও paper mode চলবে
            from broker.mt5_connection import MT5Connection
            from broker.health_monitor import HealthMonitor
            from broker.account_manager import AccountManager
            from broker.order_manager import OrderManager
            from broker.journal_bridge import JournalBridge
            from config import MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, MT5_PATH

            self._mt5_conn = MT5Connection(
                login=MT5_LOGIN, password=MT5_PASSWORD,
                server=MT5_SERVER, path=MT5_PATH or None,
            )
            if not self._mt5_conn.connect():
                raise RuntimeError(
                    "MT5 demo connection failed — check credentials and MT5 terminal "
                    "is running. EXECUTION_MODE=mt5_demo requires MT5 terminal."
                )
            self._account_manager = AccountManager(self._mt5_conn)
            self._health_monitor = HealthMonitor(
                self._mt5_conn,
                on_disconnect=lambda msg: log.warning(f"[Router] {msg}"),
                on_reconnect=lambda msg: log.info(f"[Router] {msg}"),
                on_fatal=lambda msg: log.error(f"[Router] {msg}"),
            )
            # Day 38 — real order execution + DB journal wiring
            self._order_manager  = OrderManager(self._mt5_conn, self._account_manager)
            self._journal_bridge = JournalBridge(db=self._db)
            log.info("[ExecutionRouter] Mode: MT5_DEMO (real broker, demo account)")

        else:
            raise ValueError(f"Unknown EXECUTION_MODE: {self.mode}")

    # ─────────────────────────────────────────────
    # PUBLIC ENTRY POINT
    # ─────────────────────────────────────────────

    def execute(self, decision_result: dict) -> dict | None:
        """
        DecisionAgent.decide()-এর output নিয়ে MT5 demo broker-এ trade পাঠায়।
        """
        if decision_result.get("decision") not in ("BUY", "SELL"):
            log.info(f"[ExecutionRouter] No action — decision={decision_result.get('decision')}")
            return None

        return self._execute_mt5_demo(decision_result)

    def _execute_mt5_demo(self, decision_result: dict) -> dict | None:
        """
        Day 38 — real MT5 demo order placement।
        OrderManager দিয়ে actual mt5.order_send() কল করে, JournalBridge
        দিয়ে DB-তে save করে — PaperTrader-এর মতো same `trades` table-এ,
        যাতে learning memory একসাথে থাকে।
        """
        symbol    = decision_result.get("symbol", "EURUSD")
        direction = decision_result.get("decision")
        lot       = decision_result.get("lot", 0.01)
        sl        = decision_result.get("sl")
        tp        = decision_result.get("tp")

        # ── Day 81+ ABSOLUTE_SAFETY hard gate ────────────────────
        # Runs BEFORE account_manager.trading_permission() because
        # broker-side problems (spread explosion, disconnect) are
        # more fundamental than risk-engine approval.
        safe, reason = _check_absolute_safety(symbol)
        if not safe:
            log.warning(
                f"[ExecutionRouter] ABSOLUTE_SAFETY blocked trade — "
                f"{symbol} {direction}: {reason}"
            )
            return None

        perm = self._account_manager.trading_permission(
            symbol=symbol,
            risk_engine_ok=True,   # risk engine আগেই pass করেছে ধরে নেওয়া হলো
        )
        if not perm["allowed"]:
            log.warning(
                f"[ExecutionRouter] MT5 demo — trade blocked: {perm['failed_checks']}"
            )
            return None

        broker_symbol = perm["broker_symbol"]

        order_result = self._order_manager.place_market_order(
            symbol=broker_symbol,
            direction=direction,
            lot=lot,
            sl=sl,
            tp=tp,
            comment="ai_trader_demo",
        )

        if not order_result.get("success"):
            log.error(
                f"[ExecutionRouter] MT5 demo — order failed: {order_result.get('reason')}"
            )
            return None

        filled_entry = order_result.get("price", decision_result.get("entry"))
        trade_id = self._journal_bridge.log_mt5_open(
            decision_result   = decision_result,
            broker_symbol     = broker_symbol,
            filled_entry      = filled_entry,
            mt5_order_ticket  = order_result.get("ticket"),
        )

        log.info(
            f"[ExecutionRouter] ✅ MT5 demo order FILLED — {direction} {broker_symbol} "
            f"lot={lot} ticket={order_result.get('ticket')} → DB #{trade_id}"
        )

        return {
            "id":            trade_id,
            "status":        "FILLED",
            "broker_symbol": broker_symbol,
            "ticket":        order_result.get("ticket"),
            "entry":         filled_entry,
            "sl":            sl,
            "tp":            tp,
            "lot":           lot,
            "type":          direction,
            "pair":          broker_symbol,
        }

    def shutdown(self) -> None:
        if hasattr(self, "_mt5_conn"):
            self._mt5_conn.disconnect()
        log.info("[ExecutionRouter] Shutdown complete")