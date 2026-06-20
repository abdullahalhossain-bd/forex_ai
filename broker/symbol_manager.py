# broker/symbol_manager.py  —  Day 32 Part 3 | Multi-Pair Scanner
# ============================================================
# একসাথে একাধিক pair-এর basic trend/volatility snapshot নেয়।
# এটা rule_engine.py-এর replacement না — সেটা uploaded হয়নি, তাই
# এখানে শুধু একটা lightweight heuristic (EMA slope + ATR-based
# volatility bucket) দেখানো হলো scanner output demonstrate করার
# জন্য। আসল rule_engine.py এলে এই heuristic বদলে দেওয়া উচিত।
# ============================================================

from utils.logger import get_logger
from broker.mt5_data import MT5DataFeed

log = get_logger("symbol_manager")

DEFAULT_SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]


class SymbolManager:
    """
    Multi-pair scanner — broker symbol resolve করা AccountManager-এর
    দায়িত্ব, এই class শুধু resolved symbol list নিয়ে scan করে।

    Usage:
        sm = SymbolManager(account_manager)
        broker_symbols = sm.resolve_all(["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"])
        snapshot = sm.scan(broker_symbols)
    """

    def __init__(self, account_manager, data_feed: MT5DataFeed = None):
        self.account_manager = account_manager
        self.feed = data_feed or MT5DataFeed()

    def resolve_all(self, requested_symbols: list[str]) -> dict[str, str | None]:
        """প্রতিটা requested symbol-কে broker-এর exact name-এ resolve করে।"""
        resolved = {}
        for sym in requested_symbols:
            resolved[sym] = self.account_manager.resolve_symbol(sym)
        return resolved

    def scan(self, broker_symbols: list[str]) -> dict[str, dict]:
        """
        প্রতিটা pair-এর জন্য basic trend/volatility snapshot বানায়।
        rule_engine.py uploaded হলে এই snapshot-টা সেই engine-এর input
        হতে পারে — এখন শুধু M15 candle থেকে heuristic বের করা হচ্ছে।
        """
        results = {}
        for sym in broker_symbols:
            candles = self.feed.get_candles(sym, "M15", count=50)
            if not candles:
                results[sym] = {"status": "NO_DATA"}
                continue
            results[sym] = self._classify(candles)
        return results

    def _classify(self, candles: list[dict]) -> dict:
        closes = [c["close"] for c in candles]
        highs = [c["high"] for c in candles]
        lows = [c["low"] for c in candles]

        recent_avg = sum(closes[-10:]) / 10
        older_avg = sum(closes[-30:-10]) / 20 if len(closes) >= 30 else sum(closes[:-10]) / max(1, len(closes) - 10)

        slope = recent_avg - older_avg
        avg_range = sum(h - l for h, l in zip(highs[-20:], lows[-20:])) / min(20, len(highs))
        price_ref = closes[-1] or 1
        range_pct = (avg_range / price_ref) * 100 if price_ref else 0

        if abs(slope) < avg_range * 0.3:
            trend = "RANGE"
        elif slope > 0:
            trend = "BULLISH"
        else:
            trend = "BEARISH"

        volatility = "HIGH_VOLATILITY" if range_pct > 0.15 else "NORMAL"

        return {
            "status": "OK",
            "trend": trend,
            "volatility": volatility,
            "last_close": closes[-1],
        }

    def print_scan(self, broker_symbols: list[str]) -> None:
        results = self.scan(broker_symbols)
        bar = "═" * 36
        log.info(bar)
        log.info("  🔍  MARKET SCANNER")
        log.info(bar)
        for sym, r in results.items():
            if r["status"] != "OK":
                log.info(f"  {sym:<8} ❌ {r['status']}")
                continue
            tag = r["volatility"] if r["volatility"] == "HIGH_VOLATILITY" else r["trend"]
            log.info(f"  {sym:<8} {tag}")
        log.info(bar)