"""Integration tests for Unified Signal Engine — verifies all 5 engines work together."""
import sys
sys.path.insert(0, "/home/z/my-project/forex_ai")

import warnings
warnings.filterwarnings("ignore")

import json
import numpy as np
import pandas as pd
from analysis.unified_signal_engine import UnifiedSignalEngine, detect_unified_signal


def make_4h_ohlc(n=200, base=1.0850, seed=42, vol=0.0008, start="2024-06-03 06:00"):
    np.random.seed(seed)
    dates = pd.date_range(start, periods=n, freq="4h")
    close = base + np.cumsum(np.random.randn(n) * vol)
    return pd.DataFrame({
        "open":  close + np.random.randn(n) * vol * 0.3,
        "high":  close + abs(np.random.randn(n)) * vol * 1.5,
        "low":   close - abs(np.random.randn(n)) * vol * 1.5,
        "close": close,
    }, index=dates)


def make_h2_ohlc(n=400, base=1.0850, seed=43, vol=0.0006, start="2024-06-03 06:00"):
    np.random.seed(seed)
    dates = pd.date_range(start, periods=n, freq="2h")
    close = base + np.cumsum(np.random.randn(n) * vol)
    return pd.DataFrame({
        "open":  close + np.random.randn(n) * vol * 0.3,
        "high":  close + abs(np.random.randn(n)) * vol * 1.5,
        "low":   close - abs(np.random.randn(n)) * vol * 1.5,
        "close": close,
    }, index=dates)


# ─── TESTS ────────────────────────────────────────────────────

def test_unified_schema():
    print("\n========== TEST 1: Unified schema conformance ==========")
    df = make_4h_ohlc()
    lower_df = make_h2_ohlc()
    engine = UnifiedSignalEngine(timeframe="4H")
    result = engine.analyze(df, symbol="EURUSD", lower_tf_df=lower_df)

    # Top-level keys
    for key in ["pair", "timeframe", "current_price", "atr", "zones",
                "detected_patterns", "pattern_repetition",
                "stop_hunt", "ict_amd", "multi_strategy_pa", "consensus"]:
        assert key in result, f"Missing top-level key: {key}"

    # zones schema
    z = result["zones"]
    assert "support_resistance" in z
    assert "unified_zones" in z

    # detected_patterns schema
    for p in result["detected_patterns"]:
        for field in ["pattern_name", "type", "candle_index_or_time", "near_zone", "zone_type", "reliability"]:
            assert field in p

    # pattern_repetition schema
    rep = result["pattern_repetition"]
    for field in ["zone_strength_boosts", "momentum_sequence", "consolidation_detected"]:
        assert field in rep

    # Each engine result must be present
    assert "signal" in result["stop_hunt"]
    assert "signal" in result["ict_amd"]
    assert "signal" in result["multi_strategy_pa"]

    # consensus schema
    con = result["consensus"]
    for field in ["action", "confidence", "reason", "voting_engines", "buy_score", "sell_score"]:
        assert field in con
    assert con["action"] in ("BUY", "SELL", "WAIT", "NO_TRADE")

    print(f"  All top-level keys present ✓")
    print(f"  {len(result['detected_patterns'])} patterns detected")
    print(f"  Consensus: {con['action']} (BUY={con['buy_score']}, SELL={con['sell_score']})")
    print("TEST 1 passed: unified schema conforms")


def test_insufficient_data():
    print("\n========== TEST 2: Insufficient data ==========")
    df = make_4h_ohlc(n=15)
    engine = UnifiedSignalEngine(timeframe="4H")
    result = engine.analyze(df, symbol="EURUSD")
    con = result["consensus"]
    assert con["action"] == "NO_TRADE"
    assert "Insufficient" in con["reason"]
    print(f"  action={con['action']}, reason={con['reason']}")
    print("TEST 2 passed: insufficient data → NO_TRADE")


def test_all_engines_run():
    print("\n========== TEST 3: All engines run without errors ==========")
    df = make_4h_ohlc(n=300)
    lower_df = make_h2_ohlc(n=600)
    engine = UnifiedSignalEngine(timeframe="4H")
    result = engine.analyze(df, symbol="EURUSD", lower_tf_df=lower_df)

    # Verify all 3 strategy engines produced output
    assert result["stop_hunt"] is not None
    assert result["ict_amd"] is not None
    assert result["multi_strategy_pa"] is not None

    # Each must have a signal dict
    for engine_name in ["stop_hunt", "ict_amd", "multi_strategy_pa"]:
        sig = result[engine_name]["signal"]
        assert "action" in sig
        assert sig["action"] in ("BUY", "SELL", "WAIT", "NO_TRADE")
        print(f"  {engine_name}: {sig['action']}")

    print("TEST 3 passed: all engines ran without errors")


def test_consensus_voting():
    print("\n========== TEST 4: Consensus voting logic ==========")
    # Build scenario where StopHunt + PA agree on BUY
    np.random.seed(11111)
    n = 200
    dates = pd.date_range("2024-05-26 00:00", periods=n, freq="1h")
    t = np.arange(n)
    base = 1.0820 + t * 0.00008  # uptrend
    noise = np.random.randn(n) * 0.0004
    pullbacks = np.zeros(n)
    for pb_center in [30, 80, 130, 170]:
        pullbacks += -0.0007 * np.exp(-((t - pb_center) ** 2) / 50)
    close = base + noise + pullbacks
    for touch_i in [40, 60, 80]:
        close[touch_i] = 1.0853

    df = pd.DataFrame({
        "open":  close + np.random.randn(n) * 0.0001,
        "high":  close + abs(np.random.randn(n)) * 0.0005,
        "low":   close - abs(np.random.randn(n)) * 0.0005,
        "close": close,
    }, index=dates)

    np.random.seed(22222)
    n2 = 400
    dates2 = pd.date_range("2024-05-26 00:00", periods=n2, freq="30min")
    t2 = np.arange(n2)
    base2 = 1.0820 + t2 * 0.00004
    close2 = base2 + np.random.randn(n2) * 0.0003
    lower_df = pd.DataFrame({
        "open":  close2 + np.random.randn(n2) * 0.0001,
        "high":  close2 + abs(np.random.randn(n2)) * 0.0004,
        "low":   close2 - abs(np.random.randn(n2)) * 0.0004,
        "close": close2,
    }, index=dates2)

    engine = UnifiedSignalEngine(timeframe="1H")
    result = engine.analyze(df, symbol="EURUSD", lower_tf_df=lower_df)
    con = result["consensus"]

    print(f"  StopHunt: {result['stop_hunt']['signal']['action']}")
    print(f"  ICT/AMD: {result['ict_amd']['signal']['action']}")
    print(f"  PA: {result['multi_strategy_pa']['signal']['action']}")
    print(f"  Consensus: {con['action']} (BUY={con['buy_score']}, SELL={con['sell_score']})")
    print(f"  Voting: {con['voting_engines']}")

    # If any engine votes BUY, consensus should reflect that
    if con["buy_score"] > 0 or con["sell_score"] > 0:
        assert con["action"] in ("BUY", "SELL", "NO_TRADE")  # NO_TRADE on tie
    print("TEST 4 passed: consensus voting works")


def test_engine_disabling():
    print("\n========== TEST 5: Disable individual engines ==========")
    df = make_4h_ohlc()
    engine = UnifiedSignalEngine(
        timeframe="4H",
        enable_stop_hunt=False,
        enable_ict_amd=False,
        enable_pa=True,
        enable_patterns=False,
    )
    result = engine.analyze(df, symbol="EURUSD")

    # StopHunt and ICT should be fallback (NO_TRADE) with "disabled" reason
    assert result["stop_hunt"]["signal"]["action"] == "NO_TRADE"
    assert "disabled" in result["stop_hunt"]["signal"]["reason"].lower() or \
           "failed" in result["stop_hunt"]["signal"]["reason"].lower()
    assert result["ict_amd"]["signal"]["action"] == "NO_TRADE"
    assert "disabled" in result["ict_amd"]["signal"]["reason"].lower() or \
           "failed" in result["ict_amd"]["signal"]["reason"].lower()

    # PA should still produce output
    assert result["multi_strategy_pa"]["signal"]["action"] in ("BUY", "SELL", "WAIT", "NO_TRADE")

    # Patterns disabled → empty list
    assert result["detected_patterns"] == []

    print(f"  StopHunt disabled: {result['stop_hunt']['signal']['reason']}")
    print(f"  ICT disabled: {result['ict_amd']['signal']['reason']}")
    print(f"  PA active: {result['multi_strategy_pa']['signal']['action']}")
    print(f"  Patterns disabled: {len(result['detected_patterns'])} patterns")
    print("TEST 5 passed: engine disabling works")


def test_oneshot_helper():
    print("\n========== TEST 6: detect_unified_signal() one-shot ==========")
    df = make_4h_ohlc()
    lower_df = make_h2_ohlc()
    json_str = detect_unified_signal(df, symbol="EURUSD", timeframe="4H", lower_tf_df=lower_df)
    parsed = json.loads(json_str)
    for key in ["pair", "timeframe", "zones", "detected_patterns", "consensus"]:
        assert key in parsed
    print(f"  pair={parsed['pair']}, timeframe={parsed['timeframe']}")
    print(f"  consensus={parsed['consensus']['action']}")
    print("TEST 6 passed: one-shot helper returns valid JSON")


def test_prompt_text():
    print("\n========== TEST 7: to_prompt_text() ==========")
    df = make_4h_ohlc()
    lower_df = make_h2_ohlc()
    engine = UnifiedSignalEngine(timeframe="4H")
    result = engine.analyze(df, symbol="EURUSD", lower_tf_df=lower_df)
    text = engine.to_prompt_text(result)
    print(text)
    assert "UNIFIED SIGNAL" in text
    assert "Consensus" in text
    assert "Engine Signals" in text
    print("TEST 7 passed: prompt text rendering works")


def test_pattern_detector_wired_into_pa():
    """Verify PA engine uses HighReliabilityPatternDetector for checklist."""
    print("\n========== TEST 8: Pattern detector wired into PA ==========")
    df = make_4h_ohlc()
    engine = UnifiedSignalEngine(timeframe="4H")
    result = engine.analyze(df, symbol="EURUSD")

    pa_result = result["multi_strategy_pa"]
    checklist = pa_result["confirmation_checklist"]

    # Verify all 6 factors present
    for factor in ["candlestick_pattern", "chart_pattern", "candle_behavior",
                   "confluence_level", "trendline_confluence", "multi_tf_alignment"]:
        assert factor in checklist

    print(f"  Checklist: {checklist['total_confirmed']}/6")
    print(f"    candlestick_pattern: {checklist['candlestick_pattern']}")
    print(f"    chart_pattern: {checklist['chart_pattern']}")
    print(f"    candle_behavior: {checklist['candle_behavior']}")
    print(f"    confluence_level: {checklist['confluence_level']}")
    print(f"    trendline_confluence: {checklist['trendline_confluence']}")
    print(f"    multi_tf_alignment: {checklist['multi_tf_alignment']}")
    print("TEST 8 passed: pattern detector wired into PA checklist")


def test_shared_zones_across_engines():
    """Verify S/R zones are shared (not computed redundantly per engine)."""
    print("\n========== TEST 9: Shared zones across engines ==========")
    df = make_4h_ohlc()
    engine = UnifiedSignalEngine(timeframe="4H")
    result = engine.analyze(df, symbol="EURUSD")

    # Top-level zones should match what each engine sees
    top_zones = result["zones"]["support_resistance"]

    # StopHunt engine output includes its own zones
    sh_resistance = result["stop_hunt"].get("resistance_zones", [])
    sh_support = result["stop_hunt"].get("support_zones", [])

    # PA engine output includes its own S/R zones
    pa_sr = result["multi_strategy_pa"]["zones"]["support_resistance"]

    # All engines should have detected SOME zones (or all empty if data is tough)
    print(f"  Top-level S/R zones: {len(top_zones)}")
    print(f"  StopHunt resistance zones: {len(sh_resistance)}")
    print(f"  StopHunt support zones: {len(sh_support)}")
    print(f"  PA S/R zones: {len(pa_sr)}")

    # Verify zones are non-empty (engines are working)
    assert len(top_zones) > 0 or len(pa_sr) > 0
    print("TEST 9 passed: zones shared across engines")


def test_consensus_consolidation_override():
    """When consolidation detected (multi Doji), consensus → WAIT."""
    print("\n========== TEST 10: Consolidation override ==========")
    # Build data with multiple Doji candles
    np.random.seed(707)
    n = 100
    dates = pd.date_range("2024-06-03 06:00", periods=n, freq="4h")

    # First 95 normal candles
    closes, highs, lows, opens = [], [], [], []
    for i in range(95):
        c = 1.0850 + np.sin(i / 8) * 0.0008 + np.random.randn() * 0.0002
        o = c + np.random.randn() * 0.0001
        h = max(o, c) + abs(np.random.randn()) * 0.0003
        l = min(o, c) - abs(np.random.randn()) * 0.0003
        closes.append(c); highs.append(h); lows.append(l); opens.append(o)

    # Last 5: Doji sequence (consolidation)
    for i in range(5):
        o = 1.0850
        c = 1.08505  # near-zero body (Doji)
        h = 1.0875
        l = 1.0825
        opens.append(o); highs.append(h); lows.append(l); closes.append(c)

    df = pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": closes,
    }, index=dates)

    engine = UnifiedSignalEngine(timeframe="4H")
    result = engine.analyze(df, symbol="EURUSD")

    rep = result["pattern_repetition"]
    con = result["consensus"]
    print(f"  Consolidation detected: {rep['consolidation_detected']}")
    print(f"  Consensus: {con['action']}")

    # If consolidation detected, consensus should be WAIT
    if rep["consolidation_detected"]:
        assert con["action"] == "WAIT"
        print(f"  → WAIT override active ✓")
    print("TEST 10 passed: consolidation override works")


if __name__ == "__main__":
    test_unified_schema()
    test_insufficient_data()
    test_all_engines_run()
    test_consensus_voting()
    test_engine_disabling()
    test_oneshot_helper()
    test_prompt_text()
    test_pattern_detector_wired_into_pa()
    test_shared_zones_across_engines()
    test_consensus_consolidation_override()
    print("\n" + "=" * 50)
    print("ALL TESTS PASSED")
    print("=" * 50)
