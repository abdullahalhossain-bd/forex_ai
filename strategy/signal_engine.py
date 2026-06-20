# strategy/signal_engine.py  —  Day 9 | Regime-Aware Signal Generator

from utils.logger import get_logger

log = get_logger("signal_engine")


class SignalEngine:
    """
    Rule-based signal generator।
    Day 8 এর regime context ব্যবহার করে smarter decision নেয়।

    Architecture:
        SignalEngine  →  (Day 10) RiskManager  →  (Day 11) Executor
    """

    # Thresholds — config.py তে নেওয়া যাবে পরে
    RSI_OVERSOLD       = 35
    RSI_OVERBOUGHT     = 65
    RSI_EXTREME_OVER   = 25   # trending bear এ bounce possible
    RSI_EXTREME_UNDER  = 75   # trending bull এ pullback possible
    SR_DISTANCE_PIPS   = 0.0015   # support/resistance এর কাছে কতটুকু

    def generate(
        self,
        ind_ctx: dict,
        pat_ctx: dict,
        sr_ctx:  dict,
        regime:  dict,
        mtf_bias: str = "NEUTRAL",
    ) -> dict:
        """
        সব context নিয়ে BUY / SELL / NO TRADE সিদ্ধান্ত দেয়।

        Returns:
            {
                signal:     "BUY" | "SELL" | "NO TRADE",
                confidence: 0-100,
                entry:      float,
                reasons:    [str],
                blocked_by: str | None,
            }
        """

        rsi     = ind_ctx.get("rsi", 50)
        price   = ind_ctx.get("close", 0)
        trend   = ind_ctx.get("trend", "neutral")
        macd_s  = ind_ctx.get("macd_signal", "neutral")

        regime_type = regime.get("regime", "RANGING")
        regime_dir  = regime.get("direction", "NEUTRAL")
        volatility  = regime.get("volatility", "NORMAL")

        patterns     = pat_ctx.get("recent_patterns", [])
        near_support = sr_ctx.get("location") == "near_support"
        near_resist  = sr_ctx.get("location") == "near_resistance"

        signal     = "NO TRADE"
        confidence = 0
        reasons    = []
        blocked_by = None

        # ── Guard: High Volatility ──────────────────────────────
        if volatility == "HIGH_VOLATILITY":
            return self._no_trade("High volatility — dangerous", price)

        # ── Guard: Counter-trend block ──────────────────────────
        # Trending bearish market এ BUY signal block হবে
        # (Day 8 শিক্ষা: ADX > 25 + bearish → oversold মানে bounce না)

        # ── Pattern helpers ─────────────────────────────────────
        bullish_pat = any(
            k in p for p in patterns
            for k in ("Bullish", "Hammer", "Morning Star", "Pin Bar")
        )
        bearish_pat = any(
            k in p for p in patterns
            for k in ("Bearish", "Shooting", "Evening Star")
        )

        # ── BUY Logic ───────────────────────────────────────────
        buy_score = 0

        if rsi < self.RSI_OVERSOLD:
            buy_score += 2
            reasons.append(f"RSI oversold ({rsi:.1f})")

        if bullish_pat:
            buy_score += 2
            reasons.append(f"Bullish pattern: {patterns[0] if patterns else ''}")

        if near_support:
            buy_score += 2
            reasons.append("Price near support zone")

        if "bullish" in trend.lower():
            buy_score += 1
            reasons.append(f"Trend: {trend}")

        if macd_s == "bullish_cross":
            buy_score += 1
            reasons.append("MACD bullish crossover")

        if mtf_bias in ("BULLISH", "STRONG_BULLISH"):
            buy_score += 1
            reasons.append(f"MTF bias: {mtf_bias}")

        # Counter-trend block (trending bearish → BUY blocked)
        if buy_score >= 4:
            if regime_type == "TRENDING" and regime_dir == "BEARISH":
                if rsi > self.RSI_EXTREME_OVER:   # RSI 25 এর নিচে না গেলে
                    blocked_by = "Counter-trend block (strong bearish regime)"
                    buy_score  = 0
                    reasons    = []

        # ── SELL Logic ──────────────────────────────────────────
        sell_score = 0
        sell_reasons = []

        if rsi > self.RSI_OVERBOUGHT:
            sell_score += 2
            sell_reasons.append(f"RSI overbought ({rsi:.1f})")

        if bearish_pat:
            sell_score += 2
            sell_reasons.append(f"Bearish pattern: {patterns[0] if patterns else ''}")

        if near_resist:
            sell_score += 2
            sell_reasons.append("Price near resistance zone")

        if "bearish" in trend.lower():
            sell_score += 1
            sell_reasons.append(f"Trend: {trend}")

        if macd_s == "bearish_cross":
            sell_score += 1
            sell_reasons.append("MACD bearish crossover")

        if mtf_bias in ("BEARISH", "STRONG_BEARISH"):
            sell_score += 1
            sell_reasons.append(f"MTF bias: {mtf_bias}")

        # Counter-trend block (trending bullish → SELL blocked)
        if sell_score >= 4:
            if regime_type == "TRENDING" and regime_dir == "BULLISH":
                if rsi < self.RSI_EXTREME_UNDER:
                    blocked_by   = "Counter-trend block (strong bullish regime)"
                    sell_score   = 0
                    sell_reasons = []

        # ── Final Decision ───────────────────────────────────────
        if buy_score >= 4 and buy_score > sell_score:
            signal     = "BUY"
            confidence = min(buy_score * 12, 95)

        elif sell_score >= 4 and sell_score > buy_score:
            signal     = "SELL"
            confidence = min(sell_score * 12, 95)
            reasons    = sell_reasons

        else:
            signal     = "NO TRADE"
            confidence = 0
            reasons    = reasons or sell_reasons or ["Insufficient confluence"]

        result = {
            "signal":     signal,
            "confidence": confidence,
            "entry":      round(price, 5),
            "reasons":    reasons,
            "blocked_by": blocked_by,
            "scores": {
                "buy":  buy_score,
                "sell": sell_score,
            },
        }

        log.info(
            f"Signal: {signal} | Confidence: {confidence}% | "
            f"Buy score: {buy_score} | Sell score: {sell_score}"
        )
        return result

    # ── Helpers ──────────────────────────────────────────────────
    def _no_trade(self, reason: str, price: float) -> dict:
        return {
            "signal":     "NO TRADE",
            "confidence": 0,
            "entry":      round(price, 5),
            "reasons":    [reason],
            "blocked_by": reason,
            "scores":     {"buy": 0, "sell": 0},
        }

    def print_summary(self, result: dict) -> None:
        sig = result["signal"]
        bar = "═" * 44

        signal_colors = {
            "BUY":      "🟢",
            "SELL":     "🔴",
            "NO TRADE": "⚪",
        }
        icon = signal_colors.get(sig, "⚪")

        log.info(bar)
        log.info(f"  {icon}  SIGNAL ENGINE")
        log.info(bar)
        log.info(f"  Signal      : {sig}")
        log.info(f"  Confidence  : {result['confidence']}%")
        log.info(f"  Entry       : {result['entry']}")
        log.info(f"  Buy score   : {result['scores']['buy']}")
        log.info(f"  Sell score  : {result['scores']['sell']}")

        if result.get("blocked_by"):
            log.info(f"  Blocked     : {result['blocked_by']}")

        log.info("  ── Reasons ──")
        for r in result["reasons"]:
            log.info(f"    • {r}")
        log.info(bar)

    def get_ai_context(self, result: dict) -> dict:
        return {
            "signal":            result["signal"],
            "signal_confidence": result["confidence"],
            "entry_price":       result["entry"],
            "signal_reasons":    result["reasons"],
            "signal_blocked_by": result.get("blocked_by"),
        }