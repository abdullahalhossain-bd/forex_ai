#!/usr/bin/env python3
"""
tests/steps/step_04_smc_engine.py
==================================
STEP 4: SMC Engine Test

যা যা চেক করে:
  - SMCEngine instantiate হচ্ছে কিনা
  - H4 + M15 data fetch হচ্ছে কিনা
  - Order Block detection কাজ করছে কিনা
  - FVG detection কাজ করছে কিনা
  - BOS / CHoCH detection কাজ করছে কিনা
  - Liquidity Sweep detection কাজ করছে কিনা
  - Confluence score calculate হচ্ছে কিনা
  - Signal (BUY/SELL/WAIT) generate হচ্ছে কিনা

Usage:
    python tests/steps/step_04_smc_engine.py
    python tests/steps/step_04_smc_engine.py GBPUSD XAUUSD
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


def test_symbol(symbol):
    print(f"\n[{symbol}] SMC analysis চালাচ্ছে...")
    try:
        from analysis.smc_engine import SMCEngine
        smc = SMCEngine(symbol)
        _pass(f"SMCEngine({symbol}) created")

        result = smc.analyze()

        # Check result structure
        required = {"symbol", "current_price", "h4", "m15",
                    "confluence_score", "confluence_factors",
                    "direction", "grade", "signal", "analysis"}
        missing = required - set(result.keys())
        if missing:
            _fail(f"Result missing keys: {missing}")
            return False
        _pass("Result structure valid")

        # Check H4 components
        h4 = result.get("h4", {})
        h4_components = ["order_blocks", "fvgs", "bos", "choch", "liquidity_sweep"]
        h4_missing = [c for c in h4_components if c not in h4]
        if h4_missing:
            _fail(f"H4 missing: {h4_missing}")
            return False
        _pass(f"H4 components present (OB={len(h4.get('order_blocks', []))}, "
              f"FVG={len(h4.get('fvgs', []))})")

        # BOS / CHoCH
        bos = h4.get("bos", {})
        choch = h4.get("choch", {})
        _info(f"  H4 BOS:   {bos.get('type', 'NONE')}")
        _info(f"  H4 CHoCH: {choch.get('type', 'NONE')}")

        # Liquidity sweep
        sweep = h4.get("liquidity_sweep", {})
        _info(f"  H4 Sweep: {sweep.get('type', 'NONE')}")

        # Confluence score
        score = result.get("confluence_score", 0)
        if not (0 <= score <= 100):
            _fail(f"Score {score} out of range [0,100]")
            return False
        _pass(f"Confluence score: {score}/100")

        # Factors
        factors = result.get("confluence_factors", {})
        _info("  Factors:")
        for name, active in factors.items():
            mark = "✅" if active else "❌"
            _info(f"    {mark} {name}")

        # Signal
        signal = result.get("signal", "UNKNOWN")
        if signal not in ("BUY", "SELL", "WAIT"):
            _fail(f"Invalid signal: {signal}")
            return False
        _pass(f"Signal: {signal} | Direction: {result.get('direction')} | Grade: {result.get('grade')}")

        # Analysis text
        analysis = result.get("analysis", "")
        if analysis:
            _info(f"  Analysis: {analysis[:120]}")

        return True

    except Exception as e:
        _fail(f"{symbol}: Exception — {type(e).__name__}: {e}")
        import traceback
        _info(traceback.format_exc().splitlines()[-1])
        return False


def main():
    symbols = sys.argv[1:] if len(sys.argv) > 1 else ["EURUSD"]
    symbols = [s.upper() for s in symbols]

    print("\n" + "=" * 60)
    print("  STEP 4: SMC ENGINE TEST")
    print("=" * 60)

    # Init MT5
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            _fail(f"MT5 initialize failed: {mt5.last_error()}")
            return 1
        _pass("MT5 initialized")
    except ImportError:
        _fail("MetaTrader5 package নেই")
        return 1

    all_passed = True
    for symbol in symbols:
        if not test_symbol(symbol):
            all_passed = False

    import MetaTrader5 as mt5
    mt5.shutdown()

    print("\n" + "=" * 60)
    if all_passed:
        print("  ✅ STEP 4 PASSED — SMC Engine ঠিকভাবে কাজ করছে")
    else:
        print("  ❌ STEP 4 FAILED — SMC Engine-এ সমস্যা আছে")
    print("=" * 60)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
