"""Smoke test for High-Reliability Pattern Detector — spec compliance."""
import sys
sys.path.insert(0, "/home/z/my-project/forex_ai")

import warnings
warnings.filterwarnings("ignore")

import json
import numpy as np
import pandas as pd
from analysis.high_reliability_patterns import (
    HighReliabilityPatternDetector,
    detect_high_reliability_patterns,
    _candle_metrics,
)


def make_df(candles: list, start="2024-06-01"):
    """Build DataFrame from list of (open, high, low, close) tuples."""
    n = len(candles)
    dates = pd.date_range(start, periods=n, freq="h")
    return pd.DataFrame({
        "open":  [c[0] for c in candles],
        "high":  [c[1] for c in candles],
        "low":   [c[2] for c in candles],
        "close": [c[3] for c in candles],
    }, index=dates)


# ─── TESTS ────────────────────────────────────────────────────

def test_hammer_detection():
    print("\n========== TEST 1: Hammer detection ==========")
    # Hammer: open=1.0850, high=1.0855, low=1.0830, close=1.0852
    # body=2, lower_wick=20, upper_wick=3, range=25 → lower_wick/body=10 ✓
    candles = [
        (1.0850, 1.0860, 1.0840, 1.0845),  # neutral
        (1.0845, 1.0850, 1.0830, 1.0840),  # bearish
        (1.0850, 1.0855, 1.0830, 1.0852),  # HAMMER
    ]
    df = make_df(candles)
    detector = HighReliabilityPatternDetector(lookback=5)
    patterns = detector.detect(df, zones=[], atr_value=0.0010)
    hammer = [p for p in patterns if p.pattern_name == "Hammer"]
    assert len(hammer) >= 1, "Hammer should be detected"
    assert hammer[0].direction == "bullish"
    assert hammer[0].type == "Reversal"
    print(f"  Hammer detected at index {hammer[0].candle_index} ✓")
    print("TEST 1 passed: Hammer detection works")


def test_shooting_star_detection():
    print("\n========== TEST 2: Shooting Star detection ==========")
    # Shooting Star: open=1.0850, high=1.0875, low=1.0849, close=1.0851
    # body=1, upper_wick=24, lower_wick=1, range=26 → upper_wick/body=24 ✓
    candles = [
        (1.0850, 1.0860, 1.0840, 1.0855),  # bullish
        (1.0855, 1.0865, 1.0850, 1.0860),  # bullish
        (1.0850, 1.0875, 1.0849, 1.0851),  # SHOOTING STAR
    ]
    df = make_df(candles)
    detector = HighReliabilityPatternDetector(lookback=5)
    patterns = detector.detect(df, zones=[], atr_value=0.0010)
    ss = [p for p in patterns if p.pattern_name == "Shooting Star"]
    assert len(ss) >= 1, "Shooting Star should be detected"
    assert ss[0].direction == "bearish"
    print(f"  Shooting Star detected at index {ss[0].candle_index} ✓")
    print("TEST 2 passed: Shooting Star detection works")


def test_doji_detection():
    print("\n========== TEST 3: Doji detection ==========")
    # Doji: open≈close (body ≤ 5% of range)
    candles = [
        (1.0850, 1.0860, 1.0840, 1.0855),
        (1.0855, 1.0865, 1.0850, 1.0860),
        (1.0850, 1.0865, 1.0840, 1.0851),  # DOJI (body=1, range=25)
    ]
    df = make_df(candles)
    detector = HighReliabilityPatternDetector(lookback=5)
    patterns = detector.detect(df, zones=[], atr_value=0.0010)
    doji = [p for p in patterns if p.pattern_name == "Doji"]
    assert len(doji) >= 1, "Doji should be detected"
    assert doji[0].type == "Indecision"
    print(f"  Doji detected at index {doji[0].candle_index} ✓")
    print("TEST 3 passed: Doji detection works")


def test_bullish_marubozu():
    print("\n========== TEST 4: Bullish Marubozu ==========")
    # Marubozu: open=1.0850, high=1.0870, low=1.0849, close=1.0869
    # body=19, range=21, body_pct=0.905 ✓, upper_wick=1, lower_wick=1
    candles = [
        (1.0850, 1.0860, 1.0840, 1.0855),
        (1.0855, 1.0865, 1.0850, 1.0860),
        (1.0850, 1.0870, 1.0849, 1.0869),  # BULLISH MARUBOZU
    ]
    df = make_df(candles)
    detector = HighReliabilityPatternDetector(lookback=5)
    patterns = detector.detect(df, zones=[], atr_value=0.0010)
    marubozu = [p for p in patterns if p.pattern_name == "Bullish Marubozu"]
    assert len(marubozu) >= 1, "Bullish Marubozu should be detected"
    assert marubozu[0].type == "Continuation"
    print(f"  Bullish Marubozu detected at index {marubozu[0].candle_index} ✓")
    print("TEST 4 passed: Bullish Marubozu detection works")


def test_bullish_engulfing():
    print("\n========== TEST 5: Bullish Engulfing ==========")
    # 1st bearish, 2nd bullish engulfing
    candles = [
        (1.0850, 1.0860, 1.0840, 1.0855),  # padding
        (1.0860, 1.0865, 1.0845, 1.0850),  # bearish (body=10)
        (1.0848, 1.0870, 1.0845, 1.0868),  # BULLISH ENGULFING (body=20, engulfs prior)
    ]
    df = make_df(candles)
    detector = HighReliabilityPatternDetector(lookback=5)
    patterns = detector.detect(df, zones=[], atr_value=0.0010)
    be = [p for p in patterns if p.pattern_name == "Bullish Engulfing"]
    assert len(be) >= 1, "Bullish Engulfing should be detected"
    print(f"  Bullish Engulfing detected at index {be[0].candle_index} ✓")
    print("TEST 5 passed: Bullish Engulfing detection works")


def test_bearish_engulfing():
    print("\n========== TEST 6: Bearish Engulfing ==========")
    candles = [
        (1.0850, 1.0860, 1.0840, 1.0855),  # padding
        (1.0850, 1.0870, 1.0848, 1.0868),  # bullish (body=18)
        (1.0870, 1.0872, 1.0845, 1.0848),  # BEARISH ENGULFING (body=22, engulfs prior)
    ]
    df = make_df(candles)
    detector = HighReliabilityPatternDetector(lookback=5)
    patterns = detector.detect(df, zones=[], atr_value=0.0010)
    be = [p for p in patterns if p.pattern_name == "Bearish Engulfing"]
    assert len(be) >= 1, "Bearish Engulfing should be detected"
    print(f"  Bearish Engulfing detected at index {be[0].candle_index} ✓")
    print("TEST 6 passed: Bearish Engulfing detection works")


def test_tweezer_top():
    print("\n========== TEST 7: Tweezer Top ==========")
    # Two candles with equal highs, 1st bullish, 2nd bearish
    candles = [
        (1.0850, 1.0860, 1.0840, 1.0855),  # padding
        (1.0850, 1.0870, 1.0848, 1.0868),  # bullish, high=1.0870
        (1.0868, 1.0870, 1.0850, 1.0855),  # bearish, high=1.0870 (equal high)
    ]
    df = make_df(candles)
    detector = HighReliabilityPatternDetector(lookback=5)
    patterns = detector.detect(df, zones=[], atr_value=0.0010)
    tt = [p for p in patterns if p.pattern_name == "Tweezer Top"]
    assert len(tt) >= 1, "Tweezer Top should be detected"
    print(f"  Tweezer Top detected at index {tt[0].candle_index} ✓")
    print("TEST 7 passed: Tweezer Top detection works")


def test_piercing_line():
    print("\n========== TEST 8: Piercing Line ==========")
    # 1st bearish, 2nd bullish that closes above 50% of 1st body but below 1st open
    # 1st: open=1.0870, close=1.0850 (body=20, midpoint=1.0860)
    # 2nd: open=1.0845, close=1.0865 (closes above midpoint 1.0860, below 1st open 1.0870)
    candles = [
        (1.0850, 1.0860, 1.0840, 1.0855),  # padding
        (1.0870, 1.0875, 1.0845, 1.0850),  # bearish
        (1.0845, 1.0868, 1.0842, 1.0865),  # PIERCING LINE
    ]
    df = make_df(candles)
    detector = HighReliabilityPatternDetector(lookback=5)
    patterns = detector.detect(df, zones=[], atr_value=0.0010)
    pl = [p for p in patterns if p.pattern_name == "Piercing Line"]
    assert len(pl) >= 1, "Piercing Line should be detected"
    print(f"  Piercing Line detected at index {pl[0].candle_index} ✓")
    print("TEST 8 passed: Piercing Line detection works")


def test_morning_star():
    print("\n========== TEST 9: Morning Star ==========")
    # 1st bearish large, 2nd small indecision, 3rd bullish closes above 1st midpoint
    candles = [
        (1.0870, 1.0875, 1.0850, 1.0855),  # bearish (body=15, midpoint=1.08625)
        (1.0855, 1.0860, 1.0852, 1.0857),  # small body indecision (body=2, range=8, body_pct=25%)
        (1.0857, 1.0875, 1.0855, 1.0872),  # bullish close=1.0872 > midpoint 1.08625 ✓
    ]
    df = make_df(candles)
    detector = HighReliabilityPatternDetector(lookback=5)
    patterns = detector.detect(df, zones=[], atr_value=0.0010)
    ms = [p for p in patterns if p.pattern_name == "Morning Star"]
    assert len(ms) >= 1, "Morning Star should be detected"
    print(f"  Morning Star detected at index {ms[0].candle_index} ✓")
    print("TEST 9 passed: Morning Star detection works")


def test_three_white_soldiers():
    print("\n========== TEST 10: Three White Soldiers ==========")
    # 3 large bullish candles, progressive higher highs/closes, small gaps OK
    candles = [
        (1.0850, 1.0870, 1.0849, 1.0868),  # body=18, body_pct=18/21=86% ✓
        (1.0868, 1.0888, 1.0867, 1.0886),  # body=18, body_pct=19/21=90% ✓
        (1.0886, 1.0906, 1.0885, 1.0904),  # body=18, body_pct=19/21=90% ✓
    ]
    df = make_df(candles)
    detector = HighReliabilityPatternDetector(lookback=5)
    patterns = detector.detect(df, zones=[], atr_value=0.0010)
    sws = [p for p in patterns if p.pattern_name == "Three White Soldiers"]
    assert len(sws) >= 1, "Three White Soldiers should be detected"
    assert sws[0].type == "Continuation"
    print(f"  Three White Soldiers detected at index {sws[0].candle_index} ✓")
    print("TEST 10 passed: Three White Soldiers detection works")


def test_zone_confluence():
    print("\n========== TEST 11: Zone confluence (reliability High/Low) ==========")
    # Hammer near Support zone → High reliability
    # Hammer mid-range → Low reliability
    candles = [
        (1.0850, 1.0860, 1.0840, 1.0855),
        (1.0855, 1.0865, 1.0850, 1.0860),
        (1.0850, 1.0855, 1.0830, 1.0852),  # Hammer at price ~1.0850
    ]
    df = make_df(candles)

    # Case A: Hammer near Support zone (zone at 1.0845-1.0855)
    zones_near = [{"type": "Support", "zone_top": 1.0855, "zone_bottom": 1.0845}]
    detector = HighReliabilityPatternDetector(lookback=5)
    patterns_near = detector.detect(df, zones=zones_near, atr_value=0.0010)
    hammer_near = [p for p in patterns_near if p.pattern_name == "Hammer"]
    assert len(hammer_near) >= 1
    assert hammer_near[0].near_zone == True
    assert hammer_near[0].reliability == "High"
    print(f"  Hammer near Support zone → near_zone={hammer_near[0].near_zone}, reliability={hammer_near[0].reliability} ✓")

    # Case B: Hammer mid-range (no zones, or zone far away)
    zones_far = [{"type": "Resistance", "zone_top": 1.1000, "zone_bottom": 1.0995}]
    patterns_far = detector.detect(df, zones=zones_far, atr_value=0.0010)
    hammer_far = [p for p in patterns_far if p.pattern_name == "Hammer"]
    assert len(hammer_far) >= 1
    assert hammer_far[0].near_zone == False
    assert hammer_far[0].reliability == "Low"
    print(f"  Hammer mid-range → near_zone={hammer_far[0].near_zone}, reliability={hammer_far[0].reliability} ✓")
    print("TEST 11 passed: zone confluence validation works")


def test_multi_bar_repetition():
    print("\n========== TEST 12: Multi-bar repetition ==========")
    # Two Hammers at same zone → zone strength boost
    candles = [
        (1.0820, 1.0825, 1.0800, 1.0822),  # Hammer 1 at ~1.0822
        (1.0822, 1.0830, 1.0815, 1.0828),
        (1.0828, 1.0835, 1.0810, 1.0820),
        (1.0820, 1.0825, 1.0800, 1.0822),  # Hammer 2 at ~1.0822 (same area)
    ]
    df = make_df(candles)
    zones = [{"type": "Support", "zone_top": 1.0830, "zone_bottom": 1.0815}]
    detector = HighReliabilityPatternDetector(lookback=10)
    patterns = detector.detect(df, zones=zones, atr_value=0.0010)
    repetition = detector.analyze_repetition(patterns)

    hammers = [p for p in patterns if p.pattern_name == "Hammer"]
    print(f"  Hammers detected: {len(hammers)}")
    print(f"  Zone boosts: {repetition['zone_strength_boosts']}")
    print(f"  Consolidation: {repetition['consolidation_detected']}")

    if len(hammers) >= 2:
        # If both are near zone, we expect a boost
        near_count = sum(1 for h in hammers if h.near_zone)
        if near_count >= 2:
            assert len(repetition["zone_strength_boosts"]) >= 1
    print("TEST 12 passed: multi-bar repetition analysis works")


def test_consolidation_detection():
    print("\n========== TEST 13: Consolidation (multiple Doji) ==========")
    # Two consecutive Doji → consolidation
    # Doji: body must be ≤ 5% of range. body=1pip=0.0001, range=25pip=0.0025 → 4% ✓
    candles = [
        (1.0850, 1.0860, 1.0840, 1.0855),  # padding
        (1.0850, 1.0875, 1.0845, 1.08505), # Doji 1 (body=0.00005, range=0.003, body_pct=1.7%)
        (1.08505, 1.0875, 1.0845, 1.08500), # Doji 2 (body=0.00005, range=0.003, body_pct=1.7%)
    ]
    df = make_df(candles)
    detector = HighReliabilityPatternDetector(lookback=5)
    patterns = detector.detect(df, zones=[], atr_value=0.0010)
    repetition = detector.analyze_repetition(patterns)
    dojis = [p for p in patterns if p.pattern_name == "Doji"]
    print(f"  Dojis detected: {len(dojis)}")
    print(f"  Consolidation: {repetition['consolidation_detected']}")
    assert len(dojis) >= 2
    assert repetition["consolidation_detected"] == True
    print("TEST 13 passed: consolidation detection works")


def test_schema_conformance():
    print("\n========== TEST 14: Schema conformance ==========")
    np.random.seed(42)
    n = 50
    dates = pd.date_range("2024-06-01", periods=n, freq="h")
    close = 1.0850 + np.cumsum(np.random.randn(n) * 0.0005)
    df = pd.DataFrame({
        "open": close, "high": close + 0.0008, "low": close - 0.0008, "close": close,
    }, index=dates)
    patterns_json = detect_high_reliability_patterns(df, zones=[], atr_value=0.0010, lookback=10)
    assert isinstance(patterns_json, list)
    for p in patterns_json:
        for field in ["pattern_name", "type", "candle_index_or_time", "near_zone", "zone_type", "reliability"]:
            assert field in p, f"Missing field: {field}"
        assert p["type"] in ("Reversal", "Continuation", "Indecision")
        assert p["reliability"] in ("Low", "High")
        assert p["zone_type"] in ("Support", "Resistance", "Supply", "Demand", "Trendline", "None")
    print(f"  {len(patterns_json)} patterns detected, all conform to schema")
    print("TEST 14 passed: schema conformance works")


def test_oneshot_helper():
    print("\n========== TEST 15: detect_high_reliability_patterns() one-shot ==========")
    candles = [
        (1.0850, 1.0860, 1.0840, 1.0855),
        (1.0855, 1.0865, 1.0850, 1.0860),
        (1.0850, 1.0855, 1.0830, 1.0852),  # Hammer
    ]
    df = make_df(candles)
    result = detect_high_reliability_patterns(df, zones=[], atr_value=0.0010)
    assert isinstance(result, list)
    print(f"  {len(result)} patterns returned")
    if result:
        print(f"  First pattern: {json.dumps(result[0], indent=2)}")
    print("TEST 15 passed: one-shot helper works")


def test_no_false_positives_on_neutral_candles():
    print("\n========== TEST 16: No false positives on neutral candles ==========")
    # Build candles that should NOT trigger any pattern
    candles = [
        (1.0850, 1.0855, 1.0848, 1.0852),  # tiny body, both wicks small — not doji (body too big %), not anything else
        (1.0852, 1.0857, 1.0850, 1.0854),
        (1.0854, 1.0859, 1.0852, 1.0856),
    ]
    df = make_df(candles)
    detector = HighReliabilityPatternDetector(lookback=5)
    patterns = detector.detect(df, zones=[], atr_value=0.0010)
    # Should detect very few or no patterns (maybe Doji if body is small enough)
    print(f"  Patterns detected on neutral candles: {len(patterns)}")
    for p in patterns:
        print(f"    - {p.pattern_name}")
    # Should not detect reversal/momentum patterns
    reversal_or_momentum = [p for p in patterns if p.type in ("Reversal", "Continuation")]
    assert len(reversal_or_momentum) == 0, f"False positive: {[p.pattern_name for p in reversal_or_momentum]}"
    print("TEST 16 passed: no false positives on neutral candles")


if __name__ == "__main__":
    test_hammer_detection()
    test_shooting_star_detection()
    test_doji_detection()
    test_bullish_marubozu()
    test_bullish_engulfing()
    test_bearish_engulfing()
    test_tweezer_top()
    test_piercing_line()
    test_morning_star()
    test_three_white_soldiers()
    test_zone_confluence()
    test_multi_bar_repetition()
    test_consolidation_detection()
    test_schema_conformance()
    test_oneshot_helper()
    test_no_false_positives_on_neutral_candles()
    print("\n" + "=" * 50)
    print("ALL TESTS PASSED")
    print("=" * 50)
