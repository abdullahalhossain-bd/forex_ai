# analysis/session_analysis.py  —  Day 62 | Session-Based Manipulation Detection
# ============================================================
# ICT "London Open Manipulation" concept:
#
#   Asian session range তৈরি হয় (tight, low volatility)
#        ↓
#   London open এসে একদিকে fake breakout দেখায়
#        ↓
#   দ্রুত reverse করে আসল direction-এ চলে যায়
#
# এই module Asian range + London candles দেখে এই pattern confirm করে।
# ============================================================

import pandas as pd
from utils.logger import get_logger

log = get_logger("session_analysis")

# UTC session windows (approx, broker-dependent)
LONDON_OPEN_START_HOUR = 7
LONDON_OPEN_END_HOUR   = 10


class SessionAnalyzer:
    """
    Usage:
        analyzer = SessionAnalyzer()
        result = analyzer.detect_london_manipulation(df, asian_range)
    """

    SWEEP_BUFFER_ATR_MULT = 0.05   # range boundary-র সামান্য বাইরে গেলেও sweep ধরা হবে

    def detect_london_manipulation(
        self,
        df: pd.DataFrame,
        asian_range: dict,
    ) -> dict:
        """
        Asian range + London session candles দেখে fake-breakout → reversal
        pattern detect করো।

        Args:
            df          : OHLCV (atr column থাকা উচিত), DatetimeIndex
            asian_range : LiquidityZoneMapper.asian_session_range() এর output
        """
        if not asian_range.get('valid'):
            return self._empty_result("No valid Asian range available")

        if not isinstance(df.index, pd.DatetimeIndex):
            return self._empty_result("DataFrame index is not datetime")

        hours      = df.index.hour
        london_df  = df[(hours >= LONDON_OPEN_START_HOUR) & (hours < LONDON_OPEN_END_HOUR)]

        if london_df.empty:
            return self._empty_result("No London session candles found")

        # সবচেয়ে recent London session নাও (same/next day as Asian range)
        last_day     = london_df.index.normalize().max()
        session      = london_df[london_df.index.normalize() == last_day]
        if session.empty:
            return self._empty_result("No recent London session candles")

        asian_high = asian_range['high']
        asian_low  = asian_range['low']
        atr        = self._safe_atr(df)
        buffer     = atr * self.SWEEP_BUFFER_ATR_MULT

        highs  = session['high'].values
        lows   = session['low'].values
        closes = session['close'].values

        swept_above = bool((highs > asian_high + buffer).any())
        swept_below = bool((lows  < asian_low  - buffer).any())

        current_close = float(closes[-1])

        event     = "NONE"
        direction = "NEUTRAL"
        note      = "No London liquidity sweep detected yet"

        # Bearish manipulation: swept above Asian high then closed back inside/below
        if swept_above and current_close < asian_high:
            event     = "LONDON_LIQUIDITY_SWEEP"
            direction = "BEARISH"
            note      = (
                f"London swept Asian high ({asian_high:.5f}) then rejected back "
                f"below — fake breakout, bearish reversal likely"
            )

        # Bullish manipulation: swept below Asian low then closed back inside/above
        elif swept_below and current_close > asian_low:
            event     = "LONDON_LIQUIDITY_SWEEP"
            direction = "BULLISH"
            note      = (
                f"London swept Asian low ({asian_low:.5f}) then rejected back "
                f"above — fake breakout, bullish reversal likely"
            )

        # Genuine breakout — swept and held beyond range, no rejection back in
        elif swept_above and current_close >= asian_high:
            event     = "LONDON_BREAKOUT"
            direction = "BULLISH"
            note      = f"London broke and held above Asian high ({asian_high:.5f}) — genuine breakout"

        elif swept_below and current_close <= asian_low:
            event     = "LONDON_BREAKOUT"
            direction = "BEARISH"
            note      = f"London broke and held below Asian low ({asian_low:.5f}) — genuine breakdown"

        result = {
            'valid':       True,
            'event':       event,
            'direction':   direction,
            'asian_high':  asian_high,
            'asian_low':   asian_low,
            'swept_above': swept_above,
            'swept_below': swept_below,
            'current_close': round(current_close, 5),
            'is_manipulation': event == "LONDON_LIQUIDITY_SWEEP",
            'note': note,
        }

        log.info(f"[SessionAnalyzer] {event} | Direction: {direction}")
        return result

    def _safe_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        try:
            val = df['atr'].iloc[-1]
            if val and val == val:  # not NaN
                return float(val)
        except Exception:
            pass
        return 0.0005

    def _empty_result(self, reason: str) -> dict:
        return {
            'valid': False, 'event': 'NONE', 'direction': 'NEUTRAL',
            'is_manipulation': False, 'note': reason,
        }

    # ─────────────────────────────────────────────
    # AI CONTEXT
    # ─────────────────────────────────────────────

    def get_ai_context(self, result: dict) -> dict:
        return {
            'session_event':        result.get('event', 'NONE'),
            'session_direction':    result.get('direction', 'NEUTRAL'),
            'session_manipulation': result.get('is_manipulation', False),
            'session_note':         result.get('note', ''),
        }

    # ─────────────────────────────────────────────
    # PRINT SUMMARY
    # ─────────────────────────────────────────────

    def print_summary(self, result: dict) -> None:
        bar  = "═" * 52
        icon = "🚨" if result.get('is_manipulation') else ("🟢" if result.get('event') == 'LONDON_BREAKOUT' else "🟡")
        log.info(bar)
        log.info("  🌍  SESSION ANALYSIS — LONDON OPEN  (Day 62)")
        log.info(bar)
        log.info(f"  {icon} Event     : {result.get('event')}")
        log.info(f"  Direction : {result.get('direction')}")
        log.info(f"  Note      : {result.get('note')}")
        log.info(bar)