#!/usr/bin/env python3
"""
test_smc_session.py — SMC + Session Engine verification (Day 81+)
===================================================================

WHY THIS EXISTS:
    The SMC engine and Session analyzer are critical pipeline components
    that determine whether a trade signal passes through. When they
    silently fail (return empty results, crash on edge cases, or produce
    unexpected WAIT signals), the entire trading pipeline breaks.

    This script runs each module in isolation against REAL MT5 data
    (or synthetic data if MT5 is unavailable) and reports:
      - Does the module import cleanly?
      - Does it return a valid result dict with all expected keys?
      - Does the confluence scoring work (BOS/CHoCH/OB/FVG/Sweep)?
      - Does session detection work for all 24 hours?
      - Are there any exceptions or silent failures?
      - What does the SMC+Session fusion score look like?

USAGE (on Windows with MT5 terminal running):
    python test_smc_session.py                 # default: EURUSD
    python test_smc_session.py GBPUSD XAUUSD   # multiple symbols
    python test_smc_session.py --synthetic     # use synthetic data (no MT5)

USAGE (on Linux/Mac without MT5):
    python test_smc_session.py --synthetic
"""
from __future__ import annotations

import argparse
import os
import sys
import traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── Project setup ──────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# Quiet down chatty loggers
os.environ.setdefault("ENABLE_TELEGRAM", "false")
os.environ.setdefault("USE_SCANNER", "false")

import logging
for noisy in ("urllib3", "httpx", "httpcore", "chromadb",
              "sentence_transformers", "huggingface_hub"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


# ── Color helpers ──────────────────────────────────────────────────
_IS_TTY = sys.stdout.isatty()


def _c(text: str, color: str) -> str:
    if not _IS_TTY:
        return text
    codes = {
        "red": "31", "green": "32", "yellow": "33",
        "blue": "34", "magenta": "35", "cyan": "36",
        "gray": "90", "bold": "1",
    }
    return f"\033[{codes.get(color, '0')}m{text}\033[0m"


def _pass() -> str: return _c("[PASS]", "green")
def _fail() -> str: return _c("[FAIL]", "red")
def _warn() -> str: return _c("[WARN]", "yellow")
def _info() -> str: return _c("[INFO]", "cyan")


# ── Synthetic data generator (for non-MT5 testing) ─────────────────

def _make_synthetic_df(n: int = 200, seed: int = 42) -> "pd.DataFrame":
    """Generate realistic OHLCV data with trend + noise for SMC testing."""
    import numpy as np
    import pandas as pd
    np.random.seed(seed)

    # Generate a trending price series with pullbacks
    base = 1.0850
    trend = np.cumsum(np.random.randn(n) * 0.0003 + 0.0001)  # slight uptrend
    closes = base + trend

    # Add intrabar noise
    opens = closes - np.random.uniform(-0.0005, 0.0005, n)
    highs = np.maximum(opens, closes) + np.random.uniform(0, 0.0008, n)
    lows = np.minimum(opens, closes) - np.random.uniform(0, 0.0008, n)
    volumes = np.random.randint(100, 2000, n).astype(float)

    df = pd.DataFrame({
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": volumes,
    }, index=pd.date_range("2024-01-01", periods=n, freq="15min"))
    return df


# ── Test 1: Session Analyzer ───────────────────────────────────────

def test_session_analyzer() -> Dict[str, Any]:
    """Test the SessionAnalyzer for all 24 hours + DST + dead zone."""
    print(f"\n{_info()} Testing SessionAnalyzer...")
    result = {"module": "session_analyzer", "tests": [], "errors": []}

    try:
        from analysis.session_analyzer import SessionAnalyzer
        from analysis.session_rules import DEAD_ZONES, SESSION_WINDOWS

        sa = SessionAnalyzer()

        # Test 1a: DEAD_ZONES is empty (Day 81+ hotfix)
        dead_zones_empty = len(DEAD_ZONES) == 0
        result["tests"].append({
            "name": "DEAD_ZONES empty (Day 81+ hotfix)",
            "passed": dead_zones_empty,
            "detail": f"DEAD_ZONES = {DEAD_ZONES}",
        })
        print(f"  {'✓' if dead_zones_empty else '✗'} DEAD_ZONES = {DEAD_ZONES}")

        # Test 1b: Session detection for all 24 hours
        print(f"  Testing session detection for 24 hours:")
        sessions_seen = set()
        for hour in range(24):
            dt = datetime(2026, 6, 24, hour, 0, tzinfo=timezone.utc)
            sess = sa.get_current_session(dt)
            primary = sess.get("primary_session", "UNKNOWN")
            sessions_seen.add(primary)

            # Verify required keys
            required_keys = {"primary_session", "active_sessions", "gmt_hour",
                            "is_dead_zone", "london_open_window"}
            missing = required_keys - set(sess.keys())
            if missing:
                result["errors"].append(f"Hour {hour}: missing keys {missing}")
                print(f"    {_fail()} Hour {hour:02d}: {primary} (missing {missing})")
            else:
                # Dead zone should always be False (we emptied DEAD_ZONES)
                if sess["is_dead_zone"]:
                    result["errors"].append(f"Hour {hour}: is_dead_zone=True but DEAD_ZONES is empty!")
                    print(f"    {_fail()} Hour {hour:02d}: {primary} (dead zone should be False!)")
                else:
                    print(f"    {_pass()} Hour {hour:02d}: {primary} (dead_zone={sess['is_dead_zone']})")

        # Test 1c: Verify we see expected sessions
        expected = {"LONDON", "NEW_YORK", "TOKYO", "SYDNEY", "LONDON_NY_OVERLAP", "BETWEEN_SESSIONS"}
        missing_sessions = expected - sessions_seen
        if missing_sessions:
            result["tests"].append({
                "name": "All expected sessions detected",
                "passed": False,
                "detail": f"Missing: {missing_sessions}",
            })
            print(f"  {_warn()} Missing sessions: {missing_sessions}")
        else:
            result["tests"].append({
                "name": "All expected sessions detected",
                "passed": True,
                "detail": f"Sessions seen: {sorted(sessions_seen)}",
            })
            print(f"  {_pass()} All sessions detected: {sorted(sessions_seen)}")

        # Test 1d: DST detection
        us_dst = sa._is_us_dst(datetime(2026, 6, 24, tzinfo=timezone.utc))  # June = DST
        eu_dst = sa._is_eu_dst(datetime(2026, 6, 24, tzinfo=timezone.utc))
        result["tests"].append({
            "name": "DST detection (June = summer)",
            "passed": us_dst and eu_dst,
            "detail": f"US_DST={us_dst}, EU_DST={eu_dst}",
        })
        print(f"  {'✓' if us_dst and eu_dst else '✗'} DST: US={us_dst}, EU={eu_dst}")

        # Test 1e: Strategy mode for each session
        print(f"  Testing strategy modes:")
        for session in ["LONDON", "NEW_YORK", "TOKYO", "SYDNEY", "LONDON_NY_OVERLAP", "BETWEEN_SESSIONS"]:
            strat = sa.get_strategy_mode(session, gmt_hour=9)
            has_strategy = "strategy" in strat and "trade_allowed" in strat
            result["tests"].append({
                "name": f"Strategy mode for {session}",
                "passed": has_strategy,
                "detail": f"strategy={strat.get('strategy')}, trade_allowed={strat.get('trade_allowed')}",
            })
            print(f"    {'✓' if has_strategy else '✗'} {session}: {strat.get('strategy')} (trade={strat.get('trade_allowed')})")

        # Test 1f: Full analyze() with SMC context
        full = sa.analyze(pair="EURUSD", smc_ctx={"smc_signal": "BUY", "smc_score": 75})
        # The result uses different key names than get_current_session —
        # check for the actual keys produced by analyze()
        required_full = {"session_info", "session", "strategy", "trade_allowed"}
        missing_full = required_full - set(full.keys()) if isinstance(full, dict) else required_full
        result["tests"].append({
            "name": "Full analyze() with SMC fusion",
            "passed": not missing_full,
            "detail": f"keys={list(full.keys()) if isinstance(full, dict) else 'NOT DICT'}",
        })
        print(f"  {'✓' if not missing_full else '✗'} Full analyze(): keys={list(full.keys()) if isinstance(full, dict) else 'N/A'}")

    except Exception as e:
        result["errors"].append(f"Exception: {type(e).__name__}: {e}")
        result["errors"].append(traceback.format_exc().splitlines()[-1])
        print(f"  {_fail()} Exception: {e}")

    return result


# ── Test 2: SMC Engine ─────────────────────────────────────────────

def test_smc_engine(symbol: str, use_synthetic: bool = False) -> Dict[str, Any]:
    """Test the SMCEngine for a given symbol."""
    print(f"\n{_info()} Testing SMCEngine for {symbol}...")
    result = {"module": "smc_engine", "symbol": symbol, "tests": [], "errors": []}

    try:
        from analysis.smc_engine import SMCEngine, SCORE_WEIGHTS, MIN_TRADE_SCORE

        # Test 2a: Module imports + class instantiation
        smc = SMCEngine(symbol)
        result["tests"].append({
            "name": "SMCEngine instantiation",
            "passed": True,
            "detail": f"SMCEngine({symbol}) created",
        })
        print(f"  {_pass()} SMCEngine({symbol}) instantiated")

        # Test 2b: Run analyze() — this fetches real MT5 data or fails gracefully
        if use_synthetic:
            # Inject synthetic data into the fetcher
            print(f"  Using synthetic data (no MT5)...")
            import pandas as pd
            synthetic_h4 = _make_synthetic_df(150, seed=42)
            synthetic_m15 = _make_synthetic_df(150, seed=43)

            # Monkey-patch the fetcher to return synthetic data
            original_fetch = smc.fetcher.fetch_ohlcv
            def fake_fetch(sym, tf, limit=300):
                if "4h" in str(tf).lower():
                    return synthetic_h4
                return synthetic_m15
            smc.fetcher.fetch_ohlcv = fake_fetch

        print(f"  Running analyze()...")
        try:
            res = smc.analyze()
        except Exception as e:
            if "MetaTrader5" in str(e) or "mt5" in str(e).lower():
                print(f"  {_warn()} MT5 unavailable — falling back to synthetic data")
                use_synthetic = True
                import pandas as pd
                synthetic_h4 = _make_synthetic_df(150, seed=42)
                synthetic_m15 = _make_synthetic_df(150, seed=43)
                original_fetch = smc.fetcher.fetch_ohlcv
                def fake_fetch(sym, tf, limit=300):
                    return synthetic_h4 if "4h" in str(tf).lower() else synthetic_m15
                smc.fetcher.fetch_ohlcv = fake_fetch
                res = smc.analyze()
            else:
                raise

        # Test 2c: Verify result structure
        required_keys = {
            "symbol", "current_price", "h4", "m15",
            "confluence_score", "confluence_factors", "direction",
            "grade", "signal", "analysis",
        }
        missing = required_keys - set(res.keys())
        result["tests"].append({
            "name": "Result has all required keys",
            "passed": not missing,
            "detail": f"missing={missing}" if missing else "all keys present",
        })
        print(f"  {'✓' if not missing else '✗'} Result keys: {missing or 'all present'}")

        # Test 2d: Confluence factors structure
        factors = res.get("confluence_factors", {})
        expected_factors = {"liquidity_sweep", "order_block", "fvg", "bos", "confirmation_candle"}
        missing_factors = expected_factors - set(factors.keys())
        result["tests"].append({
            "name": "Confluence factors structure",
            "passed": not missing_factors,
            "detail": f"factors={factors}",
        })
        print(f"  {'✓' if not missing_factors else '✗'} Factors: {factors}")

        # Test 2e: Score is in valid range
        score = res.get("confluence_score", -1)
        score_valid = 0 <= score <= 100
        result["tests"].append({
            "name": "Confluence score in [0, 100]",
            "passed": score_valid,
            "detail": f"score={score}",
        })
        print(f"  {'✓' if score_valid else '✗'} Score: {score}/100")

        # Test 2f: Direction is valid
        direction = res.get("direction", "UNKNOWN")
        direction_valid = direction in ("BUY", "SELL", "NEUTRAL")
        result["tests"].append({
            "name": "Direction is BUY/SELL/NEUTRAL",
            "passed": direction_valid,
            "detail": f"direction={direction}",
        })
        print(f"  {'✓' if direction_valid else '✗'} Direction: {direction}")

        # Test 2g: Grade is valid
        grade = res.get("grade", "UNKNOWN")
        grade_valid = grade in ("A+", "A", "B", "INVALID")
        result["tests"].append({
            "name": "Grade is A+/A/B/INVALID",
            "passed": grade_valid,
            "detail": f"grade={grade}",
        })
        print(f"  {'✓' if grade_valid else '✗'} Grade: {grade}")

        # Test 2h: Signal is valid
        signal = res.get("signal", "UNKNOWN")
        signal_valid = signal in ("BUY", "SELL", "WAIT")
        result["tests"].append({
            "name": "Signal is BUY/SELL/WAIT",
            "passed": signal_valid,
            "detail": f"signal={signal}",
        })
        print(f"  {'✓' if signal_valid else '✗'} Signal: {signal}")

        # Test 2i: H4 structure has BOS/CHoCH/sweep
        h4 = res.get("h4", {})
        h4_keys = {"order_blocks", "fvgs", "bos", "choch", "liquidity_sweep"}
        h4_missing = h4_keys - set(h4.keys()) if isinstance(h4, dict) else h4_keys
        result["tests"].append({
            "name": "H4 structure (BOS/CHoCH/OB/FVG/Sweep)",
            "passed": not h4_missing,
            "detail": f"h4_keys={list(h4.keys()) if isinstance(h4, dict) else 'N/A'}",
        })
        print(f"  {'✓' if not h4_missing else '✗'} H4 keys: {list(h4.keys()) if isinstance(h4, dict) else 'N/A'}")

        # Test 2j: Print full SMC summary
        print(f"\n  {_info()} SMC Summary for {symbol}:")
        print(f"    Signal     : {signal}")
        print(f"    Direction  : {direction}")
        print(f"    Score      : {score}/100 (MIN_TRADE_SCORE={MIN_TRADE_SCORE})")
        print(f"    Grade      : {grade}")
        print(f"    Price      : {res.get('current_price')}")
        print(f"    Factors    :")
        for name, weight in SCORE_WEIGHTS.items():
            mark = "✅" if factors.get(name) else "❌"
            print(f"      {mark} {name:<22} (+{weight})")
        print(f"    Analysis   : {res.get('analysis', '')[:120]}")

        # Test 2k: get_ai_context works
        ctx = smc.get_ai_context(res)
        required_ctx = {"smc_signal", "smc_direction", "smc_score", "smc_grade"}
        ctx_missing = required_ctx - set(ctx.keys())
        result["tests"].append({
            "name": "get_ai_context() returns valid dict",
            "passed": not ctx_missing,
            "detail": f"ctx_keys={list(ctx.keys())}",
        })
        print(f"  {'✓' if not ctx_missing else '✗'} AI context keys: {list(ctx.keys())}")

    except Exception as e:
        result["errors"].append(f"Exception: {type(e).__name__}: {e}")
        result["errors"].append(traceback.format_exc().splitlines()[-1])
        print(f"  {_fail()} Exception: {type(e).__name__}: {e}")
        print(f"  {_info()} Full traceback:")
        for line in traceback.format_exc().splitlines()[-5:]:
            print(f"    {line}")

    return result


# ── Test 3: SMC + Session Fusion ───────────────────────────────────

def test_smc_session_fusion(symbol: str, use_synthetic: bool = False) -> Dict[str, Any]:
    """Test that SMC + Session work together (fusion score)."""
    print(f"\n{_info()} Testing SMC + Session fusion for {symbol}...")
    result = {"module": "smc_session_fusion", "symbol": symbol, "tests": [], "errors": []}

    try:
        from analysis.smc_engine import SMCEngine
        from analysis.session_analyzer import SessionAnalyzer

        sa = SessionAnalyzer()
        smc = SMCEngine(symbol)

        # Get current session
        session_result = sa.get_current_session()
        print(f"  Current session: {session_result['primary_session']} ({session_result['gmt_time']})")
        print(f"  is_dead_zone: {session_result['is_dead_zone']} (should be False)")

        # Get SMC analysis
        if use_synthetic:
            synthetic_h4 = _make_synthetic_df(150, seed=42)
            synthetic_m15 = _make_synthetic_df(150, seed=43)
            def fake_fetch(sym, tf, limit=300):
                return synthetic_h4 if "4h" in str(tf).lower() else synthetic_m15
            smc.fetcher.fetch_ohlcv = fake_fetch

        try:
            smc_result = smc.analyze()
        except Exception as e:
            if "MetaTrader5" in str(e) or "mt5" in str(e).lower():
                print(f"  {_warn()} MT5 unavailable — using synthetic data")
                synthetic_h4 = _make_synthetic_df(150, seed=42)
                synthetic_m15 = _make_synthetic_df(150, seed=43)
                def fake_fetch(sym, tf, limit=300):
                    return synthetic_h4 if "4h" in str(tf).lower() else synthetic_m15
                smc.fetcher.fetch_ohlcv = fake_fetch
                smc_result = smc.analyze()
            else:
                raise

        smc_ctx = smc.get_ai_context(smc_result)

        # Run full analyze with SMC context
        fusion = sa.analyze(pair=symbol, smc_ctx=smc_ctx)

        # Verify fusion result
        if not isinstance(fusion, dict):
            result["errors"].append(f"Fusion result is not a dict: {type(fusion)}")
            print(f"  {_fail()} Fusion result is not a dict")
            return result

        session_info = fusion.get("session_info", {})
        session_ctx = fusion.get("strategy", {})  # analyze() returns strategy dict

        # Test: fusion has expected keys
        required = {"session_info", "session", "strategy", "trade_allowed"}
        missing = required - set(fusion.keys())
        result["tests"].append({
            "name": "Fusion has session_info + session + strategy + trade_allowed",
            "passed": not missing,
            "detail": f"keys={list(fusion.keys())}",
        })
        print(f"  {'✓' if not missing else '✗'} Fusion keys: {list(fusion.keys())}")

        # Test: trade_allowed is True (dead zone removed)
        trade_allowed = fusion.get("trade_allowed", False)
        result["tests"].append({
            "name": "trade_allowed=True (dead zone removed)",
            "passed": trade_allowed,
            "detail": f"trade_allowed={trade_allowed}",
        })
        print(f"  {'✓' if trade_allowed else '✗'} trade_allowed: {trade_allowed}")

        # Print fusion summary
        print(f"\n  {_info()} Fusion Summary for {symbol}:")
        print(f"    Session        : {session_info.get('primary_session')}")
        print(f"    Strategy       : {session_ctx.get('session_strategy')}")
        print(f"    Trade Allowed  : {trade_allowed}")
        print(f"    SMC Signal     : {smc_ctx.get('smc_signal')}")
        print(f"    SMC Score      : {smc_ctx.get('smc_score')}/100")
        print(f"    SMC Direction  : {smc_ctx.get('smc_direction')}")
        print(f"    Fusion Score   : {session_ctx.get('fusion_score', 'N/A')}")

    except Exception as e:
        result["errors"].append(f"Exception: {type(e).__name__}: {e}")
        result["errors"].append(traceback.format_exc().splitlines()[-1])
        print(f"  {_fail()} Exception: {type(e).__name__}: {e}")
        print(f"  {_info()} Full traceback:")
        for line in traceback.format_exc().splitlines()[-5:]:
            print(f"    {line}")

    return result


# ── Main ───────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="SMC + Session engine verification test."
    )
    parser.add_argument(
        "symbols", nargs="*", default=["EURUSD"],
        help="Symbols to test (default: EURUSD)",
    )
    parser.add_argument(
        "--synthetic", action="store_true",
        help="Use synthetic data instead of MT5 (for non-Windows testing)",
    )
    args = parser.parse_args()

    print()
    print(_c("=" * 70, "bold"))
    print(_c("  SMC + SESSION ENGINE VERIFICATION TEST", "bold"))
    print(_c("=" * 70, "bold"))
    print(f"  Symbols    : {', '.join(args.symbols)}")
    print(f"  Data mode  : {'synthetic' if args.synthetic else 'MT5 (real)'}")
    print(f"  Time       : {datetime.now().isoformat(timespec='seconds')}")
    print()

    all_results: List[Dict[str, Any]] = []

    # Test 1: Session Analyzer (run once, not per-symbol)
    all_results.append(test_session_analyzer())

    # Test 2 + 3: SMC Engine + Fusion (per symbol)
    for symbol in args.symbols:
        symbol = symbol.upper()
        all_results.append(test_smc_engine(symbol, use_synthetic=args.synthetic))
        all_results.append(test_smc_session_fusion(symbol, use_synthetic=args.synthetic))

    # ── Summary ────────────────────────────────────────────────────
    print()
    print(_c("=" * 70, "bold"))
    print(_c("  SUMMARY", "bold"))
    print(_c("=" * 70, "bold"))

    total_tests = 0
    passed_tests = 0
    total_errors = 0

    for r in all_results:
        module = r.get("module", "unknown")
        symbol = r.get("symbol", "")
        tests = r.get("tests", [])
        errors = r.get("errors", [])

        total_tests += len(tests)
        passed_tests += sum(1 for t in tests if t.get("passed"))
        total_errors += len(errors)

        header = f"{module}" + (f" [{symbol}]" if symbol else "")
        status = _pass() if not errors and all(t.get("passed") for t in tests) else _fail()
        print(f"  {status} {header}: {sum(1 for t in tests if t.get('passed'))}/{len(tests)} tests passed")

        if errors:
            for e in errors[:3]:  # show first 3 errors
                print(f"       {_fail()} {e}")

    print()
    print(f"  Total tests : {total_tests}")
    print(f"  Passed      : {_c(str(passed_tests), 'green')}")
    print(f"  Failed      : {_c(str(total_tests - passed_tests), 'red')}")
    print(f"  Errors      : {_c(str(total_errors), 'red')}")
    print()

    if total_errors == 0 and passed_tests == total_tests:
        print(_c("  ✅ All tests passed — SMC + Session engines are working correctly.", "green"))
    else:
        print(_c("  ❌ Some tests failed — see details above.", "red"))
        print(_c("     Common fixes:", "yellow"))
        print(_c("     - Install MetaTrader5 on Windows with MT5 terminal running", "yellow"))
        print(_c("     - Or run with --synthetic flag for non-MT5 testing", "yellow"))
        print(_c("     - Check that DEAD_ZONES is empty (Day 81+ hotfix)", "yellow"))

    print()
    return 0 if total_errors == 0 and passed_tests == total_tests else 1


if __name__ == "__main__":
    sys.exit(main())
