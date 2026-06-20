# analysis/market_regime.py
# ============================================================
# Day 8 — Market Regime Detection Engine
# AI Trader-এর Context Brain
#
# "বর্তমান market কোন অবস্থায় আছে?"
# এটা না জানলে ভুল strategy → ভুল trade
# ============================================================

import pandas as pd
import numpy as np
from utils.logger import get_logger

log = get_logger(__name__)


class MarketRegimeDetector:
    """
    Market Regime detect করে — 4টা dimension:

    1. REGIME    : Trending / Ranging / Breakout
    2. DIRECTION : Bullish / Bearish / Neutral
    3. STRENGTH  : Strong / Moderate / Weak
    4. VOLATILITY: High / Normal / Low

    এই 4টা মিলে AI বুঝবে:
    "এখন কোন strategy apply করা উচিত?"
    """

    def __init__(self):
        self.adx_strong   = 40    # ADX > 40 = strong trend
        self.adx_trend    = 20    # ADX > 20 = trending
        self.atr_high     = 1.5   # ATR > avg*1.5 = high volatility
        self.atr_low      = 0.7   # ATR < avg*0.7 = low volatility

    # ─────────────────────────────────────────────
    # MAIN METHOD
    # ─────────────────────────────────────────────

    def detect(self, df: pd.DataFrame) -> dict:
        """
        Full market regime analysis।
        df-এ indicators আগে থেকে থাকতে হবে (add_all করা)।
        """
        df   = df.copy()
        df   = self._add_adx(df)
        last = df.iloc[-1]

        regime     = self._detect_regime(df, last)
        direction  = self._detect_direction(last)
        strength   = self._detect_strength(last)
        volatility = self._detect_volatility(df, last)
        strategy   = self._suggest_strategy(regime, direction, strength, volatility)

        result = {
            'regime':        regime,
            'direction':     direction,
            'strength':      strength,
            'volatility':    volatility,
            'adx':           round(float(last.get('adx', 0)), 2),
            'atr':           round(float(last.get('atr', 0)), 5),
            'atr_avg':       round(float(df['atr'].mean()), 5),
            'strategy':      strategy,
        }

        log.info(
            f"Regime: {regime} | Direction: {direction} | "
            f"Strength: {strength} | Volatility: {volatility}"
        )
        return result

    # ─────────────────────────────────────────────
    # ADX CALCULATION (pandas-ta ছাড়া)
    # ─────────────────────────────────────────────

    def _add_adx(self, df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """
        ADX — Average Directional Index
        Trend strength measure করে (0-100)
        Direction বলে না, শুধু কতটা strong সেটা বলে
        """
        high  = df['high']
        low   = df['low']
        close = df['close']

        # True Range
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low  - close.shift(1)).abs()
        tr  = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # Directional Movement
        dm_plus  = high.diff()
        dm_minus = -low.diff()
        dm_plus  = dm_plus.where((dm_plus > dm_minus) & (dm_plus > 0), 0)
        dm_minus = dm_minus.where((dm_minus > dm_plus) & (dm_minus > 0), 0)

        # Smoothed (Wilder's smoothing)
        atr_s    = tr.ewm(alpha=1/period, adjust=False).mean()
        dmp_s    = dm_plus.ewm(alpha=1/period, adjust=False).mean()
        dmm_s    = dm_minus.ewm(alpha=1/period, adjust=False).mean()

        di_plus  = 100 * dmp_s / atr_s.replace(0, np.nan)
        di_minus = 100 * dmm_s / atr_s.replace(0, np.nan)

        dx = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan)
        df['adx']      = dx.ewm(alpha=1/period, adjust=False).mean()
        df['di_plus']  = di_plus
        df['di_minus'] = di_minus

        return df

    # ─────────────────────────────────────────────
    # REGIME DETECTION
    # ─────────────────────────────────────────────

    def _detect_regime(self, df: pd.DataFrame, last) -> str:
        """
        ADX + Price structure দিয়ে regime বোঝো

        TRENDING  : ADX > 20, price making HH/HL or LL/LH
        RANGING   : ADX < 20, price bouncing in a box
        BREAKOUT  : ADX rising fast from low level
        """
        adx = float(last.get('adx', 0))

        # ADX rising fast → breakout possible
        adx_series = df['adx'].dropna()
        if len(adx_series) >= 5:
            adx_5_ago = float(adx_series.iloc[-5])
            adx_rising = adx - adx_5_ago > 5   # 5 candle-এ 5 point rise

            if adx_rising and adx < self.adx_trend:
                return 'BREAKOUT'

        if adx >= self.adx_trend:
            return 'TRENDING'
        return 'RANGING'

    def _detect_direction(self, last) -> str:
        """EMA + MA alignment দিয়ে direction"""
        price  = float(last.get('close', 0))
        ema21  = last.get('ema_21')
        sma50  = last.get('sma_50')
        sma200 = last.get('sma_200')

        bullish_count = 0
        bearish_count = 0

        if ema21 and price > float(ema21):  bullish_count += 1
        elif ema21:                          bearish_count += 1

        if sma50 and price > float(sma50):  bullish_count += 1
        elif sma50:                          bearish_count += 1

        if sma200 and price > float(sma200): bullish_count += 1
        elif sma200:                          bearish_count += 1

        if bullish_count >= 2:   return 'BULLISH'
        if bearish_count >= 2:   return 'BEARISH'
        return 'NEUTRAL'

    def _detect_strength(self, last) -> str:
        """ADX value দিয়ে trend strength"""
        adx = float(last.get('adx', 0))
        if adx >= self.adx_strong:  return 'STRONG'
        if adx >= self.adx_trend:   return 'MODERATE'
        return 'WEAK'

    def _detect_volatility(self, df: pd.DataFrame, last) -> str:
        """ATR vs historical average দিয়ে volatility"""
        atr     = float(last.get('atr', 0))
        atr_avg = float(df['atr'].mean())

        if atr_avg == 0:
            return 'NORMAL'

        ratio = atr / atr_avg
        if ratio >= self.atr_high:   return 'HIGH'
        if ratio <= self.atr_low:    return 'LOW'
        return 'NORMAL'

    # ─────────────────────────────────────────────
    # STRATEGY SUGGESTION
    # ─────────────────────────────────────────────

    def _suggest_strategy(
        self, regime: str, direction: str,
        strength: str, volatility: str
    ) -> dict:
        """
        Regime + Direction + Strength + Volatility দেখে
        AI-এর জন্য strategy suggestion তৈরি করো
        """
        # Risk multiplier — volatility অনুযায়ী position size adjust
        risk_mult = {
            'HIGH':   0.5,   # high volatility → half size
            'NORMAL': 1.0,
            'LOW':    0.8,   # low volatility → tighter SL possible
        }.get(volatility, 1.0)

        if regime == 'RANGING':
            return {
                'type':        'RANGE',
                'action':      'Buy near support, Sell near resistance',
                'avoid':       'Breakout trades — likely false breakouts',
                'risk_mult':   risk_mult,
                'note':        'ADX < 20: No strong trend. Range-bound strategy.',
            }

        if regime == 'BREAKOUT':
            return {
                'type':        'WAIT',
                'action':      'Watch for confirmed breakout',
                'avoid':       'Entering before confirmation',
                'risk_mult':   risk_mult * 0.5,
                'note':        'ADX rising: Market transitioning. Wait for direction.',
            }

        # TRENDING
        if direction == 'BULLISH':
            if strength == 'STRONG':
                return {
                    'type':      'TREND_FOLLOW',
                    'action':    'Buy on pullbacks to EMA/Support',
                    'avoid':     'Counter-trend sells',
                    'risk_mult': risk_mult,
                    'note':      'Strong bullish trend. Only buy setups.',
                }
            return {
                'type':      'TREND_FOLLOW',
                'action':    'Buy with confirmation (pattern + S/R)',
                'avoid':     'Selling against moderate trend',
                'risk_mult': risk_mult * 0.8,
                'note':      'Moderate bullish trend. Wait for strong setups.',
            }

        if direction == 'BEARISH':
            if strength == 'STRONG':
                return {
                    'type':      'TREND_FOLLOW',
                    'action':    'Sell on pullbacks to EMA/Resistance',
                    'avoid':     'Counter-trend buys',
                    'risk_mult': risk_mult,
                    'note':      'Strong bearish trend. Only sell setups.',
                }
            return {
                'type':      'TREND_FOLLOW',
                'action':    'Sell with confirmation (pattern + S/R)',
                'avoid':     'Buying against moderate trend',
                'risk_mult': risk_mult * 0.8,
                'note':      'Moderate bearish trend. Wait for strong setups.',
            }

        return {
            'type':      'WAIT',
            'action':    'No clear direction. Stand aside.',
            'avoid':     'Trading in unclear conditions',
            'risk_mult': 0.5,
            'note':      'Neutral direction. Best to wait.',
        }

    # ─────────────────────────────────────────────
    # SUMMARY
    # ─────────────────────────────────────────────

    def print_summary(self, result: dict):
        s = result['strategy']
        print("\n" + "═" * 52)
        print("  🌐  MARKET REGIME  (Day 8)")
        print("═" * 52)
        print(f"  Regime       :  {result['regime']}")
        print(f"  Direction    :  {result['direction']}")
        print(f"  Strength     :  {result['strength']}")
        print(f"  Volatility   :  {result['volatility']}")
        print()
        print(f"  ADX (14)     :  {result['adx']:.1f}  "
              f"({'trending' if result['adx'] >= 20 else 'ranging'})")
        print(f"  ATR          :  {result['atr']:.5f}  "
              f"(avg: {result['atr_avg']:.5f})")
        print()
        print(f"  ── Strategy Suggestion ──")
        print(f"  Type         :  {s['type']}")
        print(f"  Action       :  {s['action']}")
        print(f"  Avoid        :  {s['avoid']}")
        print(f"  Risk Mult    :  {s['risk_mult']}x  "
              f"({'reduce size' if s['risk_mult'] < 1 else 'normal size'})")
        print(f"  Note         :  {s['note']}")
        print("═" * 52 + "\n")

    def get_ai_context(self, result: dict) -> dict:
        """Day 9 — Decision Brain-এর জন্য context"""
        return {
            'market_regime':    result['regime'],
            'market_direction': result['direction'],
            'trend_strength':   result['strength'],
            'volatility':       result['volatility'],
            'adx':              result['adx'],
            'strategy_type':    result['strategy']['type'],
            'risk_multiplier':  result['strategy']['risk_mult'],
            'strategy_note':    result['strategy']['note'],
        }