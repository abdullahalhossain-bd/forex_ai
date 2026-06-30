"""
analysis/amd_strategy.py — AMD Strategy (Accumulation-Manipulation-Distribution)
================================================================================

Masterclass concept:
  The market moves in 3 phases during each session:
  
  1. Accumulation — Price ranges in a tight zone (Asian session typically).
     Big players build positions without moving price.
     
  2. Manipulation — Price breaks the accumulation range (fake breakout /
     liquidity sweep) to trigger retail stop losses. This is the "judas swing".
     
  3. Distribution — Price reverses hard in the true direction and trends
     for the rest of the session. This is where the real money is made.

Detection logic:
  - Accumulation: Find a tight range (ATR < 0.7x median ATR) lasting 3+ hours
  - Manipulation: Price breaks the range high/low then reverses
  - Distribution: Price moves strongly in the opposite direction of the fake breakout

Entry signal:
  - After manipulation is detected (sweep + reversal candle)
  - Enter in the direction of the distribution (opposite of the fake breakout)

Usage:
    from analysis.amd_strategy import AMDStrategy

    amd = AMDStrategy()
    result = amd.analyze("EURUSD", "15m", df)
    # → {
    #     "phase": "DISTRIBUTION",
    #     "accumulation_range": {"high": 1.0850, "low": 1.0830},
    #     "manipulation": {"direction": "UP", "swept": "range_high"},
    #     "distribution": {"direction": "SELL", "confidence": 72},
    #     "signal": "SELL",
    #   }
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd

from core.unified_signal import UnifiedSignal
from utils.logger import get_logger

log = get_logger("amd_strategy")


# ── Constants ──────────────────────────────────────────────────

# Accumulation: range must be tight (ATR < 0.7x median)
ACCUMULATION_ATR_MAX_MULT = 0.7

# Accumulation: must last at least this many candles (3h on M15 = 12 candles)
ACCUMULATION_MIN_CANDLES = 8

# Manipulation: breakout candle must extend beyond range by this much
MANIPULATION_BREAKOUT_MIN_PIPS = 5

# Distribution: reversal candle must close back inside the range
DISTRIBUTION_REVERSAL_REQUIRED = True


class AMDStrategy:
    """
    Accumulation-Manipulation-Distribution strategy.

    Detects the 3-phase market cycle and generates trade signals
    during the Distribution phase (after Manipulation is confirmed).
    """

    name = "amd_strategy"
    timeframe_scope = ("M5", "M15", "M30", "H1")

    def analyze(
        self,
        symbol: str,
        timeframe: str,
        df: pd.DataFrame,
        session: str = "",
    ) -> UnifiedSignal:
        """Run AMD analysis and return a UnifiedSignal."""
        if timeframe.upper() not in self.timeframe_scope:
            return UnifiedSignal.wait(symbol, timeframe,
                                      reason=f"{timeframe} not in AMD scope")

        if df is None or len(df) < 30:
            return UnifiedSignal.wait(symbol, timeframe, reason="Insufficient data for AMD")

        try:
            result = self._detect_amd(df)
        except Exception as e:
            log.debug(f"AMD detection failed: {e}")
            return UnifiedSignal.wait(symbol, timeframe, reason=f"AMD error: {e}")

        if result is None:
            return UnifiedSignal.wait(symbol, timeframe, reason="No AMD pattern detected")

        phase = result.get("phase", "")
        dist = result.get("distribution", {})

        # Only trade during DISTRIBUTION phase
        if phase != "DISTRIBUTION":
            return UnifiedSignal.wait(
                symbol, timeframe,
                reason=f"AMD phase: {phase} (waiting for DISTRIBUTION)"
            )

        direction = dist.get("direction", "WAIT")
        confidence = dist.get("confidence", 0)

        if direction not in ("BUY", "SELL") or confidence < 40:
            return UnifiedSignal.wait(
                symbol, timeframe,
                reason=f"AMD distribution direction={direction} conf={confidence}% (too low)"
            )

        # Build trade signal
        last_close = float(df["close"].iloc[-1])
        atr = self._get_atr(df)

        if direction == "BUY":
            sl = last_close - (atr * 1.5)
            tp = [last_close + (atr * 3.0)]
        else:
            sl = last_close + (atr * 1.5)
            tp = [last_close - (atr * 3.0)]

        reasons = [
            f"AMD Phase: DISTRIBUTION",
            f"Accumulation range: {result['accumulation_range']['low']}-{result['accumulation_range']['high']}",
            f"Manipulation: {result['manipulation']['direction']} sweep of {result['manipulation']['swept']}",
            f"Distribution direction: {direction} ({confidence}%)",
        ]

        return UnifiedSignal(
            pair=symbol,
            timeframe=timeframe,
            signal=direction,
            confidence=confidence,
            entry=last_close,
            sl=sl,
            tp=tp,
            lot=0.01,
            risk_percent=0.5,
            source_agents=["amd"],
            agent_votes={"amd": confidence},
            reasons=reasons,
            market_story=f"AMD: accumulation→manipulation→distribution ({direction})",
            market_bias="BULLISH" if direction == "BUY" else "BEARISH",
            regime="TRENDING",
            session=session or None,
            metadata=result,
        )

    # ── AMD Detection ───────────────────────────────────────────

    def _detect_amd(self, df: pd.DataFrame) -> Optional[Dict]:
        """Detect the 3-phase AMD pattern."""
        # Compute ATR
        df = df.copy()
        df["tr"] = pd.concat([
            df["high"] - df["low"],
            (df["high"] - df["close"].shift()).abs(),
            (df["low"] - df["close"].shift()).abs(),
        ], axis=1).max(axis=1)
        df["atr"] = df["tr"].rolling(14).mean()
        atr_median = df["atr"].rolling(50, min_periods=10).median()

        # ── Step 1: Find accumulation zone ──────────────────────
        # Look for a period where ATR is consistently below 0.7x median
        # and price stays in a tight range.
        acc_start = None
        acc_end = None
        acc_high = None
        acc_low = None

        # Scan last 50 candles for accumulation
        lookback = min(50, len(df) - 1)
        for i in range(len(df) - lookback, len(df) - ACCUMULATION_MIN_CANDLES):
            window = df.iloc[i:i + ACCUMULATION_MIN_CANDLES]
            current_atr = window["atr"].mean()
            median_atr = atr_median.iloc[i] if not pd.isna(atr_median.iloc[i]) else current_atr

            if median_atr <= 0:
                continue

            # Check if ATR is low (tight range)
            if current_atr > median_atr * ACCUMULATION_ATR_MAX_MULT:
                continue

            # Check if price is in a tight range
            range_high = window["high"].max()
            range_low = window["low"].min()
            range_size = range_high - range_low

            # Range should be less than 2x ATR (tight)
            if range_size > current_atr * 3:
                continue

            # Found accumulation
            acc_start = window.index[0]
            acc_end = window.index[-1]
            acc_high = range_high
            acc_low = range_low
            break

        if acc_start is None:
            return None

        # ── Step 2: Check for manipulation ──────────────────────
        # After accumulation, did price break the range then reverse?
        after_acc = df.loc[df.index > acc_end]
        if len(after_acc) < 3:
            return None

        # Did price break above accumulation high?
        broke_high = any(after_acc["high"] > acc_high)
        # Did price break below accumulation low?
        broke_low = any(after_acc["low"] < acc_low)

        if not broke_high and not broke_low:
            # Still in accumulation
            return {
                "phase": "ACCUMULATION",
                "accumulation_range": {"high": acc_high, "low": acc_low},
                "manipulation": {},
                "distribution": {},
            }

        # Determine manipulation direction
        if broke_high and not broke_low:
            manip_direction = "UP"
            swept = "range_high"
        elif broke_low and not broke_high:
            manip_direction = "DOWN"
            swept = "range_low"
        else:
            # Both broke — use the more recent one
            last_high_break = after_acc[after_acc["high"] > acc_high].index[-1]
            last_low_break = after_acc[after_acc["low"] < acc_low].index[-1]
            if last_high_break > last_low_break:
                manip_direction = "UP"
                swept = "range_high"
            else:
                manip_direction = "DOWN"
                swept = "range_low"

        # ── Step 3: Check for distribution (reversal) ───────────
        # After the manipulation breakout, did price reverse?
        last_candle = after_acc.iloc[-1]
        last_close = float(last_candle["close"])

        distribution_direction = "WAIT"
        distribution_confidence = 0

        if manip_direction == "UP":
            # Broke high → expect reversal DOWN (distribution = SELL)
            if last_close < acc_high:
                distribution_direction = "SELL"
                # Confidence based on how far price reversed
                reversal = acc_high - last_close
                range_size = acc_high - acc_low
                if range_size > 0:
                    distribution_confidence = min(85, 40 + int(reversal / range_size * 50))
                else:
                    distribution_confidence = 50

        elif manip_direction == "DOWN":
            # Broke low → expect reversal UP (distribution = BUY)
            if last_close > acc_low:
                distribution_direction = "BUY"
                reversal = last_close - acc_low
                range_size = acc_high - acc_low
                if range_size > 0:
                    distribution_confidence = min(85, 40 + int(reversal / range_size * 50))
                else:
                    distribution_confidence = 50

        if distribution_direction == "WAIT":
            return {
                "phase": "MANIPULATION",
                "accumulation_range": {"high": acc_high, "low": acc_low},
                "manipulation": {"direction": manip_direction, "swept": swept},
                "distribution": {},
            }

        return {
            "phase": "DISTRIBUTION",
            "accumulation_range": {"high": acc_high, "low": acc_low},
            "manipulation": {"direction": manip_direction, "swept": swept},
            "distribution": {
                "direction": distribution_direction,
                "confidence": distribution_confidence,
            },
        }

    def _get_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Get current ATR value."""
        try:
            tr = pd.concat([
                df["high"] - df["low"],
                (df["high"] - df["close"].shift()).abs(),
                (df["low"] - df["close"].shift()).abs(),
            ], axis=1).max(axis=1)
            atr = tr.rolling(period).mean().iloc[-1]
            return float(atr) if not pd.isna(atr) else 0.001
        except Exception:
            return 0.001
