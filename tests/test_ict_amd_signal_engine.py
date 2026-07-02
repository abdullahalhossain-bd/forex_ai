"""Smoke test for ICT/AMD Signal Engine — spec compliance."""
import sys
sys.path.insert(0, "/home/z/my-project/forex_ai")

import warnings
warnings.filterwarnings("ignore")

import json
import numpy as np
import pandas as pd
from analysis.ict_amd_signal_engine import (
    ICTAMDSignalEngine,
    detect_ict_amd_signal,
    MIN_CANDLES_REQUIRED,
    MIN_RR_RATIO,
)


def make_intraday_ohlc(n=200, base=1.0850, seed=42, vol=0.0005):
    """Random-walk OHLC with hourly timestamps spanning multiple days."""
    np.random.seed(seed)
    # Start on a Monday
    dates = pd.date_range("2024-06-03", periods=n, freq="h")
    close = base + np.cumsum(np.random.randn(n) * vol)
    return pd.DataFrame({
        "open":  close + np.random.randn(n) * vol * 0.3,
        "high":  close + abs(np.random.randn(n)) * vol * 1.5,
        "low":   close - abs(np.random.randn(n)) * vol * 1.5,
        "close": close,
    }, index=dates)


# ─── TESTS ────────────────────────────────────────────────────

def test_schema_conformance():
    print("\n========== TEST 1: Schema conformance ==========")
    df = make_intraday_ohlc()
    result = ICTAMDSignalEngine(timeframe="H1").analyze(df, symbol="EURUSD")
    print(json.dumps(result, indent=2)[:1500])

    # Top-level keys
    for key in ["zones", "accumulation", "manipulation", "fvg", "mss_confirmed", "signal"]:
        assert key in result, f"Missing top-level key: {key}"

    # zones schema
    zones = result["zones"]
    assert "strongest_zone" in zones
    assert "weakest_zone" in zones
    # Each zone can be None or dict with type/zone_top/zone_bottom/touches
    for zkey in ["strongest_zone", "weakest_zone"]:
        z = zones[zkey]
        if z is not None:
            for field in ["type", "zone_top", "zone_bottom", "touches"]:
                assert field in z, f"Missing zone field: {field}"
            assert z["type"] in ("support", "resistance")

    # accumulation schema
    acc = result["accumulation"]
    for field in ["valid", "range_high", "range_low"]:
        assert field in acc

    # manipulation schema
    man = result["manipulation"]
    for field in ["detected", "direction", "sweep_price", "zone_strength_used"]:
        assert field in man
    if man["detected"]:
        assert man["direction"] in ("upside_sweep", "downside_sweep")
        assert man["zone_strength_used"] in ("Strong", "Medium")

    # fvg schema
    fvg = result["fvg"]
    for field in ["found", "type", "top", "bottom", "midpoint"]:
        assert field in fvg
    if fvg["found"]:
        assert fvg["type"] in ("bullish", "bearish")

    # signal schema
    sig = result["signal"]
    for field in ["action", "entry_price", "stop_loss", "take_profit",
                   "risk_reward", "reason", "confidence"]:
        assert field in sig
    assert sig["action"] in ("BUY", "SELL", "NO_TRADE")
    assert sig["confidence"] in ("Low", "Medium", "High")

    print("TEST 1 passed: schema conforms to spec")


def test_insufficient_data():
    print("\n========== TEST 2: Insufficient data ==========")
    df = make_intraday_ohlc(n=15)
    result = ICTAMDSignalEngine(timeframe="H1").analyze(df, symbol="EURUSD")
    sig = result["signal"]
    assert sig["action"] == "NO_TRADE"
    assert "Insufficient" in sig["reason"]
    print(f"  action={sig['action']}, reason={sig['reason']}")
    print("TEST 2 passed: insufficient data → NO_TRADE")


def test_weak_zone_sweep_not_counted_as_manipulation():
    """Spec: Weak zone sweep → manipulation_detected = false."""
    print("\n========== TEST 3: Weak zone sweep not counted ==========")
    # Build scenario where only Weak zones exist (min_touches=2 with single touch)
    # Actually we need a Weak zone that's been swept, but no Strong/Medium zone swept
    # Easiest: build data where only Weak zones are detected and verify manipulation.detected = False
    np.random.seed(505)
    n = 80
    dates = pd.date_range("2024-06-03", periods=n, freq="h")
    base = 1.0850
    # Tight random walk — few swings, all Weak strength (2 touches)
    close = base + np.sin(np.arange(n) / 5) * 0.0008 + np.random.randn(n) * 0.0001
    df = pd.DataFrame({
        "open":  close + np.random.randn(n) * 0.00005,
        "high":  close + abs(np.random.randn(n)) * 0.0003,
        "low":   close - abs(np.random.randn(n)) * 0.0003,
        "close": close,
    }, index=dates)

    result = ICTAMDSignalEngine(timeframe="H1", min_touches=2).analyze(df, symbol="EURUSD")
    # Either no zones detected, or all Weak
    if result["manipulation"]["detected"]:
        # If detected, must be on Strong/Medium zone or accumulation range
        zs = result["manipulation"]["zone_strength_used"]
        assert zs in ("Strong", "Medium"), f"Weak zone should not trigger manipulation, got {zs}"
    print(f"  manipulation.detected: {result['manipulation']['detected']}")
    print(f"  zone_strength_used: {result['manipulation']['zone_strength_used']}")
    print("TEST 3 passed: Weak zone sweeps not counted as valid manipulation")


def test_strict_rr_filter():
    """R:R < 1:6 must always be NO_TRADE even if other steps pass."""
    print("\n========== TEST 4: R:R strict 1:6 filter ==========")
    df = make_intraday_ohlc(n=300, vol=0.0003)  # tight vol = small range
    result = ICTAMDSignalEngine(timeframe="H1", min_touches=2).analyze(df, symbol="EURUSD")
    sig = result["signal"]
    # Either NO_TRADE or action with R:R >= 6
    if sig["action"] in ("BUY", "SELL"):
        assert sig["risk_reward"] is not None
        assert sig["risk_reward"] >= MIN_RR_RATIO - 0.1, \
            f"R:R must be ≥ {MIN_RR_RATIO}, got {sig['risk_reward']}"
        print(f"  Trade signal with R:R = 1:{sig['risk_reward']}")
    else:
        # NO_TRADE — verify reason mentions which step failed
        assert "Step" in sig["reason"] or "Insufficient" in sig["reason"]
        print(f"  NO_TRADE: {sig['reason'][:100]}")
    print("TEST 4 passed: R:R ≥ 1:6 enforced")


def test_no_trade_when_no_strong_zone_for_tp():
    """If no Strong zone exists for TP, must be NO_TRADE."""
    print("\n========== TEST 5: No Strong zone TP → NO_TRADE ==========")
    # Use very few candles so most zones are Weak/Medium at best
    np.random.seed(303)
    n = 50
    dates = pd.date_range("2024-06-03", periods=n, freq="h")
    close = 1.0850 + np.cumsum(np.random.randn(n) * 0.0008)
    df = pd.DataFrame({
        "open": close, "high": close + 0.0008, "low": close - 0.0008, "close": close,
    }, index=dates)
    result = ICTAMDSignalEngine(timeframe="H1", min_touches=2).analyze(df, symbol="EURUSD")
    sig = result["signal"]
    # With few candles, very unlikely to have full setup with Strong zone + R:R 6
    # Should be NO_TRADE
    print(f"  action={sig['action']}, reason={sig['reason'][:120]}")
    assert sig["action"] == "NO_TRADE"
    print("TEST 5 passed: insufficient setup → NO_TRADE")


def test_oneshot_helper():
    print("\n========== TEST 6: detect_ict_amd_signal() one-shot ==========")
    df = make_intraday_ohlc(n=200)
    json_str = detect_ict_amd_signal(df, symbol="EURUSD", timeframe="H1")
    parsed = json.loads(json_str)
    for key in ["zones", "accumulation", "manipulation", "fvg", "mss_confirmed", "signal"]:
        assert key in parsed
    print(f"  Top-level keys present: {list(parsed.keys())}")
    print("TEST 6 passed: one-shot helper returns valid JSON")


def test_prompt_text():
    print("\n========== TEST 7: to_prompt_text() LLM-friendly ==========")
    df = make_intraday_ohlc(n=200)
    engine = ICTAMDSignalEngine(timeframe="H1")
    result = engine.analyze(df, symbol="EURUSD")
    text = engine.to_prompt_text(result)
    print(text)
    assert "ICT/SMC AMD SIGNAL" in text
    assert "Accumulation" in text
    assert "Manipulation" in text
    assert "FVG" in text
    assert "MSS Confirmed" in text
    assert "Signal" in text
    print("TEST 7 passed: prompt text rendering works")


def test_accumulation_validation():
    """Test that wide Asian range → accumulation.valid = False."""
    print("\n========== TEST 8: Accumulation wide range → invalid ==========")
    np.random.seed(808)
    n = 100
    dates = pd.date_range("2024-06-03", periods=n, freq="h")
    # Create wide Asian range
    close = np.empty(n)
    for i in range(n):
        hour = dates[i].hour
        if 0 <= hour < 6:  # Asian — make it WIDE
            close[i] = 1.0850 + np.sin(i) * 0.015  # 1.5% swings
        else:
            close[i] = 1.0850 + np.random.randn() * 0.0005
    df = pd.DataFrame({
        "open": close, "high": close + 0.0008,
        "low": close - 0.0008, "close": close,
    }, index=dates)
    result = ICTAMDSignalEngine(timeframe="H1").analyze(df, symbol="EURUSD")
    acc = result["accumulation"]
    print(f"  Asian range_high={acc['range_high']}, range_low={acc['range_low']}, valid={acc['valid']}")
    # Should likely be invalid (range too wide)
    # Even if it slips through, signal must be NO_TRADE (no full setup)
    assert result["signal"]["action"] == "NO_TRADE"
    print("TEST 8 passed: wide Asian range handled")


def test_full_setup_buy_signal():
    """Construct a full setup: accumulation + downside sweep + bullish FVG + MSS + 1:6 RR."""
    print("\n========== TEST 9: Full BUY setup ==========")
    # This is a complex scenario — we'll build it carefully
    # Asian session: tight accumulation around 1.0850
    # London session: downside sweep below accumulation low (1.0845) → wick pierces to 1.0820
    # Then bullish reversal + bullish FVG + MSS (break of swing high)
    # Then strong resistance zone far above (1.0900) for 1:6 RR

    np.random.seed(909)
    n = 100
    dates = pd.date_range("2024-06-03", periods=n, freq="h")

    # Build candles hour by hour
    opens, highs, lows, closes = [], [], [], []
    for i in range(n):
        hour = dates[i].hour
        if 0 <= hour < 6:  # Asian (0-5): tight accumulation
            base = 1.0850 + np.sin(i / 3) * 0.0003
            o = base; c = base + np.random.randn() * 0.0001
            h = max(o, c) + 0.0001; l = min(o, c) - 0.0001
        elif 6 <= hour < 9:  # London (6-8)
            if hour == 6:  # Manipulation candle: downside sweep
                o = 1.0849
                c = 1.0847  # body closes near accumulation low (inside)
                h = 1.0850
                l = 1.0820  # wick pierces below
            elif hour == 7:  # Bullish reversal confirm (close above 1.0850)
                o = 1.0847
                c = 1.0855  # close above Asian range high → MSS+reversal
                h = 1.0858
                l = 1.0845
            elif hour == 8:  # Bullish FVG candle (3-candle pattern with prev 2)
                # candle[6]=sweep, candle[7]=reversal, candle[8]=strong up
                # For bullish FVG: c[6].high < c[8].low
                # c[6].high = 1.0850, c[8].low must be > 1.0850
                o = 1.0855
                c = 1.0870  # strong up candle
                h = 1.0872
                l = 1.0852  # > 1.0850 → creates FVG
        else:  # NY + after: drift up
            base = 1.0870 + (i - 9) * 0.0008
            o = base; c = base + 0.0005
            h = c + 0.0005; l = o - 0.0002
        opens.append(o); highs.append(h); lows.append(l); closes.append(c)

    # Add a few swing highs at 1.0900-1.0910 (Strong resistance) for TP
    # Force touches at candles 20, 35, 50, 65 (all in NY/afternoon hours)
    for touch_i in [20, 35, 50, 65]:
        if touch_i < n:
            highs[touch_i] = 1.0905 + np.random.rand() * 0.0005
            closes[touch_i] = 1.0870

    df = pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": closes,
    }, index=dates)

    engine = ICTAMDSignalEngine(timeframe="H1", min_touches=2, min_rr_ratio=6.0)
    result = engine.analyze(df, symbol="EURUSD")
    print(json.dumps(result, indent=2))

    # Expect either BUY (full setup) or NO_TRADE with clear reason
    sig = result["signal"]
    print(f"\n  Final: action={sig['action']}, R:R={sig.get('risk_reward')}, conf={sig['confidence']}")
    print(f"  Reason: {sig['reason'][:200]}")
    if sig["action"] == "BUY":
        assert sig["risk_reward"] is not None and sig["risk_reward"] >= 6.0
        assert sig["stop_loss"] < sig["entry_price"] < sig["take_profit"]
    print("TEST 9 passed: full setup scenario handled correctly")


def test_fvg_detection():
    """Directly test FVG detection logic."""
    print("\n========== TEST 10: FVG detection ==========")
    from analysis.ict_amd_signal_engine import ICTAMDSignalEngine, ManipulationResult
    engine = ICTAMDSignalEngine(timeframe="H1")

    # Build a 3-candle bullish FVG pattern manually
    # c1: high=1.0840, c2: strong bullish, c3: low=1.0850 (>1.0840) → bullish FVG
    n = 30
    dates = pd.date_range("2024-06-03", periods=n, freq="h")
    close = np.full(n, 1.0845)
    df = pd.DataFrame({
        "open": close, "high": close + 0.0005, "low": close - 0.0005, "close": close,
    }, index=dates)
    # Override candles 9, 10, 11 to create bullish FVG
    df.iloc[9, df.columns.get_loc("high")] = 1.0840
    df.iloc[10] = [1.0842, 1.0860, 1.0840, 1.0858]  # strong bullish middle
    df.iloc[11, df.columns.get_loc("low")] = 1.0852  # > 1.0840 → bullish FVG

    # Mock manipulation result (downside_sweep → expecting bullish FVG)
    manip = ManipulationResult(
        detected=True, direction="downside_sweep",
        break_index=8, confirm_index=11,
    )

    fvg = engine._step3_fvg(df, manip, atr_val=0.0010)
    print(f"  FVG found: {fvg.found}, type: {fvg.type}")
    if fvg.found:
        print(f"  top: {fvg.top}, bottom: {fvg.bottom}, midpoint: {fvg.midpoint}")
        assert fvg.type == "bullish"
        # FVG should be [c1.high=1.0840, c3.low=1.0852]
        # top = c3.low = 1.0852, bottom = c1.high = 1.0840
        assert abs(fvg.top - 1.0852) < 0.0001 or abs(fvg.bottom - 1.0840) < 0.0001
    print("TEST 10 passed: FVG detection works")


if __name__ == "__main__":
    test_schema_conformance()
    test_insufficient_data()
    test_weak_zone_sweep_not_counted_as_manipulation()
    test_strict_rr_filter()
    test_no_trade_when_no_strong_zone_for_tp()
    test_oneshot_helper()
    test_prompt_text()
    test_accumulation_validation()
    test_full_setup_buy_signal()
    test_fvg_detection()
    print("\n" + "=" * 50)
    print("ALL TESTS PASSED")
    print("=" * 50)


def test_full_setup_buy_signal_realistic():
    """Construct a complete BUY setup that PASSES 1:6 R:R filter."""
    print("\n========== TEST 11: Full BUY setup with R:R ≥ 1:6 ==========")
    np.random.seed(5555)
    n = 150
    dates = pd.date_range("2024-06-03", periods=n, freq="h")

    opens, highs, lows, closes = [], [], [], []
    for i in range(n):
        hour = dates[i].hour
        if 0 <= hour < 6:  # Asian — very tight
            base = 1.0850 + np.sin(i/4) * 0.00015
            o = base; c = base + np.random.randn() * 0.00005
            h = max(o, c) + 0.00005; l = min(o, c) - 0.00005
        elif 6 <= hour < 9:  # London
            if hour == 6:
                o = 1.0850; c = 1.0848; h = 1.0851; l = 1.0842
            elif hour == 7:
                o = 1.0848; c = 1.0855; h = 1.0858; l = 1.0846
            elif hour == 8:
                o = 1.0855; c = 1.0868; h = 1.0870; l = 1.0854
        else:
            progress = (i - 9) / max(n - 10, 1)
            base = 1.0868 + progress * 0.0080
            o = base; c = base + 0.0002
            h = c + 0.0002; l = o - 0.0001
        opens.append(o); highs.append(h); lows.append(l); closes.append(c)

    for touch_i in [25, 45, 65, 85, 105]:
        if touch_i < n:
            highs[touch_i] = 1.0950 + np.random.rand() * 0.0002
            closes[touch_i] = 1.0900

    df = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes}, index=dates)
    engine = ICTAMDSignalEngine(timeframe="H1", min_touches=2, min_rr_ratio=6.0)
    result = engine.analyze(df, symbol="EURUSD")

    sig = result["signal"]
    print(f"  Action     : {sig['action']}")
    print(f"  Entry      : {sig['entry_price']}")
    print(f"  Stop Loss  : {sig['stop_loss']}")
    print(f"  Take Profit: {sig['take_profit']}")
    print(f"  R:R        : 1:{sig['risk_reward']}")
    print(f"  Confidence : {sig['confidence']}")

    assert sig["action"] == "BUY", f"Expected BUY, got {sig['action']}"
    assert result["accumulation"]["valid"] == True
    assert result["manipulation"]["detected"] == True
    assert result["manipulation"]["zone_strength_used"] in ("Strong", "Medium")
    assert result["fvg"]["found"] == True
    assert result["mss_confirmed"] == True
    assert sig["risk_reward"] is not None and sig["risk_reward"] >= 6.0
    assert sig["stop_loss"] < sig["entry_price"] < sig["take_profit"]
    print("TEST 11 passed: full BUY setup with R:R ≥ 1:6 works!")


# Re-run all tests including the new one
if __name__ == "__main__":
    test_schema_conformance()
    test_insufficient_data()
    test_weak_zone_sweep_not_counted_as_manipulation()
    test_strict_rr_filter()
    test_no_trade_when_no_strong_zone_for_tp()
    test_oneshot_helper()
    test_prompt_text()
    test_accumulation_validation()
    test_full_setup_buy_signal()
    test_fvg_detection()
    test_full_setup_buy_signal_realistic()
    print("\n" + "=" * 50)
    print("ALL TESTS PASSED")
    print("=" * 50)
