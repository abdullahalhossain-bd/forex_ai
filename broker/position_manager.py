# broker/position_manager.py  —  Day 33 | Position Tracking + Close Detection
# ============================================================
# OrderManager order পাঠায়, কিন্তু কেউ একজনকে monitor করতে হবে কখন
# position close হলো (SL hit, TP hit, বা manual close) — MT5 নিজে
# push notification পাঠায় না, polling করতে হয়।
#
# এই module প্রতি cycle-এ:
#   1. বর্তমান open positions নেয় (OrderManager.get_open_positions)
#   2. আগের cycle-এর সাথে diff করে — কোনটা আর নেই = close হয়েছে
#   3. সেই position-এর actual close deal history থেকে P&L নেয়
#   4. SignalPipeline.on_trade_closed() + JournalBridge + TradeMemory
#      কল করে — সব downstream module কে জানায়
#
# এটা PaperTrader.update_price()-এর MT5-demo সংস্করণ — paper mode-এ
# candle-by-candle SL/TP simulate হয়, MT5 mode-এ broker নিজে SL/TP
# execute করে, আমরা শুধু ফলাফল detect করি।
# ============================================================

import time
from utils.logger import get_logger

log = get_logger("position_manager")


class PositionManager:
    """
    Usage:
        pm = PositionManager(order_manager, journal_bridge, on_closed=pipeline.on_trade_closed)
        pm.poll_once()          # একবার চেক করো
        pm.run_loop()           # blocking — সাধারণত আলাদা thread-এ চালাও
    """

    POLL_INTERVAL_SEC = 15

    def __init__(self, order_manager, journal_bridge=None, on_closed=None, trade_memory=None):
        self.order_manager = order_manager
        self.journal_bridge = journal_bridge
        self.on_closed = on_closed         # callback(symbol, result, pnl_usd) — SignalPipeline.on_trade_closed
        self.trade_memory = trade_memory   # TradeMemory.add_lesson()-এর জন্য (optional)
        self._known_tickets: dict[int, dict] = {}   # ticket → last known position snapshot
        self._ticket_to_db_id: dict[int, int] = {}    # MT5 ticket → JournalBridge-এ যে DB id-তে log হয়েছিল

    # ─────────────────────────────────────────────
    # REGISTER  (order place করার পরেই call করো)
    # ─────────────────────────────────────────────

    def register_open(self, ticket: int, db_trade_id: int) -> None:
        """OrderManager.place_market_order() সফল হওয়ার পরে call করো, যাতে
        close detect হলে সঠিক DB row update হয়।"""
        self._ticket_to_db_id[ticket] = db_trade_id

    # ─────────────────────────────────────────────
    # POLL
    # ─────────────────────────────────────────────

    def poll_once(self) -> list[dict]:
        """
        একবার বর্তমান open positions নিয়ে আগের snapshot-এর সাথে diff করে।
        Returns list of closed-position events এই cycle-এ যেগুলো detect হলো।
        """
        current = {p["ticket"]: p for p in self.order_manager.get_open_positions()}
        closed_tickets = set(self._known_tickets.keys()) - set(current.keys())

        events = []
        for ticket in closed_tickets:
            event = self._handle_close(ticket, self._known_tickets[ticket])
            if event:
                events.append(event)

        self._known_tickets = current
        return events

    def run_loop(self, stop_flag=None) -> None:
        log.info(f"[PositionManager] Starting poll loop (every {self.POLL_INTERVAL_SEC}s)")
        while True:
            if stop_flag and stop_flag():
                log.info("[PositionManager] Stop flag set — exiting loop")
                break
            try:
                self.poll_once()
            except Exception as e:
                log.error(f"[PositionManager] Poll error: {e}", exc_info=True)
            time.sleep(self.POLL_INTERVAL_SEC)

    # ─────────────────────────────────────────────
    # INTERNAL — CLOSE HANDLING
    # ─────────────────────────────────────────────

    def _handle_close(self, ticket: int, last_known: dict) -> dict | None:
        """
        Ticket আর open positions-এ নেই — মানে close হয়েছে। Actual exit
        price/pnl history থেকে নিতে হবে (last_known.profit শুধু last-seen
        floating profit, final realized P&L নয়)।
        """
        history = self.order_manager.get_order_history(days_back=1)
        # MT5-এ position ticket আর deal ticket আলাদা — close করার deal-টা
        # খুঁজতে position_id ব্যবহার করো (deal.position_id == position ticket)
        deal = next((d for d in history if d.get("position_id") == ticket), None)

        symbol = last_known["symbol"]
        pnl = deal["profit"] if deal else last_known.get("profit", 0)
        result = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "BREAKEVEN")

        log.info(f"[PositionManager] Close detected — ticket {ticket} {symbol} → {result} (${pnl:.2f})")

        # JournalBridge দিয়ে DB update (paper trades-এর মতো same `trades` table)
        db_id = self._ticket_to_db_id.get(ticket)
        if db_id and self.journal_bridge:
            from datetime import datetime, timezone
            close_data = {
                "close_time":  datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "exit_price":  deal["price"] if deal else last_known.get("price_open"),
                "result":      result,
                "pnl":         round(pnl, 2),
                "pnl_pips":    0,   # broker history থেকে pip হিসাব আলাদা করতে হয় — simplification
                "spread_cost": 0,
                "commission":  0,
                "slippage":    0,
            }
            self.journal_bridge.log_mt5_close(db_id, close_data)

        # CircuitBreaker + RiskEngine-কে জানাও (SignalPipeline.on_trade_closed via callback)
        if self.on_closed:
            self.on_closed(symbol, result, pnl)

        # TradeMemory lesson — context_json না থাকলে minimal info দিয়েই save
        if self.trade_memory:
            self.trade_memory.add_lesson({
                "pair": symbol, "type": last_known.get("type"),
                "result": result, "pnl": round(pnl, 2),
                "close_reason": "MT5_CLOSE",
                "context": {"source": "mt5_demo"},
            })

        return {"ticket": ticket, "symbol": symbol, "result": result, "pnl": pnl}