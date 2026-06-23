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
from config import EXECUTION_MODE, validate_mt5_config
from execution.paper_trader import PaperTrader

log = get_logger("execution_router")


class ExecutionRouter:
    """
    Single entry point — DecisionAgent-এর result dict নিয়ে সঠিক
    execution backend-এ পাঠায়।

    Usage:
        paper = PaperTrader(db=db)
        router = ExecutionRouter(mode="paper", db=db, paper_trader=paper)
        trade = router.execute(decision_result)
    """

    def __init__(self, mode: str = None, db=None, paper_trader: PaperTrader = None):
        self.mode = (mode or EXECUTION_MODE).lower()
        self._paper_trader = None
        self._mt5_executor = None
        self._db = db

        if self.mode == "paper":
            # Day 37 fix: reuse the caller's PaperTrader instance if given,
            # instead of always constructing a fresh (and separately
            # state-tracked) one.
            self._paper_trader = paper_trader or PaperTrader(db=self._db)
            log.info("[ExecutionRouter] Mode: PAPER (simulation)")

        elif self.mode == "mt5_demo":
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
        DecisionAgent.decide()-এর output নিয়ে সঠিক backend-এ trade পাঠায়।
        Caller-এর জন্য interface একই থাকে, mode যাই হোক।
        """
        if decision_result.get("decision") not in ("BUY", "SELL"):
            log.info(f"[ExecutionRouter] No action — decision={decision_result.get('decision')}")
            return None

        if self.mode == "paper":
            return self._execute_paper(decision_result)
        elif self.mode == "mt5_demo":
            return self._execute_mt5_demo(decision_result)

    def _execute_paper(self, decision_result: dict) -> dict | None:
        # PaperTrader.open_trade_from_signal() একটু আলাদা key-naming আশা করে
        # (final_action, symbol) — DecisionAgent output adapt করে দিচ্ছি
        adapted = self._adapt_decision_for_paper(decision_result)
        return self._paper_trader.open_trade_from_signal(adapted)

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

    def _adapt_decision_for_paper(self, decision_result: dict) -> dict:
        return {
            "final_action": decision_result.get("decision"),
            "symbol": decision_result.get("symbol", "EURUSD"),
            "entry": decision_result.get("entry"),
            "sl": decision_result.get("sl"),
            "tp": decision_result.get("tp"),
            "lot": decision_result.get("lot"),
            "confidence": decision_result.get("confidence"),
            "rr": decision_result.get("rr"),
            "timeframe": decision_result.get("timeframe", "15M"),
        }

    def shutdown(self) -> None:
        if self.mode == "mt5_demo" and hasattr(self, "_mt5_conn"):
            self._mt5_conn.disconnect()
        log.info("[ExecutionRouter] Shutdown complete")