#!/usr/bin/env python3
"""
tests/steps/step_06_signal_engine.py
=====================================
STEP 6: Signal Engine Test

যা যা চেক করে:
  - SignalEngine instantiate হচ্ছে কিনা
  - analyze() সঠিক dict return করছে কিনা
  - Signal (BUY/SELL/WAIT) generate হচ্ছে কিনা
  - Confidence 0-100 range-এ আছে কিনা
  - Bull/bear score calculate হচ্ছে কিনা

Usage:
    python tests/steps/step_06_signal_engine.py
    python tests/steps/step_06_signal_engine.py GBPUSD
"""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(str(PROJECT_ROOT / ".env"))


def _pass(msg):  print(f"  \033[32m[PASS]\033[0m {msg}")
def _fail(msg):  print(f"  \033[31m[FAIL]\033[0m {msg}")
def _info(msg):  print(f"  \033[36m[INFO]\033[0m {msg}")
def _warn(msg):  print(f"  \033[33m[WARN]\033[0m {msg}")


def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else "EURUSD"
    symbol = symbol.upper()

    print("\n" + "=" * 60)
    print(f"  STEP 6: SIGNAL ENGINE TEST ({symbol})")
    print("=" * 60)

    # ── 1. Fetch data + indicators ──
    print(f"\n[1] {symbol} data + indicators...")
    try:
        from data.fetcher import DataFetcher
        from data.indicators import Indicators
        from analysis.patterns import PatternDetector
        from analysis.support_resistance import SupportResistance
        from analysis.fibonacci import FibonacciEngine

        df = DataFetcher().fetch_ohlcv(symbol, "15m", limit=300)
        if df is None or df.empty:
            _fail("Data fetch failed")
            return 1

        df = Indicators().add_all(df)
        df = PatternDetector().run_full_detection(df)
        sr = SupportResistance().analyze(df)
        fib = FibonacciEngine().analyze(df)
        _pass("Data + indicators + patterns ready")
    except Exception as e:
        _fail(f"Setup failed: {e}")
        return 1

    # ── 2. SignalEngine ──
    print(f"\n[2] SignalEngine generate...")
    try:
        from strategy.signal_engine import SignalEngine
        engine = SignalEngine()
        _pass("SignalEngine() created")

        # NOTE: SignalEngine has generate() method, NOT analyze()
        # mtf_bias expects a dict with keys: bias, confidence
        result = engine.generate(
            ind_ctx=Indicators().get_ai_context(df),
            pat_ctx=PatternDetector().get_ai_pattern_context(df),
            sr_ctx=sr,
            fib_ctx=fib,
            regime={"regime": "TRENDING", "volatility": "NORMAL"},
            mtf_bias={"bias": "BULLISH", "confidence": "HIGH"},
        )
        _pass("generate() completed")
    except Exception as e:
        _fail(f"SignalEngine failed: {type(e).__name__}: {e}")
        return 1

    # ── 3. Check result ──
    print(f"\n[3] Result verify...")
    required = {"signal", "confidence", "bull_score", "bear_score", "net_score"}
    missing = required - set(result.keys())
    if missing:
        _fail(f"Missing keys: {missing}")
        return 1
    _pass("All required keys present")

    # Signal
    signal = result.get("signal", "UNKNOWN")
    if signal not in ("STRONG_BUY", "BUY", "WAIT", "SELL", "STRONG_SELL", "NO TRADE"):
        _fail(f"Invalid signal: {signal}")
        return 1
    _pass(f"Signal: {signal}")

    # Confidence
    conf = result.get("confidence", -1)
    if not (0 <= conf <= 100):
        _fail(f"Confidence {conf} out of range [0,100]")
        return 1
    _pass(f"Confidence: {conf}%")

    # Scores
    _info(f"  Bull score: {result.get('bull_score')}")
    _info(f"  Bear score: {result.get('bear_score')}")
    _info(f"  Net score:  {result.get('net_score')}")
    _info(f"  Recommendation: {result.get('recommendation', 'N/A')}")

    # ── Summary ──
    print("\n" + "=" * 60)
    print(f"  ✅ STEP 6 PASSED — Signal Engine ঠিকভাবে কাজ করছে ({symbol})")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
