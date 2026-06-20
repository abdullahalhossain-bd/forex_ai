# fundamental/fundamental_sentiment.py  —  Day 43 | Fundamental Sentiment Score
# ============================================================
# Economic event history (database/db.py এর `economic_history` table)
# থেকে একটা currency-র "fundamental score" বের করে — যেমন doc-এ লেখা:
#
#     USD Fundamental Score: +35 Bullish
#
# এই score টা MasterAnalyst-এর context-এ যাবে (sentiment.py-এর
# market-psychology score-এর পাশাপাশি, কিন্তু এটা purely news-driven)।
# ============================================================

from database.db import TraderDB
from fundamental.news_filter import NewsFilter
from utils.logger import get_logger

log = get_logger("fundamental_sentiment")

MAJOR_CURRENCIES = ["USD", "EUR", "GBP", "JPY"]

# raw_score (bullish_count - bearish_count) → scaled -100..+100
SCALE_PER_EVENT = 12   # প্রতিটা net event reaction কত পয়েন্ট নাড়াবে


class FundamentalSentimentScore:
    """
    Usage:
        fs = FundamentalSentimentScore()
        usd_score = fs.score_currency("USD")
        pair_score = fs.score_pair("EURUSD")
        ctx = fs.get_ai_context(pair_score)
    """

    def __init__(self, db: TraderDB = None, news_filter: NewsFilter = None):
        self.db = db or TraderDB()
        self.news_filter = news_filter or NewsFilter()

    # ─────────────────────────────────────────────
    # SINGLE CURRENCY SCORE
    # ─────────────────────────────────────────────

    def score_currency(self, currency: str, lookback: int = 10) -> dict:
        """
        একটা currency-র fundamental score বের করে — সাম্প্রতিক
        economic_history reaction-গুলো + upcoming high-impact risk মিলিয়ে।

        Returns:
            {
                "currency": "USD",
                "score": 35,
                "label": "BULLISH",
                "sample_size": 6,
                "upcoming_risk": "HIGH",
                "reason": "3 bullish vs 1 bearish reaction in recent history; ..."
            }
        """
        currency = currency.upper()
        bias = self.db.get_currency_fundamental_bias(currency, lookback=lookback)

        raw_score = bias["raw_score"]
        score     = max(-100, min(100, raw_score * SCALE_PER_EVENT))

        if score >= 25:
            label = "STRONG_BULLISH" if score >= 50 else "BULLISH"
        elif score <= -25:
            label = "STRONG_BEARISH" if score <= -50 else "BEARISH"
        else:
            label = "NEUTRAL"

        # Upcoming news risk — high-impact event আসন্ন থাকলে score-এর
        # উপর confidence কমানো উচিত (volatile reversal সম্ভব)
        upcoming_risk = self._upcoming_risk_for_currency(currency)

        reason = (
            f"{bias['bullish_count']} bullish vs {bias['bearish_count']} bearish "
            f"reaction in last {bias['sample_size']} {currency} events"
            if bias["sample_size"] else
            f"No recent {currency} economic history — neutral by default"
        )

        result = {
            "currency":      currency,
            "score":         round(score),
            "label":         label,
            "sample_size":   bias["sample_size"],
            "upcoming_risk": upcoming_risk,
            "reason":        reason,
        }

        log.info(
            f"[FundamentalSentiment] {currency} | Score: {result['score']:+d} | "
            f"Label: {label} | Upcoming risk: {upcoming_risk}"
        )
        return result

    def _upcoming_risk_for_currency(self, currency: str) -> str:
        """এই currency-র জন্য কোনো high-impact event আসন্ন কিনা (3h window)।"""
        try:
            check = self.news_filter.check(f"{currency}USD" if currency != "USD" else "EURUSD")
            for ev in check.get("upcoming_events", []):
                if ev.get("currency") == currency:
                    return ev.get("volatility", {}).get("level", "LOW")
            if not check.get("trade_allowed", True):
                for ev in check.get("flagged_events", []):
                    if ev.get("currency") == currency:
                        return ev.get("volatility", {}).get("level", "HIGH")
        except Exception as e:
            log.warning(f"[FundamentalSentiment] upcoming_risk check failed: {e}")
        return "LOW"

    # ─────────────────────────────────────────────
    # PAIR SCORE (base vs quote)
    # ─────────────────────────────────────────────

    def score_pair(self, pair: str, lookback: int = 10) -> dict:
        """
        EURUSD হলে EUR vs USD fundamental score-এর difference থেকে
        pair-level bias বের করে।

        Returns:
            {
                "pair": "EURUSD",
                "base": "EUR", "quote": "USD",
                "base_score": -10, "quote_score": 35,
                "diff": -45,
                "pair_bias": "BEARISH",
                "reason": "USD fundamentals stronger than EUR"
            }
        """
        pair_clean = pair.upper().replace("/", "").replace("=X", "")
        base  = pair_clean[:3]
        quote = pair_clean[3:6] if len(pair_clean) >= 6 else pair_clean[3:]

        base_result  = self.score_currency(base, lookback=lookback)
        quote_result = self.score_currency(quote, lookback=lookback)

        diff = base_result["score"] - quote_result["score"]

        if diff >= 30:
            bias = "STRONG_BULLISH"
        elif diff >= 10:
            bias = "BULLISH"
        elif diff <= -30:
            bias = "STRONG_BEARISH"
        elif diff <= -10:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"

        reason = (
            f"{base} fundamentals stronger than {quote}" if diff > 10 else
            f"{quote} fundamentals stronger than {base}" if diff < -10 else
            f"{base} and {quote} fundamentals roughly balanced"
        )

        result = {
            "pair":        pair,
            "base":        base,
            "quote":       quote,
            "base_score":  base_result["score"],
            "quote_score": quote_result["score"],
            "diff":        diff,
            "pair_bias":   bias,
            "reason":      reason,
            "base_detail":  base_result,
            "quote_detail": quote_result,
        }

        log.info(
            f"[FundamentalSentiment] {pair} | {base}:{base_result['score']:+d} "
            f"vs {quote}:{quote_result['score']:+d} | Bias: {bias}"
        )
        return result

    # ─────────────────────────────────────────────
    # AI CONTEXT  (MasterAnalyst handoff)
    # ─────────────────────────────────────────────

    def get_ai_context(self, pair_result: dict) -> dict:
        return {
            "fundamental_pair_bias":   pair_result.get("pair_bias", "NEUTRAL"),
            "fundamental_base_score":  pair_result.get("base_score", 0),
            "fundamental_quote_score": pair_result.get("quote_score", 0),
            "fundamental_diff":        pair_result.get("diff", 0),
            "fundamental_reason":      pair_result.get("reason", ""),
        }

    # ─────────────────────────────────────────────
    # PRINT SUMMARY
    # ─────────────────────────────────────────────

    def print_summary(self, pair_result: dict) -> None:
        bar = "═" * 50
        log.info(bar)
        log.info(f"  💵  FUNDAMENTAL SENTIMENT SCORE  (Day 43)")
        log.info(bar)
        log.info(f"  Pair        : {pair_result['pair']}")
        log.info(
            f"  {pair_result['base']} Score : {pair_result['base_score']:+d}  "
            f"({pair_result['base_detail']['label']})"
        )
        log.info(
            f"  {pair_result['quote']} Score : {pair_result['quote_score']:+d}  "
            f"({pair_result['quote_detail']['label']})"
        )
        log.info(f"  Pair Bias   : {pair_result['pair_bias']}")
        log.info(f"  Reason      : {pair_result['reason']}")
        log.info(bar)