"""Smoke test for upgraded S/R Zone detection module."""
import sys
sys.path.insert(0, "/home/z/my-project/forex_ai")

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
from analysis.support_resistance import SupportResistance, detect_zones_for_llm


def make_synthetic_ohlc(n=300, base=1.0850, seed=42):
    """Create realistic OHLC with clear S/R clusters."""
    np.random.seed(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="h")
    t = np.arange(n)
    swing = np.sin(t / 12) * 0.003 + np.sin(t / 30) * 0.005
    noise = np.random.randn(n) * 0.0004
    close = base + swing + np.cumsum(noise) * 0.01

    close = np.where(close > 1.0895, 1.0895 - np.random.rand() * 0.001, close)
    close = np.where(close < 1.0805, 1.0805 + np.random.rand() * 0.001, close)

    high = close + abs(np.random.randn(n)) * 0.0008
    low = close - abs(np.random.randn(n)) * 0.0008
    opn = close + np.random.randn(n) * 0.0002

    return pd.DataFrame({"open": opn, "high": high, "low": low, "close": close}, index=dates)


def test_basic():
    print("\n========== TEST 1: Basic zone detection ==========")
    df = make_synthetic_ohlc()
    sr = SupportResistance(timeframe="H1")
    result = sr.analyze(df, symbol="EURUSD")
    sr.get_summary(result)
    assert "support_zones" in result
    assert "resistance_zones" in result
    print("TEST 1 passed: zones detected with zone_top/zone_bottom")


def test_json_output():
    print("\n========== TEST 2: JSON output (LLM Agent) ==========")
    df = make_synthetic_ohlc()
    json_str = detect_zones_for_llm(df, symbol="EURUSD", timeframe="H1")
    print(json_str)
    import json
    parsed = json.loads(json_str)
    assert "resistance_zones" in parsed
    assert "support_zones" in parsed
    assert "current_price" in parsed
    for z in parsed["resistance_zones"] + parsed["support_zones"]:
        assert "zone_top" in z and "zone_bottom" in z and "touches" in z and "strength" in z
        assert z["strength"] in ("Weak", "Medium", "Strong")
    print("TEST 2 passed: JSON conforms to spec schema")


def test_max_zones_filter():
    print("\n========== TEST 3: Max 3 zones per side (spec rule 5) ==========")
    df = make_synthetic_ohlc(n=500)
    sr = SupportResistance(timeframe="H1", max_zones_per_side=3)
    result = sr.analyze(df, symbol="EURUSD")
    print(f"Support zones returned: {len(result['support_zones'])}")
    print(f"Resistance zones returned: {len(result['resistance_zones'])}")
    assert len(result["support_zones"]) <= 3
    assert len(result["resistance_zones"]) <= 3
    print("TEST 3 passed: max 3 zones per side enforced")


def test_tf_adaptive_window():
    print("\n========== TEST 4: Timeframe-adaptive swing_window ==========")
    df = make_synthetic_ohlc()
    for tf, expected_w in [("M5", 3), ("M15", 4), ("H1", 4), ("H4", 5), ("D1", 5)]:
        sr = SupportResistance(timeframe=tf)
        assert sr.swing_window == expected_w, f"TF={tf} expected={expected_w}, got {sr.swing_window}"
        print(f"  TF={tf} -> swing_window={sr.swing_window}")
    print("TEST 4 passed: TF adaptive window correct")


def test_backward_compat():
    print("\n========== TEST 5: Backward-compat ==========")
    df = make_synthetic_ohlc()
    sr = SupportResistance(timeframe="H1")
    result = sr.analyze(df, symbol="EURUSD")
    ctx = sr.get_ai_context(result)
    for key in ["nearest_support","nearest_resistance","support_strength",
                "resistance_strength","dist_to_support_pips","dist_to_resistance_pips",
                "price_location","pivot","R1","S1","role_reversal",
                "support_zones","resistance_zones","zone_summary","zones_json"]:
        assert key in ctx, f"Missing key: {key}"
    print(f"  nearest_support: {ctx['nearest_support']}")
    print(f"  nearest_resistance: {ctx['nearest_resistance']}")
    print(f"  price_location: {ctx['price_location']}")
    print(f"  zones_json length: {len(ctx['zones_json'])} chars")
    print("TEST 5 passed: backward-compat preserved + new keys added")


def test_xau_pip_value():
    print("\n========== TEST 6: XAUUSD pip value ==========")
    np.random.seed(7)
    n = 200
    dates = pd.date_range("2024-01-01", periods=n, freq="h")
    base = 2300.0
    close = base + np.cumsum(np.random.randn(n) * 0.5)
    df = pd.DataFrame({
        "open": close, "high": close + 1.5, "low": close - 1.5, "close": close
    }, index=dates)
    sr = SupportResistance(timeframe="H1")
    result = sr.analyze(df, symbol="XAUUSD")
    print(f"  XAUUSD support zones: {len(result['support_zones'])}")
    print("TEST 6 passed: XAUUSD handled without crash")


def test_insufficient_candles():
    print("\n========== TEST 7: Insufficient candles ==========")
    df = make_synthetic_ohlc(n=10)
    sr = SupportResistance(timeframe="H1")
    result = sr.analyze(df, symbol="EURUSD")
    assert result["support_zones"] == []
    assert result["resistance_zones"] == []
    print("TEST 7 passed: handles insufficient candles gracefully")


def test_rejection_validation():
    print("\n========== TEST 8: Rejection candle validation ==========")
    df = make_synthetic_ohlc()
    sr = SupportResistance(timeframe="H1", wick_body_ratio=1.5)
    pin_bar = pd.Series({
        "open": 1.0900, "high": 1.0950, "low": 1.0898, "close": 1.0902
    })
    assert sr._is_valid_rejection(pin_bar, direction="resistance") == True
    assert sr._is_valid_rejection(pin_bar, direction="support") == False
    print("  Pin bar rejection validated (wick >= 1.5x body)")
    print("TEST 8 passed: rejection wick validation works")


if __name__ == "__main__":
    test_basic()
    test_json_output()
    test_max_zones_filter()
    test_tf_adaptive_window()
    test_backward_compat()
    test_xau_pip_value()
    test_insufficient_candles()
    test_rejection_validation()
    print("\n" + "=" * 50)
    print("ALL TESTS PASSED")
    print("=" * 50)
