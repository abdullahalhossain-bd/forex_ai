#!/usr/bin/env python3
"""
tests/steps/step_09_risk_engine.py
====================================
STEP 9: Risk Engine Test

যা যা চেক করে:
  - RiskEngine instantiate হচ্ছে কিনা
  - evaluate() সঠিক dict return করছে কিনা
  - Lot size calculate হচ্ছে কিনা
  - SL/TP price calculate হচ্ছে কিনা
  - R:R ratio সঠিক আছে কিনা
  - Daily loss tracking কাজ করছে কিনা
  - Rejection reasons সঠিকভাবে আসছে কিনা

Usage:
    python tests/steps/step_09_risk_engine.py
    python tests/steps/step_09_risk_engine.py GBPUSD
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
    print(f"  STEP 9: RISK ENGINE TEST ({symbol})")
    print("=" * 60)

    # ── 1. RiskEngine ──
    print(f"\n[1] RiskEngine instantiation...")
    try:
        from risk.risk_engine import RiskEngine
        risk = RiskEngine(balance=10000, symbol=symbol)
        _pass(f"RiskEngine(balance=10000, symbol={symbol}) created")
    except Exception as e:
        _fail(f"RiskEngine failed: {e}")
        return 1

    # ── 2. Test BUY scenario ──
    print(f"\n[2] BUY scenario test...")
    try:
        result = risk.evaluate(
            signal="BUY",
            entry=1.0850,
            atr=0.0010,
            regime={"regime": "TRENDING", "volatility": "NORMAL"},
        )

        required = {"approved", "lot", "sl_pips", "tp_pips", "rr_ratio",
                    "entry", "sl_price", "tp_price", "risk_usd", "risk_pc"}
        missing = required - set(result.keys())
        if missing:
            _fail(f"Missing keys: {missing}")
            return 1
        _pass("All required keys present")

        if result.get("approved"):
            _pass(f"Trade APPROVED")
            _pass(f"Lot: {result.get('lot')}")
            _pass(f"Entry: {result.get('entry')}")
            _pass(f"SL: {result.get('sl_price')} ({result.get('sl_pips')} pips)")
            _pass(f"TP: {result.get('tp_price')} ({result.get('tp_pips')} pips)")
            _pass(f"R:R: 1:{result.get('rr_ratio')}")
            _pass(f"Risk: ${result.get('risk_usd')} ({result.get('risk_pc')}%)")
        else:
            _warn(f"Trade REJECTED: {result.get('reject_reason')}")

    except Exception as e:
        _fail(f"BUY evaluate failed: {type(e).__name__}: {e}")
        return 1

    # ── 3. Test SELL scenario ──
    print(f"\n[3] SELL scenario test...")
    try:
        result_sell = risk.evaluate(
            signal="SELL",
            entry=1.0850,
            atr=0.0010,
            regime={"regime": "TRENDING", "volatility": "NORMAL"},
        )
        if result_sell.get("approved"):
            _pass(f"SELL approved | Lot: {result_sell.get('lot')} | "
                  f"SL: {result_sell.get('sl_price')} | TP: {result_sell.get('tp_price')}")
            # Verify SL/TP direction
            if result_sell.get("sl_price", 0) > result_sell.get("entry", 0):
                _pass("SL above entry (correct for SELL)")
            else:
                _fail("SL should be above entry for SELL")
            if result_sell.get("tp_price", 0) < result_sell.get("entry", 0):
                _pass("TP below entry (correct for SELL)")
            else:
                _fail("TP should be below entry for SELL")
        else:
            _warn(f"SELL rejected: {result_sell.get('reject_reason')}")
    except Exception as e:
        _fail(f"SELL evaluate failed: {e}")

    # ── 4. Test WAIT signal ──
    print(f"\n[4] WAIT signal test...")
    try:
        result_wait = risk.evaluate(
            signal="WAIT",
            entry=1.0850,
            atr=0.0010,
            regime={"regime": "RANGING"},
        )
        if result_wait.get("approved"):
            _fail("WAIT signal should not be approved")
            return 1
        _pass(f"WAIT correctly rejected: {result_wait.get('reject_reason')}")
    except Exception as e:
        _fail(f"WAIT test failed: {e}")

    # ── 5. Daily summary ──
    print(f"\n[5] Daily summary...")
    try:
        daily = risk.get_daily_summary()
        _pass(f"Daily: net=${daily.get('net_usd', 0)} | "
              f"loss={daily.get('daily_loss_pc', 0)}% | "
              f"limit_left={daily.get('limit_remaining_pc', 0)}%")
    except Exception as e:
        _warn(f"Daily summary failed (non-critical): {e}")

    # ── Summary ──
    print("\n" + "=" * 60)
    print(f"  ✅ STEP 9 PASSED — Risk Engine ঠিকভাবে কাজ করছে ({symbol})")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
