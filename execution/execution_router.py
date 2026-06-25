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

import threading

from utils.logger import get_logger
from config import validate_mt5_config

log = get_logger("execution_router")

# Lazy import — execution_logger lives in core/, and we don't want a
# hard dependency at module-load time (in case core/ hasn't been
# initialized yet during boot).
def _log_event(event: str, **fields):
    try:
        from core.execution_logger import log_event
        log_event(event, **fields)
    except Exception:
        pass


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
        from config import ABSOLUTE_SAFETY, TEST_MODE
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
        # Day 81+ hotfix: FAIL-CLOSED instead of fail-open.
        # The previous code returned (True, "safety check unavailable")
        # which silently bypassed broker-disconnect / spread-explosion /
        # market-closed checks whenever the live_feed itself raised.  This
        # is unsafe — if the safety checker is broken, we should NOT
        # place trades until it's fixed.
        log.error(
            f"[ABSOLUTE_SAFETY] check itself failed — FAIL-CLOSED: {e}",
            exc_info=True,
        )
        return False, f"safety check unavailable: {e}"


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
        self._simulation_mode = False

        # ── Day 81+ SIMULATION_MODE ─────────────────────────────
        # If config.SIMULATION_MODE=True, use the SimulatedExecutor
        # instead of real MT5.  Lets the operator verify the full
        # execution chain end-to-end without a live terminal.
        try:
            from config import SIMULATION_MODE
            self._simulation_mode = bool(SIMULATION_MODE)
        except Exception:
            pass

        if self._simulation_mode:
            from execution.simulated_executor import SimulatedExecutor
            self._order_manager  = SimulatedExecutor(db=self._db)
            self._journal_bridge = None  # no DB journal in simulation
            self._mt5_conn       = None
            self._account_manager = None
            self._health_monitor  = None
            log.info("[ExecutionRouter] Mode: SIMULATION (no broker contact — dry run)")
            return

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
                    "is running. EXECUTION_MODE=mt5_demo requires MT5 terminal. "
                    "Tip: set SIMULATION_MODE=true in .env to verify the order-flow "
                    "chain without a live terminal."
                )
            self._account_manager = AccountManager(self._mt5_conn)
            self._health_monitor = HealthMonitor(
                self._mt5_conn,
                on_disconnect=lambda msg: log.warning(f"[Router] {msg}"),
                on_reconnect=lambda msg: log.info(f"[Router] {msg}"),
                on_fatal=lambda msg: log.error(f"[Router] {msg}"),
            )
            # Day 81+ hotfix: START the HealthMonitor background thread.
            # Previously the monitor was created but never started, so
            # disconnects after the initial connect were never detected
            # and reconnect logic was dead code.
            try:
                self._health_thread = threading.Thread(
                    target=self._health_monitor.run_loop,
                    name="mt5_health_monitor",
                    daemon=True,
                )
                self._health_thread.start()
                log.info("[ExecutionRouter] HealthMonitor thread started")
            except Exception as e:
                log.warning(f"[ExecutionRouter] Could not start HealthMonitor: {e}")
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

        Day 81+ hotfix: HARD permission + lot cap gate at the very top.
        Even if upstream trader.py somehow calls execute() with a rejected
        decision (e.g. a future code path, a dashboard override, or a bug
        in TradePermission), this gate catches it here before any broker
        contact.  This is the LAST line of defense.
        """
        # ── HARD GATE 1: decision must be BUY/SELL ──
        if decision_result.get("decision") not in ("BUY", "SELL"):
            log.info(f"[ExecutionRouter] No action — decision={decision_result.get('decision')}")
            return None

        # ── HARD GATE 2: explicit permission flag ──
        # trader.py sets "trade_allowed" in the result dict from perm_out["allowed"].
        # If this is False, the trade was rejected by TradePermission — DO NOT execute.
        # This catches the bug where execution proceeds despite permission rejection.
        if "trade_allowed" in decision_result and not decision_result["trade_allowed"]:
            log.error(
                f"[ExecutionRouter] ⛔ HARD BLOCK — trade_allowed=False for "
                f"{decision_result.get('symbol')} {decision_result.get('decision')}. "
                f"This indicates a permission bypass bug upstream. Refusing to execute."
            )
            _log_event("router.execute.fail",
                       symbol=decision_result.get("symbol", "?"),
                       reason="hard_gate: trade_allowed=False",
                       stage="permission_bypass_blocked")
            return None

        # ── HARD GATE 3: lot cap ──
        lot = decision_result.get("lot", 0.01)
        try:
            from config import MAX_LOT
        except Exception:
            MAX_LOT = 0.20
        if lot > MAX_LOT:
            log.warning(
                f"[ExecutionRouter] ⛔ LOT CAP — lot={lot} exceeds MAX_LOT={MAX_LOT}. "
                f"Capping to {MAX_LOT}. (symbol={decision_result.get('symbol')})"
            )
            decision_result = {**decision_result, "lot": MAX_LOT}
            _log_event("router.execute.lot_capped",
                       symbol=decision_result.get("symbol", "?"),
                       original_lot=lot, capped_lot=MAX_LOT)

        # ── HARD GATE 4: lot must be positive ──
        if lot <= 0:
            log.error(
                f"[ExecutionRouter] ⛔ INVALID LOT — lot={lot}. Refusing to execute."
            )
            _log_event("router.execute.fail",
                       symbol=decision_result.get("symbol", "?"),
                       reason=f"invalid lot={lot}",
                       stage="lot_validation")
            return None

        return self._execute_mt5_demo(decision_result)

    def _execute_mt5_demo(self, decision_result: dict) -> dict | None:
        """
        Day 38 — real MT5 demo order placement।
        OrderManager দিয়ে actual mt5.order_send() কল করে, JournalBridge
        দিয়ে DB-তে save করে — PaperTrader-এর মতো same `trades` table-এ,
        যাতে learning memory একসাথে থাকে।

        Day 81+ hotfix: every step is now wrapped in try/except and
        logged to logs/execution.log via core.execution_logger.  If
        the broker fill succeeds but the DB journal write fails, the
        position is logged as an ORPHAN so the operator can reconcile.
        """
        symbol    = decision_result.get("symbol", "EURUSD")
        direction = decision_result.get("decision")
        lot       = decision_result.get("lot", 0.01)
        sl        = decision_result.get("sl")
        tp        = decision_result.get("tp")

        _log_event("router.execute.start", symbol=symbol, decision=direction,
                   lot=lot, sl=sl, tp=tp, simulation=self._simulation_mode)

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
            _log_event("router.execute.fail", symbol=symbol, reason=reason,
                       stage="absolute_safety")
            return None

        # In SIMULATION_MODE, skip the broker-side trading_permission
        # check (there is no broker).  Use the requested symbol directly.
        if self._simulation_mode:
            broker_symbol = symbol
        else:
            perm = self._account_manager.trading_permission(
                symbol=symbol,
                risk_engine_ok=True,   # risk engine আগেই pass করেছে ধরে নেওয়া হলো
            )
            if not perm["allowed"]:
                log.warning(
                    f"[ExecutionRouter] MT5 demo — trade blocked: {perm['failed_checks']}"
                )
                _log_event("router.execute.fail", symbol=symbol,
                           reason=f"trading_permission: {perm['failed_checks']}",
                           stage="trading_permission")
                return None
            broker_symbol = perm["broker_symbol"]

        # ── Day 81+ hotfix: wrap order placement in try/except ──
        # If mt5.order_send() raises (rather than returning a result
        # with a bad retcode), the exception used to propagate all the
        # way up to main.py's "Symbol cycle failed" handler — leaving
        # no diagnostic and no DB record.  Now we catch, log, and
        # publish a broker.failure event.
        try:
            order_result = self._order_manager.place_market_order(
                symbol=broker_symbol,
                direction=direction,
                lot=lot,
                sl=sl,
                tp=tp,
                comment="ai_trader_demo" if not self._simulation_mode else "ai_trader_sim",
            )
        except Exception as e:
            log.error(
                f"[ExecutionRouter] place_market_order raised: {e}",
                exc_info=True,
            )
            _log_event("router.execute.fail", symbol=symbol,
                       reason=f"place_market_order raised: {e}",
                       stage="order_send")
            return None

        if not order_result.get("success"):
            log.error(
                f"[ExecutionRouter] MT5 demo — order failed: {order_result.get('reason')}"
            )
            _log_event("router.execute.fail", symbol=symbol,
                       reason=order_result.get('reason', 'unknown'),
                       stage="order_result",
                       retcode=order_result.get('retcode'))
            return None

        filled_entry = order_result.get("price", decision_result.get("entry"))
        ticket       = order_result.get("ticket")

        # ── In SIMULATION_MODE, skip DB journal (no real trade to record) ──
        if self._simulation_mode or self._journal_bridge is None:
            log.info(
                f"[ExecutionRouter] ✅ SIMULATED order FILLED — {direction} {broker_symbol} "
                f"lot={lot} ticket={ticket} (no DB record — simulation)"
            )
            _log_event("router.execute.success", symbol=symbol, ticket=ticket,
                       price=filled_entry, lot=lot, simulation=True)
            return {
                "id":            None,
                "status":        "SIMULATED",
                "broker_symbol": broker_symbol,
                "ticket":        ticket,
                "entry":         filled_entry,
                "sl":            sl,
                "tp":            tp,
                "lot":           lot,
                "type":          direction,
                "pair":          broker_symbol,
            }

        # ── Day 81+ hotfix: wrap DB journal in try/except ──────
        # If save_trade_open raises AFTER the broker has filled the
        # order, the broker has a position but the bot has no record.
        # Log as ORPHAN so the operator can reconcile manually.
        trade_id = None
        journal_failed = False
        try:
            trade_id = self._journal_bridge.log_mt5_open(
                decision_result   = decision_result,
                broker_symbol     = broker_symbol,
                filled_entry      = filled_entry,
                mt5_order_ticket  = ticket,
            )
        except Exception as e:
            journal_failed = True
            log.error(
                f"[ExecutionRouter] ⚠️  ORPHAN POSITION — broker filled {ticket} "
                f"({broker_symbol} {direction} lot={lot}) but DB journal failed: {e}",
                exc_info=True,
            )
            _log_event("orphan.position", symbol=symbol, ticket=ticket,
                       reason=f"journal failed after broker fill: {e}",
                       broker_symbol=broker_symbol, direction=direction, lot=lot)
            # Do NOT return None — the broker has the position, so we
            # return a success dict with trade_id=None so the caller
            # (trader.py) can still update its in-memory state.

        log.info(
            f"[ExecutionRouter] ✅ MT5 demo order FILLED — {direction} {broker_symbol} "
            f"lot={lot} ticket={ticket} → DB #{trade_id}"
            + ("  ⚠️  ORPHAN (DB write failed)" if journal_failed else "")
        )
        _log_event("router.execute.success", symbol=symbol, ticket=ticket,
                   price=filled_entry, lot=lot, trade_id=trade_id,
                   orphan=journal_failed)

        return {
            "id":            trade_id,
            "status":        "FILLED" if not journal_failed else "FILLED_ORPHAN",
            "broker_symbol": broker_symbol,
            "ticket":        ticket,
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