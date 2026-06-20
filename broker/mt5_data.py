# broker/mt5_data.py  —  Day 32 Part 1, 2, 6 | Tick + Multi-Timeframe Candle Data
# ============================================================
# একজন professional trader শুধু একটা timeframe দেখে না — D1 দিয়ে
# direction, H4 দিয়ে structure, M15 দিয়ে entry timing বোঝে। এই
# module সেই multi-timeframe candle fetch + live tick + disk-এ
# save করার দায়িত্ব নেয়।
#
# account_manager.py-এর resolve_symbol()/market_status() থেকে
# duplicate করা হয়নি — broker symbol resolve করার জন্য AccountManager
# কেই call করো, এই module শুধু candle/tick data নিয়ে কাজ করে।
# ============================================================

import os
import csv
from datetime import datetime, timezone
from utils.logger import get_logger
from broker.mt5_connection import MT5_AVAILABLE

log = get_logger("mt5_data")

if MT5_AVAILABLE:
    import MetaTrader5 as mt5

LIVE_DATA_DIR = "data/live"
os.makedirs(LIVE_DATA_DIR, exist_ok=True)

TIMEFRAMES = {
    "M1":  "TIMEFRAME_M1",
    "M5":  "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "H1":  "TIMEFRAME_H1",
    "H4":  "TIMEFRAME_H4",
    "D1":  "TIMEFRAME_D1",
}


def _mt5_timeframe(label: str):
    """Label string ('M15') কে actual mt5.TIMEFRAME_* constant-এ map করে।"""
    attr = TIMEFRAMES.get(label)
    if not attr or not MT5_AVAILABLE:
        return None
    return getattr(mt5, attr)


class MT5DataFeed:
    """
    MT5 থেকে tick + multi-timeframe candle data নেয়।

    Usage:
        feed = MT5DataFeed()
        tick = feed.get_tick("EURUSD")
        candles = feed.get_candles("EURUSD", "M15", count=500)
        all_tf = feed.get_multi_timeframe("EURUSD")
    """

    DEFAULT_CANDLE_COUNT = 500

    # ─────────────────────────────────────────────
    # TICK DATA  (Part 1)
    # ─────────────────────────────────────────────

    def get_tick(self, broker_symbol: str) -> dict | None:
        """
        Live bid/ask/spread নেয়। broker_symbol অবশ্যই
        AccountManager.resolve_symbol()-এর exact output হতে হবে।
        """
        if not MT5_AVAILABLE:
            log.error("[MT5DataFeed] MetaTrader5 package নেই")
            return None

        tick = mt5.symbol_info_tick(broker_symbol)
        if tick is None or tick.time == 0:
            log.warning(f"[MT5DataFeed] কোনো tick data নেই: {broker_symbol}")
            return None

        info = mt5.symbol_info(broker_symbol)
        digits = info.digits if info else 5
        spread_points = (tick.ask - tick.bid)
        spread_pips = round(spread_points * (10 ** (digits - 1)), 1) if digits else 0

        return {
            "symbol":      broker_symbol,
            "bid":         tick.bid,
            "ask":         tick.ask,
            "spread_pips": spread_pips,
            "time":        datetime.fromtimestamp(tick.time, tz=timezone.utc).isoformat(),
        }

    def get_tick_stream(self, broker_symbols: list[str]) -> dict[str, dict]:
        """একসাথে একাধিক pair-এর tick নেয় — multi-pair scanner-এর basic building block।"""
        stream = {}
        for sym in broker_symbols:
            tick = self.get_tick(sym)
            if tick:
                stream[sym] = tick
        return stream

    def print_tick_stream(self, broker_symbols: list[str]) -> None:
        stream = self.get_tick_stream(broker_symbols)
        bar = "═" * 36
        log.info(bar)
        log.info("  📡  LIVE TICK STREAM")
        log.info(bar)
        for sym, tick in stream.items():
            log.info(f"  {sym:<8} Bid: {tick['bid']}  Ask: {tick['ask']}  ({tick['spread_pips']} pips)")
        log.info(bar)

    # ─────────────────────────────────────────────
    # CANDLE DATA — single + multi timeframe  (Part 2)
    # ─────────────────────────────────────────────

    def get_candles(
        self, broker_symbol: str, timeframe: str, count: int = None
    ) -> list[dict]:
        """
        একটা timeframe-এর candles নেয়। Returns list of dicts:
        {time, open, high, low, close, volume, spread}
        """
        if not MT5_AVAILABLE:
            log.error("[MT5DataFeed] MetaTrader5 package নেই")
            return []

        tf_const = _mt5_timeframe(timeframe)
        if tf_const is None:
            log.error(f"[MT5DataFeed] Unknown timeframe: {timeframe}")
            return []

        count = count or self.DEFAULT_CANDLE_COUNT
        rates = mt5.copy_rates_from_pos(broker_symbol, tf_const, 0, count)
        if rates is None or len(rates) == 0:
            log.warning(f"[MT5DataFeed] কোনো candle পাওয়া যায়নি: {broker_symbol} {timeframe}")
            return []

        candles = [
            {
                "time":   datetime.fromtimestamp(int(r["time"]), tz=timezone.utc).isoformat(),
                "open":   float(r["open"]),
                "high":   float(r["high"]),
                "low":    float(r["low"]),
                "close":  float(r["close"]),
                "volume": float(r["tick_volume"]),
                "spread": int(r["spread"]),
            }
            for r in rates
        ]
        return candles

    def get_multi_timeframe(
        self, broker_symbol: str, timeframes: list[str] = None, count: int = None
    ) -> dict[str, list[dict]]:
        """
        D1 → H4 → H1 → M15 → M5 → M1 — professional trader-এর মতো
        একসাথে সব timeframe নেয়। Direction (D1/H4) আর entry timing
        (M15/M5) দুটোই context-এ থাকবে।
        """
        timeframes = timeframes or list(TIMEFRAMES.keys())
        result = {}
        for tf in timeframes:
            candles = self.get_candles(broker_symbol, tf, count=count)
            result[tf] = candles
        return result

    def print_multi_timeframe_status(
        self, broker_symbol: str, timeframes: list[str] = None
    ) -> None:
        timeframes = timeframes or list(TIMEFRAMES.keys())
        data = self.get_multi_timeframe(broker_symbol, timeframes)
        log.info(f"  {broker_symbol}")
        for tf in timeframes:
            n = len(data.get(tf, []))
            status = "✅" if n > 0 else "❌"
            log.info(f"    {tf:<4} {status}  ({n} candles)")

    # ─────────────────────────────────────────────
    # STORAGE  (Part 6)
    # ─────────────────────────────────────────────

    def save_live_csv(self, broker_symbol: str, timeframe: str, candles: list[dict]) -> str:
        """
        data/live/{SYMBOL}_{TIMEFRAME}_live.csv-এ save করে। DB-তে নয় —
        কারণ db.py-এর `candles` table আলাদা পরিসরের জন্য আছে এবং এখানে
        existing schema পরিবর্তন না করেই raw live snapshot রাখা হচ্ছে।
        """
        path = os.path.join(LIVE_DATA_DIR, f"{broker_symbol}_{timeframe}_live.csv")
        if not candles:
            return path

        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(candles[0].keys()))
            writer.writeheader()
            writer.writerows(candles)

        log.info(f"[MT5DataFeed] Saved {len(candles)} candles → {path}")
        return path