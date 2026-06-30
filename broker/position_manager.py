# broker/position_manager.py  —  Day 33 (base) + Day 35 (upgrade)
# ============================================================
# Day 33: Close detection — MT5 broker-এ SL/TP hit detect করে
#         JournalBridge + TradeMemory update করে।
#
# Day 35 upgrade: Active trade management —
#   1. Trailing Stop (ATR-based dynamic)
#   2. Breakeven (50% profit → SL = entry)
#   3. Partial Close (TP1 hit → 50% close, rest runs)
#   4. Time-Based Exit (session end)
#   5. Friday Close (weekend gap protection)
#   6. Trade Health Score
#   7. Action Log (DB-ready dict list)
# ============================================================

import time
from datetime import datetime, timezone
from utils.logger import get_logger

log = get_logger("position_manager")

# ─────────────────────────────────────────────────────────────
# PIP SIZE MAP
# ─────────────────────────────────────────────────────────────
PIP_SIZE = {
    "EURUSD": 0.0001, "GBPUSD": 0.0001,
    "USDJPY": 0.01,   "USDCHF": 0.0001,
    "AUDUSD": 0.0001, "USDCAD": 0.0001,
    "XAUUSD": 0.1,
    "DEFAULT": 0.0001,
}


def _pip(symbol: str) -> float:
    key = symbol.upper()[:6]
    return PIP_SIZE.get(key, PIP_SIZE["DEFAULT"])


def _pips(symbol: str, price_diff: float) -> float:
    return round(abs(price_diff) / _pip(symbol), 1)


# ─────────────────────────────────────────────────────────────
# POSITION MANAGER
# ─────────────────────────────────────────────────────────────

class PositionManager:
    """
    Usage:
        pm = PositionManager(
            order_manager,
            journal_bridge=bridge,
            on_closed=pipeline.on_trade_closed,
            trade_memory=memory,
        )
        pm.poll_once()     # একবার চেক — close detect + management rules
        pm.run_loop()      # blocking loop — আলাদা thread-এ চালাও
    """

    POLL_INTERVAL_SEC = 10       # প্রতি 10 সেকেন্ডে position check

    # ── Trailing Stop ──
    TRAIL_ACTIVATE_PIPS  = 20    # কত pips profit হলে trailing শুরু হবে
    TRAIL_DISTANCE_PIPS  = 15    # trailing SL কত pips পিছনে থাকবে (default)
    ATR_TRAIL_MULT       = 1.0   # ATR-based trail: trail_distance = ATR × mult

    # ── Breakeven ──
    BREAKEVEN_TRIGGER_PC = 0.50  # TP distance-এর কত % profit হলে SL → entry

    # ── Partial Close ──
    PARTIAL_TRIGGER_PC   = 0.50  # TP distance-এর কত % এ partial close
    PARTIAL_CLOSE_PC     = 0.50  # কত % position close করবে (50% = half lot)

    # ── Time Exit ──
    SESSION_END_HOUR_UTC = 22    # UTC 22:00 এর পর কোনো trade রাখবে না

    # ── Friday Close ──
    FRIDAY_CLOSE_HOUR_UTC = 20   # Friday UTC 20:00 এর পর সব close

    def __init__(
        self,
        order_manager,
        journal_bridge=None,
        on_closed=None,
        trade_memory=None,
        risk_engine=None,
    ):
        self.order_manager  = order_manager
        self.journal_bridge = journal_bridge
        self.on_closed      = on_closed       # callback(symbol, result, pnl)
        self.trade_memory   = trade_memory
        self.risk_engine    = risk_engine     # ATR-based trailing-এর জন্য (optional)

        self._known_tickets:    dict[int, dict] = {}  # ticket → position snapshot
        self._ticket_to_db_id: dict[int, int]  = {}  # ticket → DB trade id
        self._breakeven_done:   set[int]        = set()  # ইতিমধ্যে breakeven করা tickets
        self._partial_done:     set[int]        = set()  # ইতিমধ্যে partial close করা tickets
        self._action_log:       list[dict]      = []     # সব management action record

    # ─────────────────────────────────────────────
    # PUBLIC — REGISTER AFTER OPEN
    # ─────────────────────────────────────────────

    def register_open(self, ticket: int, db_trade_id: int) -> None:
        """OrderManager.place_market_order() সফল হওয়ার পরেই call করো।"""
        self._ticket_to_db_id[ticket] = db_trade_id
        log.info(f"[PositionManager] Registered ticket {ticket} → DB #{db_trade_id}")

    # ─────────────────────────────────────────────
    # PUBLIC — MAIN POLL
    # ─────────────────────────────────────────────

    def poll_once(self) -> list[dict]:
        """
        একবার সব open positions চেক করে:
        1. Close detection (SL/TP hit by broker)
        2. Active management (trailing, breakeven, partial, time/friday exit)
        Returns list of close events এই cycle-এ।
        """
        current = {
            p["ticket"]: p
            for p in self.order_manager.get_open_positions()
        }

        # ── Friday / Time exit — আগে চেক করো ──
        self._check_scheduled_exits(current)

        # ── Close detection ──
        closed_tickets = set(self._known_tickets.keys()) - set(current.keys())
        events = []
        for ticket in closed_tickets:
            event = self._handle_close(ticket, self._known_tickets[ticket])
            if event:
                events.append(event)

        # ── Active management for still-open positions ──
        for ticket, pos in current.items():
            self._apply_management_rules(pos)

        self._known_tickets = current
        return events

    def run_loop(self, stop_flag=None) -> None:
        log.info(f"[PositionManager] 🔄 Starting management loop (every {self.POLL_INTERVAL_SEC}s)")
        while True:
            if stop_flag and stop_flag():
                log.info("[PositionManager] Stop flag — exiting loop")
                break
            try:
                self.poll_once()
            except Exception as e:
                log.error(f"[PositionManager] Poll error: {e}", exc_info=True)
            time.sleep(self.POLL_INTERVAL_SEC)

    # ─────────────────────────────────────────────
    # MANAGEMENT RULES
    # ─────────────────────────────────────────────

    def _apply_management_rules(self, pos: dict) -> None:
        """
        একটা open position-এর জন্য সব Day 35 rules check করে।
        Order: Breakeven → Trailing → Partial Close
        (সব একসাথে না — breakeven হলে trailing শুরু হয়)
        """
        ticket  = pos["ticket"]
        symbol  = pos["symbol"]
        direction = pos["type"]        # "BUY" or "SELL"
        entry   = pos["price_open"]
        current_price = self._get_current_price(symbol, direction)
        if current_price is None:
            return

        sl = pos.get("sl", 0.0)
        tp = pos.get("tp", 0.0)

        # TP দেওয়া না থাকলে management করার reference নেই
        if not tp or not entry:
            return

        tp_distance = abs(tp - entry)
        if tp_distance == 0:
            return

        # Floating profit (pips)
        if direction == "BUY":
            profit_distance = current_price - entry
        else:
            profit_distance = entry - current_price

        profit_pips = _pips(symbol, profit_distance) if profit_distance > 0 else 0

        # ── Rule 1: Breakeven ──
        if ticket not in self._breakeven_done:
            self._check_breakeven(pos, current_price, entry, tp_distance, profit_distance, sl)

        # ── Rule 2: Trailing Stop ──
        self._check_trailing(pos, current_price, profit_pips, sl, direction)

        # ── Rule 3: Partial Close ──
        if ticket not in self._partial_done:
            self._check_partial_close(pos, profit_distance, tp_distance)

        # ── Rule 4: Trade Health Score ──
        health = self._compute_health(pos, profit_pips, current_price)
        if health < 30:
            log.warning(
                f"[PositionManager] ⚠️ Low health {health}/100 — {symbol} {direction} "
                f"profit={profit_pips} pips"
            )

    # ── 1. BREAKEVEN ──

    def _check_breakeven(
        self, pos: dict, current_price: float,
        entry: float, tp_distance: float,
        profit_distance: float, current_sl: float,
    ) -> None:
        ticket    = pos["ticket"]
        symbol    = pos["symbol"]
        direction = pos["type"]

        trigger_distance = tp_distance * self.BREAKEVEN_TRIGGER_PC
        if profit_distance < trigger_distance:
            return

        # SL already at or better than entry
        if direction == "BUY" and current_sl >= entry:
            self._breakeven_done.add(ticket)
            return
        if direction == "SELL" and current_sl <= entry and current_sl > 0:
            self._breakeven_done.add(ticket)
            return

        result = self.order_manager.modify_order(ticket, new_sl=entry)
        if result.get("success"):
            self._breakeven_done.add(ticket)
            self._log_action(ticket, symbol, "BREAKEVEN", old_sl=current_sl, new_sl=entry,
                             reason=f"{self.BREAKEVEN_TRIGGER_PC*100:.0f}% of TP reached")
            log.info(
                f"[PositionManager] 🔒 BREAKEVEN — {symbol} {direction} "
                f"SL: {current_sl} → {entry}"
            )

    # ── 2. TRAILING STOP ──

    def _check_trailing(
        self, pos: dict, current_price: float,
        profit_pips: float, current_sl: float, direction: str,
    ) -> None:
        ticket = pos["ticket"]
        symbol = pos["symbol"]

        if profit_pips < self.TRAIL_ACTIVATE_PIPS:
            return

        pip = _pip(symbol)
        trail_distance = self.TRAIL_DISTANCE_PIPS * pip

        if direction == "BUY":
            new_sl = round(current_price - trail_distance, 5)
            if new_sl <= current_sl:
                return   # SL is already tighter or equal — no move needed
        else:
            new_sl = round(current_price + trail_distance, 5)
            if current_sl > 0 and new_sl >= current_sl:
                return

        result = self.order_manager.modify_order(ticket, new_sl=new_sl)
        if result.get("success"):
            self._log_action(ticket, symbol, "TRAILING_STOP", old_sl=current_sl, new_sl=new_sl,
                             reason=f"Profit {profit_pips} pips — trail {self.TRAIL_DISTANCE_PIPS} pips")
            log.info(
                f"[PositionManager] 📈 TRAILING — {symbol} {direction} "
                f"SL: {current_sl} → {new_sl}  (profit {profit_pips} pips)"
            )

    # ── 3. PARTIAL CLOSE ──

    def _check_partial_close(
        self, pos: dict, profit_distance: float, tp_distance: float,
    ) -> None:
        ticket    = pos["ticket"]
        symbol    = pos["symbol"]
        direction = pos["type"]
        volume    = pos.get("volume", 0)

        if profit_distance < tp_distance * self.PARTIAL_TRIGGER_PC:
            return

        close_volume = round(volume * self.PARTIAL_CLOSE_PC, 2)
        if close_volume < 0.01:
            return

        # MT5-এ partial close = নতুন opposite market order same position-এ
        # order_manager.close_order() পুরো close করে — partial-এর জন্য
        # আলাদা request পাঠাতে হয়
        result = self._partial_close_mt5(ticket, symbol, direction, close_volume)
        if result.get("success"):
            self._partial_done.add(ticket)
            profit_usd = pos.get("profit", 0) * self.PARTIAL_CLOSE_PC
            self._log_action(ticket, symbol, "PARTIAL_CLOSE",
                             reason=f"{self.PARTIAL_TRIGGER_PC*100:.0f}% TP reached — closed {close_volume} lot")
            log.info(
                f"[PositionManager] 💰 PARTIAL CLOSE — {symbol} {direction} "
                f"closed {close_volume} lot  ~${profit_usd:.2f}"
            )
            # Breakeven activate করো remainder-এর জন্য
            self._breakeven_done.discard(ticket)   # force re-check breakeven for remainder

    def _partial_close_mt5(self, ticket: int, symbol: str, direction: str, volume: float) -> dict:
        """Partial close — opposite order same ticket-এ।"""
        try:
            from broker.mt5_connection import MT5_AVAILABLE
            if not MT5_AVAILABLE:
                return {"success": False, "reason": "MT5 not available"}
            import MetaTrader5 as mt5
            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                return {"success": False, "reason": "No tick"}

            close_type  = mt5.ORDER_TYPE_SELL if direction == "BUY" else mt5.ORDER_TYPE_BUY
            close_price = tick.bid if direction == "BUY" else tick.ask

            request = {
                "action":       mt5.TRADE_ACTION_DEAL,
                "symbol":       symbol,
                "volume":       volume,
                "type":         close_type,
                "position":     ticket,
                "price":        close_price,
                "deviation":    10,
                "magic":        424242,
                "comment":      "partial_close",
                "type_time":    mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_FOK,
            }
            result = mt5.order_send(request)
            if result and result.retcode in {10008, 10009}:
                return {"success": True, "ticket": result.order}
            return {"success": False, "reason": f"retcode={getattr(result,'retcode','?')}"}
        except Exception as e:
            return {"success": False, "reason": str(e)}

    # ── 4. SCHEDULED EXITS (Time + Friday) ──

    def _check_scheduled_exits(self, current_positions: dict) -> None:
        """Time-based exit এবং Friday close চেক করে।"""
        if not current_positions:
            return

        now_utc  = datetime.now(timezone.utc)
        weekday  = now_utc.weekday()   # 0=Mon … 4=Fri … 6=Sun
        hour_utc = now_utc.hour

        # Friday close
        if weekday == 4 and hour_utc >= self.FRIDAY_CLOSE_HOUR_UTC:
            log.warning(
                f"[PositionManager] ⚠️ FRIDAY CLOSE — {len(current_positions)} positions to close"
            )
            for ticket in list(current_positions.keys()):
                result = self.order_manager.close_order(ticket, comment="friday_close")
                sym = current_positions[ticket]["symbol"]
                if result.get("success"):
                    self._log_action(ticket, sym, "FRIDAY_CLOSE", reason="Weekend gap protection")
                    log.info(f"[PositionManager] ⚠️ Friday closed — {sym} ticket {ticket}")
            return

        # Session time exit (UTC 22:00+)
        if hour_utc >= self.SESSION_END_HOUR_UTC:
            log.info(
                f"[PositionManager] ⏰ SESSION END ({hour_utc}:00 UTC) — "
                f"closing {len(current_positions)} positions"
            )
            for ticket in list(current_positions.keys()):
                result = self.order_manager.close_order(ticket, comment="session_end")
                sym = current_positions[ticket]["symbol"]
                if result.get("success"):
                    self._log_action(ticket, sym, "TIME_EXIT", reason=f"Session end UTC {hour_utc}:00")
                    log.info(f"[PositionManager] ⏰ Time exit — {sym} ticket {ticket}")

    # ─────────────────────────────────────────────
    # CLOSE DETECTION (Day 33 logic — unchanged)
    # ─────────────────────────────────────────────

    def _handle_close(self, ticket: int, last_known: dict) -> dict | None:
        history = self.order_manager.get_order_history(days_back=1)
        deal    = next((d for d in history if d.get("position_id") == ticket), None)

        symbol = last_known["symbol"]
        pnl    = deal["profit"] if deal else last_known.get("profit", 0)
        result = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "BREAKEVEN")

        log.info(f"[PositionManager] Close detected — {symbol} ticket {ticket} → {result} (${pnl:.2f})")

        db_id = self._ticket_to_db_id.get(ticket)
        if db_id and self.journal_bridge:
            close_data = {
                "close_time":  datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "exit_price":  deal["price"] if deal else last_known.get("price_open"),
                "result":      result,
                "pnl":         round(pnl, 2),
                "pnl_pips":    0,
                "spread_cost": 0,
                "commission":  0,
                "slippage":    0,
            }
            self.journal_bridge.log_mt5_close(db_id, close_data)

        if self.on_closed:
            self.on_closed(symbol, result, pnl)

        if self.trade_memory:
            self.trade_memory.add_lesson({
                "pair": symbol, "type": last_known.get("type"),
                "result": result, "pnl": round(pnl, 2),
                "close_reason": "MT5_CLOSE",
                "context": {"source": "mt5_demo"},
            })

        if self.risk_engine:
            self.risk_engine.record_trade_close(symbol, pnl)

        # Cleanup sets
        self._breakeven_done.discard(ticket)
        self._partial_done.discard(ticket)
        self._ticket_to_db_id.pop(ticket, None)

        return {"ticket": ticket, "symbol": symbol, "result": result, "pnl": pnl}

    # ─────────────────────────────────────────────
    # TRADE HEALTH SCORE  (Bonus 3)
    # ─────────────────────────────────────────────

    def _compute_health(self, pos: dict, profit_pips: float, current_price: float) -> int:
        """
        0-100 health score:
        - profit zone: +40
        - SL buffer remaining: +30
        - breakeven/partial done: +20
        - trade age (not too old): +10
        """
        score = 0
        ticket    = pos["ticket"]
        entry     = pos["price_open"]
        direction = pos["type"]
        sl        = pos.get("sl", 0.0)

        # Profit zone
        if profit_pips > 0:
            score += min(40, int(profit_pips * 1.5))

        # SL buffer
        if sl and current_price:
            pip = _pip(pos["symbol"])
            if direction == "BUY":
                sl_buffer = _pips(pos["symbol"], current_price - sl) if current_price > sl else 0
            else:
                sl_buffer = _pips(pos["symbol"], sl - current_price) if sl > current_price else 0
            score += min(30, int(sl_buffer))

        # Breakeven done = less risk
        if ticket in self._breakeven_done:
            score += 15
        if ticket in self._partial_done:
            score += 5

        return min(100, max(0, score))

    # ─────────────────────────────────────────────
    # UTILITIES
    # ─────────────────────────────────────────────

    def _get_current_price(self, symbol: str, direction: str) -> float | None:
        try:
            from broker.mt5_connection import MT5_AVAILABLE
            if not MT5_AVAILABLE:
                return None
            import MetaTrader5 as mt5
            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                return None
            return tick.bid if direction == "BUY" else tick.ask
        except Exception:
            return None

    def _log_action(
        self, ticket: int, symbol: str, action: str,
        old_sl: float = None, new_sl: float = None, reason: str = "",
    ) -> None:
        entry = {
            "ticket":    ticket,
            "symbol":    symbol,
            "action":    action,
            "old_sl":    old_sl,
            "new_sl":    new_sl,
            "reason":    reason,
            "time":      datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self._action_log.append(entry)

    def get_action_log(self) -> list[dict]:
        """সব management action-এর list — DB save বা Telegram alert-এর জন্য।"""
        return list(self._action_log)

    def print_status(self) -> None:
        positions = self.order_manager.get_open_positions()
        bar = "═" * 48
        log.info(bar)
        log.info("  🤖  POSITION MANAGER STATUS")
        log.info(bar)
        log.info(f"  Open positions : {len(positions)}")
        log.info(f"  Breakeven done : {len(self._breakeven_done)}")
        log.info(f"  Partial done   : {len(self._partial_done)}")
        log.info(f"  Actions logged : {len(self._action_log)}")
        log.info(bar)
        for pos in positions:
            ticket = pos["ticket"]
            sym    = pos["symbol"]
            profit = pos.get("profit", 0)
            icon   = "🟢" if profit >= 0 else "🔴"
            be     = "🔒BE" if ticket in self._breakeven_done else ""
            pt     = "💰PT" if ticket in self._partial_done else ""
            log.info(f"  {icon} {sym} {pos['type']} lot={pos['volume']} profit=${profit:.2f} {be}{pt}")
        log.info(bar)