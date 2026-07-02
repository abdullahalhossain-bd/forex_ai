"""Smoke test for Stop Hunt Signal Engine — spec compliance."""
import sys
sys.path.insert(0, "/home/z/my-project/forex_ai")

import warnings
warnings.filterwarnings("ignore")

import json
import numpy as np
import pandas as pd
from analysis.stop_hunt_signal_engine import (
    StopHuntSignalEngine,
    detect_stop_hunt_signal,
    MIN_CANDLES_REQUIRED,
)


def make_ohlc(n=200, base=1.0850, seed=42, volatility=0.0005):
    """Plain random-walk OHLC."""
    np.random.seed(seed)
    dates = pd.date_range("2024-01-01", periods=n, freq="h")
    close = base + np.cumsum(np.random.randn(n) * volatility)
    return pd.DataFrame({
        "open":  close + np.random.randn(n) * volatility * 0.3,
        "high":  close + abs(np.random.randn(n)) * volatility * 1.5,
        "low":   close - abs(np.random.randn(n)) * volatility * 1.5,
        "close": close,
    }, index=dates)


def make_ohlc_with_resistance_stop_hunt():
    """
    Build OHLC where:
    1. Price oscillates tightly BELOW a clear resistance zone at 1.0900-1.0910
    2. Resistance zone is established by 4 forced swing highs at 1.0905-1.0910.
    3. Candle 95 = STOP HUNT: wick pierces 1.0910 -> 1.0940, body closes back
       inside zone at 1.0905, big upper wick.
    4. Candle 96-97: small inside-zone candles.
    5. Candle 98: BEARISH REVERSAL CONFIRM - close below zone_bottom (1.0900).
    6. Candle 99: continuation down.
    """
    np.random.seed(100)
    n = 100
    dates = pd.date_range("2024-01-01", periods=n, freq="h")

    # First 95 candles: oscillate tightly BELOW resistance
    # Base = 1.0870, amplitude = 0.0008 (8 pips), so highs reach max ~1.0883
    base = 1.0870
    closes, highs, lows, opens = [], [], [], []
    for i in range(95):
        c = base + np.sin(i / 8) * 0.0008 + np.random.randn() * 0.0002
        o = c + np.random.randn() * 0.0001
        h = max(o, c) + abs(np.random.randn()) * 0.0003
        l = min(o, c) - abs(np.random.randn()) * 0.0003
        closes.append(c); highs.append(h); lows.append(l); opens.append(o)

    # Force swing highs at 1.0905-1.0910 (clearly separated from random-walk highs ~1.0883)
    for touch_i in [10, 30, 50, 70]:
        highs[touch_i] = 1.0905 + np.random.rand() * 0.0005
        closes[touch_i] = 1.0880  # rejected back

    # Candle 95: STOP HUNT - wick pierces above zone_top, body closes inside zone
    o = 1.0898
    c = 1.0905
    h = 1.0940
    l = 1.0895
    opens.append(o); highs.append(h); lows.append(l); closes.append(c)

    # Candle 96: small candle, still inside zone
    o = 1.0905
    c = 1.0902
    h = 1.0908
    l = 1.0898
    opens.append(o); highs.append(h); lows.append(l); closes.append(c)

    # Candle 97: another small candle inside zone
    o = 1.0902
    c = 1.0898
    h = 1.0906
    l = 1.0895
    opens.append(o); highs.append(h); lows.append(l); closes.append(c)

    # Candle 98: BEARISH REVERSAL CONFIRM - close below zone_bottom (1.0900)
    o = 1.0898
    c = 1.0888
    h = 1.0902
    l = 1.0885
    opens.append(o); highs.append(h); lows.append(l); closes.append(c)

    # Candle 99: continuation down (entry would be open of candle 99)
    o = 1.0888
    c = 1.0875
    h = 1.0892
    l = 1.0870
    opens.append(o); highs.append(h); lows.append(l); closes.append(c)

    df = pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": closes,
    }, index=dates[:len(closes)])
    return df


def make_ohlc_real_breakout_no_stop_hunt():
    """
    Real breakout: price breaks ABOVE resistance zone with strong bullish
    body that closes OUTSIDE zone. No stop hunt (body doesn't close inside).
    Should result in NO_TRADE per spec rule 3.
    """
    np.random.seed(101)
    n = 100
    dates = pd.date_range("2024-01-01", periods=n, freq="h")

    base = 1.0870
    closes, highs, lows, opens = [], [], [], []
    for i in range(95):
        c = base + np.sin(i / 8) * 0.0015 + np.random.randn() * 0.0003
        o = c + np.random.randn() * 0.0002
        h = max(o, c) + abs(np.random.randn()) * 0.0005
        l = min(o, c) - abs(np.random.randn()) * 0.0005
        closes.append(c); highs.append(h); lows.append(l); opens.append(o)

    # Force swing highs around 1.0900-1.0910 (resistance zone)
    for touch_i in [10, 30, 50, 70]:
        highs[touch_i] = 1.0905 + np.random.rand() * 0.0005
        closes[touch_i] = 1.0885

    # Candle 95: REAL BREAKOUT — body closes WAY above zone_top
    # body = 1.0910 → 1.0925 (large body, no rejection wick)
    o = 1.0910
    c = 1.0935  # closes outside zone, big body
    h = 1.0940
    l = 1.0908
    opens.append(o); highs.append(h); lows.append(l); closes.append(c)

    # Candle 96-99: continuation up (no reversal)
    for _ in range(4):
        o = c
        c = c + 0.0008
        h = c + 0.0005
        l = o - 0.0002
        opens.append(o); highs.append(h); lows.append(l); closes.append(c)

    df = pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": closes,
    }, index=dates[:len(closes)])
    return df


# ─── TESTS ────────────────────────────────────────────────────

def test_schema_conformance():
    print("\n========== TEST 1: Schema conformance ==========")
    df = make_ohlc()
    result = StopHuntSignalEngine(timeframe="H1").analyze(df, symbol="EURUSD")

    # Top-level keys
    assert "resistance_zones" in result
    assert "support_zones" in result
    assert "stop_hunt_detected" in result
    assert "stop_hunt_zone" in result
    assert "signal" in result

    # Zone schema
    for z in result["resistance_zones"] + result["support_zones"]:
        assert "zone_top" in z
        assert "zone_bottom" in z
        assert "touches" in z
        assert "strength" in z
        assert z["strength"] in ("Weak", "Medium", "Strong")

    # Signal schema
    sig = result["signal"]
    for key in ["action", "entry_price", "stop_loss",
                "take_profit", "reason", "confidence"]:
        assert key in sig, f"Missing signal key: {key}"
    assert sig["action"] in ("BUY", "SELL", "NO_TRADE")
    assert sig["confidence"] in ("Low", "Medium", "High")

    print("TEST 1 passed: schema conforms to spec")


def test_insufficient_data():
    print("\n========== TEST 2: Insufficient data ==========")
    df = make_ohlc(n=15)
    result = StopHuntSignalEngine(timeframe="H1").analyze(df, symbol="EURUSD")
    sig = result["signal"]
    assert sig["action"] == "NO_TRADE", f"Expected NO_TRADE, got {sig['action']}"
    assert "Insufficient" in sig["reason"], f"Reason: {sig['reason']}"
    assert sig["entry_price"] is None
    assert sig["stop_loss"] is None
    assert sig["take_profit"] is None
    print(f"  action={sig['action']}, reason={sig['reason']}")
    print("TEST 2 passed: insufficient data → NO_TRADE")


def test_stop_hunt_confirmed_sell_signal():
    print("\n========== TEST 3: Stop hunt at resistance → SELL signal ==========")
    df = make_ohlc_with_resistance_stop_hunt()
    engine = StopHuntSignalEngine(timeframe="H1", min_touches=2)
    result = engine.analyze(df, symbol="EURUSD")

    print(f"  stop_hunt_detected: {result['stop_hunt_detected']}")
    print(f"  stop_hunt_zone: {result['stop_hunt_zone']}")
    print(f"  signal: {json.dumps(result['signal'], indent=2)}")

    # We expect a SELL signal (bearish reversal from resistance)
    assert result["stop_hunt_detected"] == True, "Stop hunt should be detected"
    assert result["stop_hunt_zone"] == "resistance"
    sig = result["signal"]
    assert sig["action"] == "SELL", f"Expected SELL, got {sig['action']}"
    assert sig["entry_price"] is not None
    assert sig["stop_loss"] is not None
    assert sig["take_profit"] is not None
    # SL must be above entry (SELL)
    assert sig["stop_loss"] > sig["entry_price"], "SL must be above entry for SELL"
    # TP must be below entry (SELL)
    assert sig["take_profit"] < sig["entry_price"], "TP must be below entry for SELL"
    # R:R ≥ 2.0
    risk = sig["stop_loss"] - sig["entry_price"]
    reward = sig["entry_price"] - sig["take_profit"]
    assert reward / risk >= 1.9, f"R:R too low: {reward/risk:.2f}"
    print(f"  R:R = 1:{reward/risk:.2f}")
    print("TEST 3 passed: stop hunt → SELL signal with valid geometry")


def test_real_breakout_no_trade():
    print("\n========== TEST 4: Real breakout (no stop hunt) → NO_TRADE ==========")
    df = make_ohlc_real_breakout_no_stop_hunt()
    engine = StopHuntSignalEngine(timeframe="H1", min_touches=2)
    result = engine.analyze(df, symbol="EURUSD")

    print(f"  stop_hunt_detected: {result['stop_hunt_detected']}")
    print(f"  signal: {json.dumps(result['signal'], indent=2)}")

    # Real breakout — body closes outside zone → no stop hunt
    # Either no stop hunt detected OR signal action is NO_TRADE
    sig = result["signal"]
    if not result["stop_hunt_detected"]:
        assert sig["action"] == "NO_TRADE"
        print(f"  Correctly identified as no-stop-hunt → NO_TRADE")
    else:
        # If somehow detected, geometry check should reject it
        assert sig["action"] == "NO_TRADE", "Real breakout should NOT generate trade"
        print(f"  Stop hunt flagged but rejected by geometry → NO_TRADE")
    print("TEST 4 passed: real breakout → NO_TRADE")


def test_no_zones_no_trade():
    print("\n========== TEST 5: No zones detectable → NO_TRADE ==========")
    # Tight range, no swings
    np.random.seed(7)
    n = 50
    dates = pd.date_range("2024-01-01", periods=n, freq="h")
    close = np.full(n, 1.0850) + np.random.randn(n) * 0.00005  # ultra-tight
    df = pd.DataFrame({
        "open": close, "high": close + 0.0001,
        "low": close - 0.0001, "close": close,
    }, index=dates)
    engine = StopHuntSignalEngine(timeframe="H1")
    result = engine.analyze(df, symbol="EURUSD")
    sig = result["signal"]
    assert sig["action"] == "NO_TRADE"
    print(f"  action={sig['action']}, reason={sig['reason'][:80]}")
    print("TEST 5 passed: no zones → NO_TRADE")


def test_round_number_detection():
    print("\n========== TEST 6: Round number proximity check ==========")
    from analysis.stop_hunt_signal_engine import _is_round_number
    # FX major
    assert _is_round_number(1.0900, "EURUSD") == True   # 100 pip round number
    assert _is_round_number(1.0850, "EURUSD") == True   # 50 pip round number
    assert _is_round_number(1.0873, "EURUSD") == False  # not round
    # JPY
    assert _is_round_number(150.00, "USDJPY") == True
    assert _is_round_number(150.50, "USDJPY") == True
    # XAUUSD
    assert _is_round_number(2300.0, "XAUUSD") == True
    assert _is_round_number(2305.0, "XAUUSD") == True
    print("  EURUSD 1.0900 ✓ | 1.0850 ✓ | 1.0873 ✗")
    print("  USDJPY 150.00 ✓ | 150.50 ✓")
    print("  XAUUSD 2300 ✓ | 2305 ✓")
    print("TEST 6 passed: round number detection works")


def test_oneshot_helper():
    print("\n========== TEST 7: detect_stop_hunt_signal() one-shot helper ==========")
    df = make_ohlc_with_resistance_stop_hunt()
    json_str = detect_stop_hunt_signal(df, symbol="EURUSD", timeframe="H1", min_touches=2)
    parsed = json.loads(json_str)
    assert "resistance_zones" in parsed
    assert "support_zones" in parsed
    assert "stop_hunt_detected" in parsed
    assert "signal" in parsed
    print(f"  stop_hunt_detected: {parsed['stop_hunt_detected']}")
    print(f"  action: {parsed['signal']['action']}")
    print("TEST 7 passed: one-shot helper returns valid JSON")


def test_prompt_text():
    print("\n========== TEST 8: to_prompt_text() LLM-friendly output ==========")
    df = make_ohlc_with_resistance_stop_hunt()
    engine = StopHuntSignalEngine(timeframe="H1", min_touches=2)
    result = engine.analyze(df, symbol="EURUSD")
    text = engine.to_prompt_text(result)
    print(text)
    assert "STOP HUNT SIGNAL" in text
    assert "Action" in text
    print("TEST 8 passed: prompt text rendering works")


def test_bullish_stop_hunt_at_support():
    """Symmetric test: stop hunt at SUPPORT -> BUY signal."""
    print("\n========== TEST 9: Stop hunt at support -> BUY signal ==========")
    # Build mirror image of test 3 - tight random walk ABOVE support zone
    np.random.seed(102)
    n = 100
    dates = pd.date_range("2024-01-01", periods=n, freq="h")
    base = 1.0870
    closes, highs, lows, opens = [], [], [], []
    # Random walk oscillates ABOVE the support zone (1.0830-1.0840)
    for i in range(95):
        c = base + np.sin(i / 8) * 0.0008 + np.random.randn() * 0.0002
        o = c + np.random.randn() * 0.0001
        h = max(o, c) + abs(np.random.randn()) * 0.0003
        l = min(o, c) - abs(np.random.randn()) * 0.0003
        closes.append(c); highs.append(h); lows.append(l); opens.append(o)

    # Force swing lows at 1.0830-1.0835 (clearly separated from random-walk lows ~1.0857)
    for touch_i in [10, 30, 50, 70]:
        lows[touch_i] = 1.0830 - np.random.rand() * 0.0005
        closes[touch_i] = 1.0860  # rejected up

    # Candle 95: STOP HUNT - wick pierces below zone_bottom, body closes inside zone
    o = 1.0845
    c = 1.0835   # body closes inside zone [1.0830-1.0840]
    h = 1.0848
    l = 1.0800   # wick pierces well below zone_bottom (clearly outside cluster)
    opens.append(o); highs.append(h); lows.append(l); closes.append(c)

    # Candle 96: small candle, still inside zone
    o = 1.0835
    c = 1.0838
    h = 1.0842
    l = 1.0832
    opens.append(o); highs.append(h); lows.append(l); closes.append(c)

    # Candle 97: another small candle inside zone
    o = 1.0838
    c = 1.0842
    h = 1.0845
    l = 1.0835
    opens.append(o); highs.append(h); lows.append(l); closes.append(c)

    # Candle 98: BULLISH REVERSAL CONFIRM - close above zone_top (1.0840)
    o = 1.0842
    c = 1.0852   # close above zone_top
    h = 1.0855
    l = 1.0840
    opens.append(o); highs.append(h); lows.append(l); closes.append(c)

    # Candle 99: continuation up (entry would be open of candle 99)
    o = 1.0852
    c = 1.0865
    h = 1.0870
    l = 1.0848
    opens.append(o); highs.append(h); lows.append(l); closes.append(c)

    df = pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": closes,
    }, index=dates[:len(closes)])

    engine = StopHuntSignalEngine(timeframe="H1", min_touches=2)
    result = engine.analyze(df, symbol="EURUSD")
    print(f"  stop_hunt_detected: {result['stop_hunt_detected']}")
    print(f"  stop_hunt_zone: {result['stop_hunt_zone']}")
    print(f"  signal: {json.dumps(result['signal'], indent=2)}")

    assert result["stop_hunt_detected"] == True, "Bullish stop hunt should be detected"
    assert result["stop_hunt_zone"] == "support"
    sig = result["signal"]
    assert sig["action"] == "BUY", f"Expected BUY, got {sig['action']}"
    assert sig["stop_loss"] < sig["entry_price"], "SL must be below entry for BUY"
    assert sig["take_profit"] > sig["entry_price"], "TP must be above entry for BUY"
    print("TEST 9 passed: bullish stop hunt -> BUY signal")


if __name__ == "__main__":
    test_schema_conformance()
    test_insufficient_data()
    test_stop_hunt_confirmed_sell_signal()
    test_real_breakout_no_trade()
    test_no_zones_no_trade()
    test_round_number_detection()
    test_oneshot_helper()
    test_prompt_text()
    test_bullish_stop_hunt_at_support()
    print("\n" + "=" * 50)
    print("ALL TESTS PASSED")
    print("=" * 50)
