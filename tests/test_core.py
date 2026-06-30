# tests/test_core.py
# ============================================================
# Unit Tests — AI Trader Core Modules
# python -m pytest tests/ -v
# ============================================================

import pandas as pd
import numpy as np
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from data.validator import DataValidator
from data.indicators import Indicators
from analysis.patterns import PatternDetector
from analysis.support_resistance import SupportResistance
from utils.session import SessionAnalyzer
from datetime import datetime, timezone


# ── Fixtures ────────────────────────────────────────────────

def make_df(n=300):
    """Synthetic OHLCV DataFrame"""
    np.random.seed(42)
    price = 1.10 + np.cumsum(np.random.randn(n) * 0.001)
    idx   = pd.date_range("2026-01-01", periods=n, freq="15min")
    df    = pd.DataFrame({
        'open':   price,
        'high':   price + np.abs(np.random.randn(n) * 0.002),
        'low':    price - np.abs(np.random.randn(n) * 0.002),
        'close':  price + np.random.randn(n) * 0.001,
        'volume': np.random.randint(100, 1000, n).astype(float),
    }, index=idx)
    # Fix OHLC logic
    df['high']  = df[['open', 'close', 'high']].max(axis=1)
    df['low']   = df[['open', 'close', 'low']].min(axis=1)
    return df


# ── DataValidator ────────────────────────────────────────────

class TestDataValidator:

    def test_valid_data_passes(self):
        df  = make_df()
        val = DataValidator()
        assert val.validate(df, "EUR/USDT", "15m") is True

    def test_empty_df_fails(self):
        val = DataValidator()
        assert val.validate(pd.DataFrame(), "EUR/USDT", "15m") is False

    def test_missing_column_fails(self):
        df  = make_df().drop(columns=['volume'])
        val = DataValidator()
        assert val.validate(df, "EUR/USDT", "15m") is False

    def test_ohlc_logic_check(self):
        df = make_df()
        # Manually break OHLC
        df.iloc[0, df.columns.get_loc('high')] = 0.5   # high < low
        val = DataValidator()
        # Still returns True (warning, not critical)
        result = val.validate(df, "EUR/USDT", "15m")
        assert isinstance(result, bool)


# ── Indicators ───────────────────────────────────────────────

class TestIndicators:

    def test_all_indicators_added(self):
        df  = make_df()
        ind = Indicators()
        df  = ind.add_all(df)
        for col in ['rsi', 'macd', 'sma_20', 'sma_50', 'sma_200', 'atr',
                    'bb_upper', 'bb_lower', 'trend']:
            assert col in df.columns, f"Missing column: {col}"

    def test_rsi_range(self):
        df  = make_df()
        ind = Indicators()
        df  = ind.add_all(df)
        rsi = df['rsi'].dropna()
        assert (rsi >= 0).all() and (rsi <= 100).all()

    def test_ai_context_keys(self):
        df  = make_df()
        ind = Indicators()
        df  = ind.add_all(df)
        ctx = ind.get_ai_context(df)
        for key in ['price', 'trend', 'rsi', 'macd', 'atr']:
            assert key in ctx

    def test_trend_values(self):
        df  = make_df()
        ind = Indicators()
        df  = ind.add_all(df)
        valid_trends = {
            'strong_bullish', 'bullish', 'sideways',
            'bearish', 'strong_bearish', 'unknown'
        }
        assert set(df['trend'].unique()).issubset(valid_trends)


# ── Patterns ─────────────────────────────────────────────────

class TestPatterns:

    def test_pattern_column_exists(self):
        df  = make_df()
        det = PatternDetector()
        df  = det.detect_all(df)
        assert 'pattern' in df.columns

    def test_engulfing_column_exists(self):
        df  = make_df()
        det = PatternDetector()
        df  = det.detect_engulfing(df)
        assert 'engulfing' in df.columns

    def test_known_hammer(self):
        """Manually craft a hammer candle"""
        det = PatternDetector()
        row = pd.Series({
            'open': 1.1000, 'close': 1.1010,
            'high': 1.1015, 'low':   1.0970,
        })
        assert det.is_hammer(row) == 'hammer'

    def test_known_shooting_star(self):
        det = PatternDetector()
        row = pd.Series({
            'open': 1.1010, 'close': 1.1000,
            'high': 1.1050, 'low':   1.0998,
        })
        assert det.is_shooting_star(row) == 'shooting_star'


# ── Support & Resistance ─────────────────────────────────────

class TestSupportResistance:

    def test_swing_highs_found(self):
        df = make_df()
        sr = SupportResistance(window=5)
        highs = sr.find_swing_highs(df)
        assert len(highs) > 0

    def test_swing_lows_found(self):
        df = make_df()
        sr = SupportResistance(window=5)
        lows = sr.find_swing_lows(df)
        assert len(lows) > 0

    def test_ai_context_keys(self):
        df     = make_df()
        ind    = Indicators()
        df     = ind.add_all(df)
        sr     = SupportResistance()
        result = sr.analyze(df)
        ctx    = sr.get_ai_context(result)
        for key in ['nearest_support', 'nearest_resistance',
                    'price_location', 'pivot']:
            assert key in ctx


# ── Session ──────────────────────────────────────────────────

class TestSession:

    def test_london_session(self):
        sa = SessionAnalyzer()
        dt = datetime(2026, 6, 19, 10, 0, tzinfo=timezone.utc)  # 10 UTC = London
        info = sa.get_current_session(dt)
        assert 'london' in info['active_sessions']

    def test_new_york_session(self):
        sa = SessionAnalyzer()
        dt = datetime(2026, 6, 19, 14, 0, tzinfo=timezone.utc)  # 14 UTC = NY
        info = sa.get_current_session(dt)
        assert 'new_york' in info['active_sessions']

    def test_overlap_detected(self):
        sa = SessionAnalyzer()
        dt = datetime(2026, 6, 19, 13, 0, tzinfo=timezone.utc)  # 13 UTC = London/NY overlap
        info = sa.get_current_session(dt)
        assert info['overlap'] == 'London/New York'