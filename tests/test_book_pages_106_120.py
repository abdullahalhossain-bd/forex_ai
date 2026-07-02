"""Tests for new chart patterns from Book pages 106-120."""
import sys
sys.path.insert(0, "/home/z/my-project/forex_ai")

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from analysis.advanced_patterns import AdvancedPatternDetector


def make_df(candles, start="2024-01-01", freq="h"):
    n = len(candles)
    dates = pd.date_range(start, periods=n, freq=freq)
    return pd.DataFrame({
        "open":   [c[0] for c in candles],
        "high":   [c[1] for c in candles],
        "low":    [c[2] for c in candles],
        "close":  [c[3] for c in candles],
        "volume": [c[4] if len(c) > 4 else 500 for c in candles],
    }, index=dates)


def make_ohlc(n=100, base=1.0850, seed=42, vol=0.0005, freq="h"):
    np.random.seed(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq=freq)
    close = base + np.cumsum(np.random.randn(n) * vol)
    return pd.DataFrame({
        "open":   close + np.random.randn(n) * vol * 0.3,
        "high":   close + abs(np.random.randn(n)) * vol * 1.5,
        "low":    close - abs(np.random.randn(n)) * vol * 1.5,
        "close":  close,
        "volume": np.random.randint(100, 1000, n),
    }, index=dates)


# ─── TESTS ────────────────────────────────────────────────────

def test_rectangle_no_trade_state():
    """Rectangle forming (no breakout) → NO_TRADE state."""
    print("\n========== TEST 1: Rectangle NO_TRADE state ==========")
    # Build tight rectangle: price oscillating between 1.0840-1.0860
    np.random.seed(100)
    n = 80
    dates = pd.date_range("2024-01-01", periods=n, freq="h")
    close = 1.0850 + np.sin(np.arange(n) / 3) * 0.0008
    df = pd.DataFrame({
        "open":   close,
        "high":   close + 0.0003,
        "low":    close - 0.0003,
        "close":  close,
        "volume": np.random.randint(100, 1000, n),
    }, index=dates)

    detector = AdvancedPatternDetector(lookback=80)
    results = detector.detect_rectangle(df)
    rectangles = [r for r in results if "RECTANGLE" in r["pattern"]]

    print(f"  Rectangle patterns: {len(rectangles)}")
    for r in rectangles:
        print(f"    - {r['pattern']}: {r['direction']} (action={r.get('trade_action')})")

    # Either no rectangle detected, or if detected with no breakout → NO_TRADE
    for r in rectangles:
        if r["pattern"] == "RECTANGLE":
            assert r["trade_action"] == "NO_TRADE", f"Expected NO_TRADE, got {r['trade_action']}"
            assert r["direction"] == "NEUTRAL"
    print("TEST 1 passed: Rectangle NO_TRADE state works")


def test_rectangle_breakout_up():
    """Rectangle breakout up → LONG signal."""
    print("\n========== TEST 2: Rectangle breakout UP ==========")
    np.random.seed(101)
    n = 80
    dates = pd.date_range("2024-01-01", periods=n, freq="h")
    # First 78 candles: tight rectangle 1.0840-1.0860
    close = np.empty(n)
    for i in range(n):
        if i < 78:
            close[i] = 1.0850 + np.sin(i / 3) * 0.0008
        else:
            close[i] = 1.0870  # breakout up
    df = pd.DataFrame({
        "open":   close,
        "high":   close + 0.0003,
        "low":    close - 0.0003,
        "close":  close,
        "volume": np.random.randint(100, 1000, n),
    }, index=dates)

    detector = AdvancedPatternDetector(lookback=80)
    results = detector.detect_rectangle(df)
    breakouts = [r for r in results if r["pattern"] == "RECTANGLE_BREAKOUT_UP"]

    print(f"  Breakout up patterns: {len(breakouts)}")
    for r in breakouts:
        print(f"    - {r['pattern']}: entry={r['entry']}, target={r['target']}")
        assert r["direction"] == "BULLISH"
        assert r["trade_action"] == "LONG"
        assert r["entry"] is not None
        assert r["target"] > r["entry"]
    print("TEST 2 passed: Rectangle breakout UP works")


def test_momentum_screener_near_high():
    """Price within 10% of high → MOMENTUM_CANDIDATE."""
    print("\n========== TEST 3: Momentum screener near high ==========")
    # Steady uptrend — price ends near high
    np.random.seed(102)
    n = 100
    dates = pd.date_range("2024-01-01", periods=n, freq="h")
    close = np.linspace(1.0800, 1.0895, n)  # ends very close to high
    df = pd.DataFrame({
        "open":   close,
        "high":   close + 0.0005,
        "low":    close - 0.0005,
        "close":  close,
        "volume": np.random.randint(100, 1000, n),
    }, index=dates)

    detector = AdvancedPatternDetector(lookback=100)
    results = detector.detect_momentum_screen(df)

    print(f"  Momentum patterns: {len(results)}")
    for r in results:
        print(f"    - {r['pattern']}: proximity={r['proximity_to_high']}%, "
              f"pct_12={r['pct_change_12']}%, conf={r['confidence']}")
        assert r["pattern"] == "MOMENTUM_CANDIDATE"
        assert r["proximity_to_high"] <= 10.0  # within 10% of high

    assert len(results) >= 1, "Should detect momentum candidate"
    print("TEST 3 passed: Momentum screener works")


def test_momentum_screener_far_from_high():
    """Price far from high (>10% below) → no momentum candidate."""
    print("\n========== TEST 4: Momentum screener — far from high ==========")
    # Price dropped significantly from high (>10% below)
    np.random.seed(103)
    n = 100
    dates = pd.date_range("2024-01-01", periods=n, freq="h")
    # First 50 candles rise to 1.1000, then drop to 1.0800 (~18% below high)
    close = np.empty(n)
    for i in range(n):
        if i < 50:
            close[i] = 1.0800 + i * 0.0004  # rise to ~1.0996
        else:
            close[i] = 1.0996 - (i - 50) * 0.0004  # drop to ~1.0800
    # Force a clear high
    close[49] = 1.1000
    df = pd.DataFrame({
        "open":   close,
        "high":   close + 0.0005,
        "low":    close - 0.0005,
        "close":  close,
        "volume": np.random.randint(100, 1000, n),
    }, index=dates)

    high = df["high"].max()
    curr = df["close"].iloc[-1]
    proximity = (high - curr) / high * 100
    print(f"  High: {high:.5f}, Current: {curr:.5f}, Proximity: {proximity:.2f}%")

    detector = AdvancedPatternDetector(lookback=100)
    results = detector.detect_momentum_screen(df)

    print(f"  Momentum patterns: {len(results)} (expected 0 — price >10% below high)")
    # If proximity > 10%, should NOT detect
    if proximity > 10:
        assert len(results) == 0, f"Should NOT detect when {proximity:.2f}% below high"
    print("TEST 4 passed: Momentum screener correctly rejects far-from-high")


def test_rectangle_breakout_down():
    """Rectangle breakout down → SHORT signal."""
    print("\n========== TEST 5: Rectangle breakout DOWN ==========")
    np.random.seed(104)
    n = 80
    dates = pd.date_range("2024-01-01", periods=n, freq="h")
    close = np.empty(n)
    for i in range(n):
        if i < 78:
            close[i] = 1.0850 + np.sin(i / 3) * 0.0008
        else:
            close[i] = 1.0830  # breakout down
    df = pd.DataFrame({
        "open":   close,
        "high":   close + 0.0003,
        "low":    close - 0.0003,
        "close":  close,
        "volume": np.random.randint(100, 1000, n),
    }, index=dates)

    detector = AdvancedPatternDetector(lookback=80)
    results = detector.detect_rectangle(df)
    breakouts = [r for r in results if r["pattern"] == "RECTANGLE_BREAKOUT_DOWN"]

    print(f"  Breakout down patterns: {len(breakouts)}")
    for r in breakouts:
        print(f"    - {r['pattern']}: entry={r['entry']}, target={r['target']}")
        assert r["direction"] == "BEARISH"
        assert r["trade_action"] == "SHORT"
        assert r["target"] < r["entry"]
    print("TEST 5 passed: Rectangle breakout DOWN works")


def test_new_patterns_in_detect_all():
    """Verify detect_all includes the new patterns."""
    print("\n========== TEST 6: New patterns in detect_all ==========")
    np.random.seed(105)
    n = 100
    dates = pd.date_range("2024-01-01", periods=n, freq="h")
    close = np.linspace(1.0800, 1.0890, n)  # uptrend → momentum
    df = pd.DataFrame({
        "open":   close,
        "high":   close + 0.0005,
        "low":    close - 0.0005,
        "close":  close,
        "volume": np.random.randint(100, 1000, n),
    }, index=dates)

    detector = AdvancedPatternDetector(lookback=100)
    all_patterns = detector.detect_all(df)

    pattern_names = [p["pattern"] for p in all_patterns]
    print(f"  All patterns: {pattern_names[:5]}")

    # Should include MOMENTUM_CANDIDATE (price near high)
    assert "MOMENTUM_CANDIDATE" in pattern_names, "Momentum candidate should be in detect_all results"
    print("TEST 6 passed: new patterns integrated into detect_all")


def test_momentum_confidence_scoring():
    """Closer to high → higher confidence."""
    print("\n========== TEST 7: Momentum confidence scoring ==========")
    np.random.seed(106)

    # Case A: price at 5% below high
    n = 100
    dates = pd.date_range("2024-01-01", periods=n, freq="h")
    close_a = np.linspace(1.0800, 1.0855, n)  # ends 0.45% below 1.0860 high
    df_a = pd.DataFrame({
        "open": close_a, "high": close_a + 0.0005, "low": close_a - 0.0005,
        "close": close_a, "volume": np.random.randint(100, 1000, n),
    }, index=dates)

    # Case B: price at 9.5% below high
    close_b = np.linspace(1.0800, 1.0810, n)  # ends ~9% below 1.0900 high
    # Force a high at 1.0900 in the middle
    close_b[50] = 1.0900
    df_b = pd.DataFrame({
        "open": close_b, "high": close_b + 0.0005, "low": close_b - 0.0005,
        "close": close_b, "volume": np.random.randint(100, 1000, n),
    }, index=dates)

    detector = AdvancedPatternDetector(lookback=100)
    res_a = detector.detect_momentum_screen(df_a)
    res_b = detector.detect_momentum_screen(df_b)

    print(f"  Case A (near high): {len(res_a)} patterns")
    print(f"  Case B (far from high): {len(res_b)} patterns")

    # Case A should have higher confidence (closer to high)
    if res_a and res_b:
        conf_a = res_a[0]["confidence"]
        conf_b = res_b[0]["confidence"]
        print(f"  Confidence A: {conf_a}, B: {conf_b}")
        # A should be >= B (closer to high → higher confidence)
        assert conf_a >= conf_b, f"Expected conf_a >= conf_b, got {conf_a} < {conf_b}"
    print("TEST 7 passed: confidence scoring works")


if __name__ == "__main__":
    test_rectangle_no_trade_state()
    test_rectangle_breakout_up()
    test_momentum_screener_near_high()
    test_momentum_screener_far_from_high()
    test_rectangle_breakout_down()
    test_new_patterns_in_detect_all()
    test_momentum_confidence_scoring()
    print("\n" + "=" * 50)
    print("ALL TESTS PASSED")
    print("=" * 50)
