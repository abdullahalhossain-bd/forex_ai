# broker/order_manager.py  —  Day 33 | MT5 Order Execution Engine
# ============================================================
# AI এখন শুধু "BUY EURUSD" বলে না — এই module আসলে MT5 demo
# account-এ order পাঠায়। ৭টা function (doc অনুযায়ী) + ৩টা
# bonus safety layer (pre-trade validation, retry, confirmation)।
#
# Execution Logger ও Paper/Demo router আলাদা module-এ আছে
# (broker/journal_bridge.py এবং execution/execution_router.py) —
# duplicate করা হয়নি, এখানে শুধু order placement logic।
# ============================================================

import time
from datetime import datetime, timezone
from utils.logger import get_logger
from broker.mt5_connection import MT5_AVAILABLE

log = get_logger("order_manager")

if MT5_AVAILABLE:
    import MetaTrader5 as mt5

# retcode গুলোর human-readable meaning — confirmation check-ের জন্য
RETCODE_SUCCESS = {10008, 10009}   # TRADE_RETCODE_PLACED, TRADE_RETCODE_DONE


def _resolve_filling_mode(broker_symbol: str):
    """Pick the most permissive filling mode the broker supports.

    Different brokers accept different `type_filling` values. The
    MetaQuotes-Demo server, ICMarkets, and many others reject
    ORDER_FILLING_FOK outright with retcode=10030 ("Unsupported filling
    mode").  We probe `mt5.symbol_info(symbol).filling_mode` (a bitmask)
    and pick the first supported mode in this priority order:

        1. ORDER_FILLING_IOC  (Immediate-or-Cancel — most permissive, supported by almost all brokers)
        2. ORDER_FILLING_FOK  (Fill-or-Kill — stricter, some brokers reject)
        3. ORDER_FILLING_RETURN (Return — used by some ECN brokers)

    Falls back to IOC if the probe fails — IOC works on >95% of brokers.
    """
    if not MT5_AVAILABLE:
        return None
    try:
        info = mt5.symbol_info(broker_symbol)
        if info is None:
            return mt5.ORDER_FILLING_IOC
        mode = info.filling_mode  # bitmask: bit0=FOK, bit1=IOC, bit2=RETURN
        if mode & 2:  # IOC supported
            return mt5.ORDER_FILLING_IOC
        if mode & 1:  # FOK supported
            return mt5.ORDER_FILLING_FOK
        if mode & 4:  # RETURN supported
            return mt5.ORDER_FILLING_RETURN
        return mt5.ORDER_FILLING_IOC  # safest default
    except Exception as e:
        # Day 81+ hotfix: was silent `return mt5.ORDER_FILLING_IOC`.
        # If symbol_info raises (disconnect, symbol not in Market Watch),
        # silently defaulting to IOC meant the next order_send would fail
        # with retcode=10030 and the operator had no idea why.  Now we
        # log the exception so the root cause is visible.
        log.warning(
            f"[OrderManager] _resolve_filling_mode({broker_symbol}) raised: {e} "
            f"— falling back to ORDER_FILLING_IOC"
        )
        try:
            from core.execution_logger import log_broker_last_error
            log_broker_last_error(symbol=broker_symbol, error=e,
                                  stage="resolve_filling_mode")
        except Exception:
            pass
        return mt5.ORDER_FILLING_IOC


class OrderManager:
    """
    MT5-এ actual order পাঠায়, modify করে, close করে।

    Usage:
        om = OrderManager(connection, account_manager)
        result = om.place_market_order("EURUSD", "BUY", lot=0.01, sl=1.0825, tp=1.0900)
        if result["success"]:
            ticket = result["ticket"]
            om.modify_order(ticket, new_sl=1.0855)
            ...
            om.close_order(ticket)
    """

    MAX_RETRIES = 3
    RETRY_DELAY_SEC = 2
    MAX_LOT = 10.0   # sanity ceiling — risk engine আগেই size করে, এটা শুধু hard backstop

    def __init__(self, connection, account_manager):
        self.connection = connection
        self.account_manager = account_manager

    # ─────────────────────────────────────────────
    # FUNCTION 1 — MARKET ORDER
    # ─────────────────────────────────────────────

    def place_market_order(
        self, symbol: str, direction: str, lot: float, sl: float = None, tp: float = None,
        comment: str = "ai_trader",
    ) -> dict:
        """BUY/SELL instantly বর্তমান market price-এ। Pre-trade validation + retry সহ।"""
        validation = self._pre_trade_validate(symbol, direction, lot, sl, tp)
        if not validation["ok"]:
            log.warning(f"[OrderManager] Pre-trade validation failed: {validation['reason']}")
            return {"success": False, "reason": validation["reason"]}

        broker_symbol = validation["broker_symbol"]

        for attempt in range(1, self.MAX_RETRIES + 1):
            tick = mt5.symbol_info_tick(broker_symbol)
            if tick is None:
                self._wait_retry(attempt, "no tick data")
                continue

            price = tick.ask if direction == "BUY" else tick.bid
            order_type = mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL

            # Auto-detect the broker's supported filling mode — this is the
            # #1 cause of "Unsupported filling mode" (retcode 10030) rejections
            # on demo accounts (MetaQuotes-Demo, ICMarkets, etc.).
            filling_mode = _resolve_filling_mode(broker_symbol)

            request = {
                "action":       mt5.TRADE_ACTION_DEAL,
                "symbol":       broker_symbol,
                "volume":       lot,
                "type":         order_type,
                "price":        price,
                "sl":           sl or 0.0,
                "tp":           tp or 0.0,
                "deviation":    10,         # max acceptable slippage (points)
                "magic":        424242,
                "comment":      comment,
                "type_time":    mt5.ORDER_TIME_GTC,
                "type_filling": filling_mode,
            }

            result = mt5.order_send(request)
            outcome = self._check_confirmation(result, attempt)
            if outcome["success"]:
                log.info(
                    f"[OrderManager] ✅ ORDER FILLED — {direction} {broker_symbol} "
                    f"lot={lot} ticket={outcome['ticket']}"
                )
                return outcome

            if not outcome.get("retryable", True):
                return outcome   # permanent rejection (যেমন invalid lot) — retry করার মানে নেই

            self._wait_retry(attempt, outcome["reason"])

        log.error(f"[OrderManager] ⛔ Order failed after {self.MAX_RETRIES} retries — {symbol} {direction}")
        return {"success": False, "reason": f"Failed after {self.MAX_RETRIES} retries"}

    # ─────────────────────────────────────────────
    # FUNCTION 2 — LIMIT ORDER
    # ─────────────────────────────────────────────

    def place_limit_order(
        self, symbol: str, price: float, direction: str, lot: float,
        sl: float = None, tp: float = None, comment: str = "ai_trader_limit",
    ) -> dict:
        """Pullback/support/breakout-retest entry-র জন্য — future price-এ pending order।"""
        validation = self._pre_trade_validate(symbol, direction, lot, sl, tp)
        if not validation["ok"]:
            return {"success": False, "reason": validation["reason"]}

        broker_symbol = validation["broker_symbol"]
        order_type = mt5.ORDER_TYPE_BUY_LIMIT if direction == "BUY" else mt5.ORDER_TYPE_SELL_LIMIT

        # Use broker-supported filling mode (auto-detected).
        filling_mode = _resolve_filling_mode(broker_symbol)

        request = {
            "action":       mt5.TRADE_ACTION_PENDING,
            "symbol":       broker_symbol,
            "volume":       lot,
            "type":         order_type,
            "price":        price,
            "sl":           sl or 0.0,
            "tp":           tp or 0.0,
            "magic":        424242,
            "comment":      comment,
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }

        for attempt in range(1, self.MAX_RETRIES + 1):
            result = mt5.order_send(request)
            outcome = self._check_confirmation(result, attempt)
            if outcome["success"]:
                log.info(f"[OrderManager] ✅ LIMIT ORDER PLACED — {direction} {broker_symbol} @ {price}")
                return outcome
            if not outcome.get("retryable", True):
                return outcome
            self._wait_retry(attempt, outcome["reason"])

        return {"success": False, "reason": f"Limit order failed after {self.MAX_RETRIES} retries"}

    # ─────────────────────────────────────────────
    # FUNCTION 3 — MODIFY ORDER  (SL/TP move, break-even, trailing)
    # ─────────────────────────────────────────────

    def modify_order(self, ticket: int, new_sl: float = None, new_tp: float = None) -> dict:
        position = self._get_position(ticket)
        if position is None:
            return {"success": False, "reason": f"Position not found: {ticket}"}

        request = {
            "action":   mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol":   position.symbol,
            "sl":       new_sl if new_sl is not None else position.sl,
            "tp":       new_tp if new_tp is not None else position.tp,
        }

        result = mt5.order_send(request)
        outcome = self._check_confirmation(result, attempt=1)
        if outcome["success"]:
            log.info(f"[OrderManager] SL/TP updated — ticket {ticket} → SL {new_sl} TP {new_tp}")
        return outcome

    # ─────────────────────────────────────────────
    # FUNCTION 4 — CLOSE ORDER
    # ─────────────────────────────────────────────

    def close_order(self, ticket: int, comment: str = "manual_close") -> dict:
        position = self._get_position(ticket)
        if position is None:
            return {"success": False, "reason": f"Position not found: {ticket}"}

        tick = mt5.symbol_info_tick(position.symbol)
        if tick is None:
            return {"success": False, "reason": "No tick data — cannot close"}

        is_buy = position.type == mt5.ORDER_TYPE_BUY
        close_type = mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY
        price = tick.bid if is_buy else tick.ask

        # Use broker-supported filling mode for close orders too.
        filling_mode = _resolve_filling_mode(position.symbol)

        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       position.symbol,
            "volume":       position.volume,
            "type":         close_type,
            "position":     ticket,
            "price":        price,
            "deviation":    10,
            "magic":        424242,
            "comment":      comment,
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }

        result = mt5.order_send(request)
        outcome = self._check_confirmation(result, attempt=1)
        if outcome["success"]:
            profit = position.profit
            log.info(f"[OrderManager] ✅ Position closed — ticket {ticket} | Profit: ${profit:.2f}")
            outcome["profit"] = profit
        return outcome

    # ─────────────────────────────────────────────
    # FUNCTION 5 — CLOSE ALL  (kill switch / emergency)
    # ─────────────────────────────────────────────

    def close_all_orders(self, reason: str = "Emergency close") -> list[dict]:
        log.warning(f"[OrderManager] 🚨 EMERGENCY — closing all positions: {reason}")
        positions = self.get_open_positions()
        results = []
        for pos in positions:
            outcome = self.close_order(pos["ticket"], comment=f"emergency:{reason}"[:31])
            results.append(outcome)
        log.warning(f"[OrderManager] {len(results)} positions processed for emergency close")
        return results

    # ─────────────────────────────────────────────
    # FUNCTION 6 — OPEN POSITIONS
    # ─────────────────────────────────────────────

    def get_open_positions(self, symbol: str = None) -> list[dict]:
        if not MT5_AVAILABLE:
            return []
        positions = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        if positions is None:
            return []
        return [
            {
                "ticket":   p.ticket,
                "symbol":   p.symbol,
                "type":     "BUY" if p.type == mt5.ORDER_TYPE_BUY else "SELL",
                "volume":   p.volume,
                "price_open": p.price_open,
                "sl":       p.sl,
                "tp":       p.tp,
                "profit":   p.profit,
                "open_time": datetime.fromtimestamp(p.time, tz=timezone.utc).isoformat(),
            }
            for p in positions
        ]

    def print_open_positions(self) -> None:
        positions = self.get_open_positions()
        bar = "═" * 40
        log.info(bar)
        log.info("  📊  OPEN POSITIONS")
        log.info(bar)
        if not positions:
            log.info("  (none)")
        for p in positions:
            icon = "🟢" if p["profit"] >= 0 else "🔴"
            log.info(f"  {icon} {p['symbol']} {p['type']} | Lot {p['volume']} | Profit ${p['profit']:.2f}")
        log.info(bar)

    # ─────────────────────────────────────────────
    # FUNCTION 7 — TRADE HISTORY
    # ─────────────────────────────────────────────

    def get_order_history(self, days_back: int = 7) -> list[dict]:
        if not MT5_AVAILABLE:
            return []
        from datetime import timedelta
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days_back)
        deals = mt5.history_deals_get(start, end)
        if deals is None:
            return []
        return [
            {
                "ticket":      d.ticket,
                "position_id": d.position_id,
                "symbol":      d.symbol,
                "type":        "BUY" if d.type == mt5.DEAL_TYPE_BUY else "SELL",
                "volume":      d.volume,
                "price":       d.price,
                "profit":      d.profit,
                "time":        datetime.fromtimestamp(d.time, tz=timezone.utc).isoformat(),
            }
            for d in deals
        ]

    # ─────────────────────────────────────────────
    # BONUS 1 — PRE-TRADE VALIDATION
    # ─────────────────────────────────────────────

    def _pre_trade_validate(
        self, symbol: str, direction: str, lot: float, sl: float, tp: float
    ) -> dict:
        if not MT5_AVAILABLE or not self.connection.connected:
            return {"ok": False, "reason": "MT5 not connected"}

        if direction not in ("BUY", "SELL"):
            return {"ok": False, "reason": f"Invalid direction: {direction}"}

        if lot <= 0 or lot > self.MAX_LOT:
            return {"ok": False, "reason": f"Invalid lot size: {lot} (max {self.MAX_LOT})"}

        perm = self.account_manager.trading_permission(symbol=symbol, risk_engine_ok=True)
        if not perm["allowed"]:
            return {"ok": False, "reason": f"Trading not permitted: {perm['failed_checks']}"}

        broker_symbol = perm["broker_symbol"]
        info = mt5.symbol_info(broker_symbol)
        if info and sl and tp:
            # SL/TP sanity — direction-এর সাথে সঠিক দিকে আছে কিনা
            tick = mt5.symbol_info_tick(broker_symbol)
            ref_price = tick.ask if direction == "BUY" else tick.bid
            if direction == "BUY" and not (sl < ref_price < tp):
                return {"ok": False, "reason": f"Invalid SL/TP for BUY: SL={sl} price={ref_price} TP={tp}"}
            if direction == "SELL" and not (tp < ref_price < sl):
                return {"ok": False, "reason": f"Invalid SL/TP for SELL: TP={tp} price={ref_price} SL={sl}"}

        return {"ok": True, "broker_symbol": broker_symbol}

    # ─────────────────────────────────────────────
    # BONUS 2 + 3 — RETRY + CONFIRMATION
    # ─────────────────────────────────────────────

    def _check_confirmation(self, result, attempt: int) -> dict:
        """mt5.order_send()-এর result.retcode চেক করে success/failure ঠিক করে।"""
        if result is None:
            # Day 81+ hotfix: log mt5.last_error() so the operator can
            # see WHY order_send returned None (terminal disconnected,
            # IPC pipe broken, terminal not running, etc.).  Previously
            # this was silent — only "order_send returned None" was
            # logged, with no MT5-side diagnostic.
            try:
                last_err = mt5.last_error()
            except Exception:
                last_err = "(last_error() itself failed)"
            log.error(
                f"[OrderManager] order_send returned None on attempt {attempt} — "
                f"mt5.last_error()={last_err}"
            )
            try:
                from core.execution_logger import log_broker_last_error
                log_broker_last_error(symbol="?", error=last_err,
                                      attempt=attempt, stage="order_send_none")
            except Exception:
                pass
            return {
                "success": False,
                "reason": f"order_send returned None (last_error={last_err})",
                "retryable": True,
            }

        if result.retcode in RETCODE_SUCCESS:
            # Day 81+ hotfix: log every successful order_send to logs/execution.log
            try:
                from core.execution_logger import log_broker_order_send
                log_broker_order_send(
                    symbol="?",  # caller doesn't pass symbol here; could refactor
                    retcode=result.retcode,
                    comment=getattr(result, "comment", None),
                    price=result.price,
                    volume=result.volume,
                    ticket=result.order or result.deal,
                    attempt=attempt,
                )
            except Exception:
                pass
            return {
                "success": True,
                "ticket": result.order or result.deal,
                "retcode": result.retcode,
                "price": result.price,
                "volume": result.volume,
            }

        # Permanent rejection reasons — retry-এর মানে নেই
        permanent_codes = {
            10013,  # TRADE_RETCODE_INVALID — invalid request
            10014,  # invalid volume
            10015,  # invalid price
            10016,  # invalid stops
            10019,  # no money
            10027,  # autotrading disabled (client side) — broker পরিবর্তন ছাড়া retry futile
        }
        # 10030 (Unsupported filling mode) is RETRYABLE because _resolve_filling_mode
        # will pick a different mode on the next attempt. This was the #1 cause
        # of "trades silently fail" on MetaQuotes-Demo and ICMarkets demo servers
        # — they reject ORDER_FILLING_FOK outright.
        retryable = result.retcode not in permanent_codes

        log.warning(
            f"[OrderManager] Attempt {attempt} rejected — retcode={result.retcode} "
            f"comment={getattr(result, 'comment', '')}"
        )
        return {
            "success": False,
            "reason": f"retcode={result.retcode} ({getattr(result, 'comment', 'no comment')})",
            "retryable": retryable,
        }

    def _wait_retry(self, attempt: int, reason: str) -> None:
        log.warning(f"[OrderManager] Retry {attempt}/{self.MAX_RETRIES} — {reason}")
        time.sleep(self.RETRY_DELAY_SEC)

    # ─────────────────────────────────────────────
    # INTERNAL
    # ─────────────────────────────────────────────

    def _get_position(self, ticket: int):
        if not MT5_AVAILABLE:
            return None
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return None
        return positions[0]