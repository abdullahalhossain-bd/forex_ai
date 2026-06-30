"""
analysis/dat_framework.py — DAT Framework (Direction-Area-Trigger)
====================================================================

Masterclass concept: Before taking any trade, confirm 3 things in order:
  1. Direction (D) — is market uptrend or downtrend?
  2. Area (A)     — is price at an important S/R, trendline, or OB zone?
  3. Trigger (T)  — is there a strong candlestick confirmation at that area?

All three must align. If any is missing → NO TRADE.

This module implements the DAT pipeline as a clean, explicit framework
that can be used standalone or as a pre-filter before the full
analysis_agent pipeline.

Usage:
    from analysis.dat_framework import DATFramework

    dat = DATFramework()
    result = dat.evaluate(symbol="EURUSD", timeframe="15m")
    # → {
    #     "direction": "BULLISH",
    #     "area": {"at_zone": True, "zone_type": "support", "zone_price": 1.0820},
    #     "trigger": {"pattern": "hammer", "confirmed": True},
    #     "dat_signal": "BUY",   # only if all 3 align
    #     "dat_confidence": 75,
    #     "reasoning": "Direction BULLISH + at support zone + hammer trigger",
    #   }
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from utils.logger import get_logger

log = get_logger("dat_framework")


# ── DAT Result ──────────────────────────────────────────────────

@dataclass
class DATResult:
    """Result of the DAT evaluation."""
    direction: str = "NEUTRAL"           # BULLISH / BEARISH / NEUTRAL
    direction_confidence: int = 0        # 0-100
    area_at_zone: bool = False           # is price at a significant zone?
    area_zone_type: str = ""             # support / resistance / ob / fvg / fib
    area_zone_price: Optional[float] = None
    trigger_pattern: str = ""            # hammer / engulfing / pinbar / etc.
    trigger_confirmed: bool = False
    dat_signal: str = "WAIT"             # BUY / SELL / WAIT
    dat_confidence: int = 0
    reasoning: str = ""
    all_aligned: bool = False            # True only if D + A + T all confirm

    def to_dict(self) -> Dict[str, Any]:
        return {
            "direction":             self.direction,
            "direction_confidence":  self.direction_confidence,
            "area_at_zone":          self.area_at_zone,
            "area_zone_type":        self.area_zone_type,
            "area_zone_price":       self.area_zone_price,
            "trigger_pattern":       self.trigger_pattern,
            "trigger_confirmed":     self.trigger_confirmed,
            "dat_signal":            self.dat_signal,
            "dat_confidence":        self.dat_confidence,
            "reasoning":             self.reasoning,
            "all_aligned":           self.all_aligned,
        }


# ── DAT Framework ───────────────────────────────────────────────

class DATFramework:
    """
    Direction-Area-Trigger evaluation pipeline.

    Pulls data from existing modules:
      - Direction: from Indicators trend + MTF bias
      - Area:      from SupportResistance + OrderBlock + FVG + Fibonacci
      - Trigger:   from PatternDetector (candlestick patterns)
    """

    # Minimum confidence thresholds for each stage
    MIN_DIRECTION_CONF = 50   # trend must be at least 50% clear
    MIN_TRIGGER_CONF = 60     # pattern must be at least 60% confidence

    def __init__(self):
        try:
            from data.fetcher import DataFetcher
            from data.indicators import Indicators
            from analysis.patterns import PatternDetector
            from analysis.support_resistance import SupportResistance
            self.fetcher = DataFetcher()
            self.ind = Indicators()
            self.pat = PatternDetector()
            self.sr = SupportResistance()
        except Exception as e:
            log.warning(f"DATFramework init partial: {e}")

    def evaluate(self, symbol: str = "EURUSD", timeframe: str = "15m") -> DATResult:
        """Run the full DAT pipeline for a symbol."""
        result = DATResult()

        try:
            # ── Fetch data ──────────────────────────────────────
            df = self.fetcher.fetch_ohlcv(symbol, timeframe, limit=300)
            if df is None or df.empty:
                result.reasoning = "No data available"
                return result

            df = self.ind.add_all(df)
            df = self.pat.run_full_detection(df)
            ind_ctx = self.ind.get_ai_context(df)

            # ── D: Direction ────────────────────────────────────
            direction, dir_conf = self._evaluate_direction(ind_ctx)
            result.direction = direction
            result.direction_confidence = dir_conf

            if direction == "NEUTRAL" or dir_conf < self.MIN_DIRECTION_CONF:
                result.dat_signal = "WAIT"
                result.reasoning = f"Direction unclear ({direction} {dir_conf}%)"
                return result

            # ── A: Area ─────────────────────────────────────────
            sr_result = self.sr.analyze(df)
            sr_ctx = self.sr.get_ai_context(sr_result) if hasattr(self.sr, 'get_ai_context') else {}
            area_found, zone_type, zone_price = self._evaluate_area(ind_ctx, sr_ctx)

            result.area_at_zone = area_found
            result.area_zone_type = zone_type
            result.area_zone_price = zone_price

            if not area_found:
                result.dat_signal = "WAIT"
                result.reasoning = f"Direction {direction} but no significant area"
                return result

            # ── T: Trigger ──────────────────────────────────────
            pat_ctx = self.pat.get_ai_pattern_context(df)
            trigger_found, pattern_name, trigger_conf = self._evaluate_trigger(pat_ctx, direction)

            result.trigger_pattern = pattern_name
            result.trigger_confirmed = trigger_found

            if not trigger_found:
                result.dat_signal = "WAIT"
                result.reasoning = (
                    f"Direction {direction} + at {zone_type} zone, "
                    f"but no trigger confirmation"
                )
                return result

            # ── All 3 aligned! ──────────────────────────────────
            result.all_aligned = True
            result.dat_signal = "BUY" if direction == "BULLISH" else "SELL"
            result.dat_confidence = min(95, (dir_conf + trigger_conf) // 2)
            result.reasoning = (
                f"Direction {direction} ({dir_conf}%) + "
                f"at {zone_type} zone ({zone_price}) + "
                f"trigger {pattern_name} ({trigger_conf}%)"
            )

            log.info(
                f"[DAT] {symbol} {timeframe} | "
                f"D={direction}({dir_conf}%) A={zone_type}@{zone_price} "
                f"T={pattern_name}({trigger_conf}%) → "
                f"{result.dat_signal} ({result.dat_confidence}%)"
            )

        except Exception as e:
            log.error(f"DAT evaluate failed: {e}")
            result.reasoning = f"Error: {e}"

        return result

    # ── D: Direction evaluation ────────────────────────────────

    def _evaluate_direction(self, ind_ctx: dict) -> tuple[str, int]:
        """Determine market direction from trend + EMAs."""
        trend = (ind_ctx.get("trend") or "").lower()
        price = ind_ctx.get("price", 0)
        ema_9 = ind_ctx.get("ema_9", 0) or ind_ctx.get("ema9", 0)
        ema_21 = ind_ctx.get("ema_21", 0) or ind_ctx.get("ema21", 0)
        sma_50 = ind_ctx.get("sma_50", 0) or ind_ctx.get("sma50", 0)
        sma_200 = ind_ctx.get("sma_200", 0) or ind_ctx.get("sma200", 0)
        rsi = ind_ctx.get("rsi", 50)

        bull_score = 0
        bear_score = 0

        # Trend label
        if "strong_bullish" in trend:
            bull_score += 40
        elif "bullish" in trend:
            bull_score += 25
        elif "strong_bearish" in trend:
            bear_score += 40
        elif "bearish" in trend:
            bear_score += 25

        # EMA alignment
        if ema_9 and ema_21:
            if ema_9 > ema_21:
                bull_score += 20
            else:
                bear_score += 20

        # Price vs SMA 50/200
        if price and sma_50:
            if price > sma_50:
                bull_score += 15
            else:
                bear_score += 15
        if price and sma_200:
            if price > sma_200:
                bull_score += 15
            else:
                bear_score += 15

        # RSI bias
        if rsi > 55:
            bull_score += 10
        elif rsi < 45:
            bear_score += 10

        if bull_score > bear_score:
            direction = "BULLISH"
            confidence = min(100, bull_score)
        elif bear_score > bull_score:
            direction = "BEARISH"
            confidence = min(100, bear_score)
        else:
            direction = "NEUTRAL"
            confidence = 0

        return direction, confidence

    # ── A: Area evaluation ─────────────────────────────────────

    def _evaluate_area(self, ind_ctx: dict, sr_ctx: dict) -> tuple[bool, str, Optional[float]]:
        """Check if price is at a significant zone (S/R, OB, FVG, Fib)."""
        price = ind_ctx.get("price", 0)
        if not price:
            return False, "", None

        # Check Support/Resistance
        nearest_support = sr_ctx.get("nearest_support")
        nearest_resistance = sr_ctx.get("nearest_resistance")

        # Tolerance: within 0.3% of price
        tolerance = price * 0.003

        if nearest_support and abs(price - nearest_support) <= tolerance:
            return True, "support", nearest_support
        if nearest_resistance and abs(price - nearest_resistance) <= tolerance:
            return True, "resistance", nearest_resistance

        # TODO: Add OrderBlock + FVG + Fibonacci zone checks here
        # (would require passing those contexts in — for now S/R is enough)

        return False, "", None

    # ── T: Trigger evaluation ──────────────────────────────────

    def _evaluate_trigger(self, pat_ctx: dict, direction: str) -> tuple[bool, str, int]:
        """Check for candlestick trigger pattern aligned with direction."""
        pattern = (pat_ctx.get("latest_pattern") or "").lower()
        pattern_signal = (pat_ctx.get("pattern_signal") or "").lower()
        pattern_conf = pat_ctx.get("pattern_confidence", 50)

        # Bullish triggers
        bullish_triggers = {"hammer", "bullish_engulfing", "morning_star",
                           "pin_bar_bullish", "three_bar_reversal_bullish"}
        # Bearish triggers
        bearish_triggers = {"shooting_star", "bearish_engulfing", "evening_star",
                           "pin_bar_bearish", "three_bar_reversal_bearish"}

        if direction == "BULLISH":
            if any(t in pattern for t in bullish_triggers) or "bullish" in pattern_signal:
                return True, pattern, max(pattern_conf, 60)
        elif direction == "BEARISH":
            if any(t in pattern for t in bearish_triggers) or "bearish" in pattern_signal:
                return True, pattern, max(pattern_conf, 60)

        return False, "", 0
