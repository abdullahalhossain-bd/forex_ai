# broker/journal_bridge.py  —  Day 31 Bonus 4 | Demo Trading Journal Link
# ============================================================
# Lock-in problem এটা সমাধান করে: paper trading আর MT5 demo trading
# যদি আলাদা storage ব্যবহার করে, তাহলে Learning Agent / TradeMemory
# অর্ধেক data দেখবে — pattern lesson ভুল হবে।
#
# Solution: existing `trades` table-এই save করো (db.py পরিবর্তন
# করতে হয়নি), কিন্তু context_json-এর ভেতরে `source` ট্যাগ যুক্ত
# করো যাতে paper vs mt5_demo আলাদা করা যায় reporting/learning-এ।
# ============================================================

from utils.logger import get_logger
from database.db import TraderDB

log = get_logger("journal_bridge")


class JournalBridge:
    """
    MT5 demo trade-কে paper trade-এর মতো same `trades` table-এ লেখে,
    যাতে দুটো mode-ই একই learning memory ব্যবহার করে।

    Usage:
        bridge = JournalBridge(db)
        trade_id = bridge.log_mt5_open(decision_result, broker_symbol, filled_entry, mt5_order_ticket)
        ...
        bridge.log_mt5_close(trade_id, close_data)
    """

    def __init__(self, db: TraderDB = None):
        self.db = db or TraderDB()

    def log_mt5_open(
        self,
        decision_result: dict,
        broker_symbol: str,
        filled_entry: float,
        mt5_order_ticket: int = None,
    ) -> int:
        """
        MT5 demo-তে order place হওয়ার পরে call করো। PaperTrader-এর
        _build_trade_record()-এর সাথে structurally মিলিয়ে রাখা হয়েছে
        যাতে db.save_trade_open() unchanged থাকতে পারে।
        """
        from datetime import datetime, timezone

        trade = {
            "pair":       broker_symbol,
            "timeframe":  decision_result.get("timeframe"),
            "type":       decision_result.get("decision"),
            "entry":      round(filled_entry, 5),
            "sl":         decision_result.get("sl"),
            "tp":         decision_result.get("tp"),
            "lot":        decision_result.get("lot", 0.01),
            "confidence": decision_result.get("confidence"),
            "open_time":  datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "pattern":    decision_result.get("pattern"),
            "regime":     decision_result.get("regime"),
            "trend":      decision_result.get("trend"),
            "rsi":        decision_result.get("rsi"),
            "session":    decision_result.get("session"),
            "context": {
                "source": "mt5_demo",          # ⭐ paper trade থেকে আলাদা করার ট্যাগ
                "mt5_order_ticket": mt5_order_ticket,
                "mtf_bias":   decision_result.get("mtf_bias"),
                "llm_signal": decision_result.get("llm_signal"),
                "rr_ratio":   decision_result.get("rr"),
            },
        }
        trade_id = self.db.save_trade_open(trade)
        log.info(
            f"[JournalBridge] MT5 demo trade logged → DB #{trade_id} "
            f"(ticket={mt5_order_ticket})"
        )
        return trade_id

    def log_mt5_close(self, trade_id: int, close_data: dict) -> None:
        """close_data একই shape — PaperTrader.close_trade()-এর close_data দেখো।"""
        self.db.save_trade_close(trade_id, close_data)
        log.info(f"[JournalBridge] MT5 demo trade closed → DB #{trade_id}")

    # ─────────────────────────────────────────────
    # COMBINED REPORTING — paper + mt5_demo একসাথে
    # ─────────────────────────────────────────────

    def get_combined_stats(self, starting_balance: float = 10000.0) -> dict:
        """
        সব trade (source নির্বিশেষে) মিলিয়ে stats — Learning Agent
        এটা ব্যবহার করবে, mode আলাদা ভাবে নয়।
        """
        return self.db.get_account_stats(starting_balance=starting_balance)

    def get_stats_by_source(self, starting_balance: float = 10000.0) -> dict:
        """
        Paper vs MT5-demo আলাদা ভাবে break-down — যাতে বোঝা যায় simulation
        আর real-broker-condition performance কতটা মিলছে/আলাদা।
        """
        import json
        history = self.db.get_trade_history(limit=10000)
        paper_pnl, demo_pnl = 0.0, 0.0
        paper_n, demo_n = 0, 0

        for _, row in history.iterrows():
            ctx_raw = row.get("context_json") or "{}"
            try:
                ctx = json.loads(ctx_raw)
            except Exception:
                ctx = {}
            source = ctx.get("source", "paper")  # context_json নেই মানে পুরনো paper trade
            pnl = row.get("pnl", 0) or 0
            if source == "mt5_demo":
                demo_pnl += pnl
                demo_n += 1
            else:
                paper_pnl += pnl
                paper_n += 1

        return {
            "paper":    {"trades": paper_n, "pnl": round(paper_pnl, 2)},
            "mt5_demo": {"trades": demo_n, "pnl": round(demo_pnl, 2)},
        }