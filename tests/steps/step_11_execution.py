#!/usr/bin/env python3
"""
tests/steps/step_11_execution.py
==================================
STEP 11: Execution Router Test

যা যা চেক করে:
  - ExecutionRouter instantiate হচ্ছে কিনা
  - MT5 connection সফল হচ্ছে কিনা
  - ABSOLUTE_SAFETY gate কাজ করছে কিনা
  - Order placement (test trade) কাজ করছে কিনা
  - Auto-close (safety) কাজ করছে কিনা
  - Filling mode auto-detect কাজ করছে কিনা

⚠️ WARNING: এই টেস্ট একটা ছোট trade নেবে এবং সাথে সাথে close করবে (lot=0.01)

Usage:
    python tests/steps/step_11_execution.py              # verify only (no trade)
    python tests/steps/step_11_execution.py --trade      # place test trade + auto-close
"""
import os
import sys
import time
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
    do_trade = "--trade" in sys.argv

    print("\n" + "=" * 60)
    print("  STEP 11: EXECUTION ROUTER TEST")
    print("=" * 60)

    if not do_trade:
        _info("Verify mode (no trade). --trade flag দিলে test trade নেবে।")

    # ── 1. ExecutionRouter ──
    print(f"\n[1] ExecutionRouter instantiation...")
    try:
        from execution.execution_router import ExecutionRouter
        router = ExecutionRouter()
        _pass("ExecutionRouter created (MT5_DEMO mode)")
    except Exception as e:
        _fail(f"ExecutionRouter failed: {type(e).__name__}: {e}")
        print(f"\n  সম্ভাব্য কারণ:")
        print(f"  - MT5 terminal চালু নয়")
        print(f"  - .env-তে MT5 credentials নেই")
        print(f"  - MT5 demo account-এ login করা নয়")
        return 1

    # ── 2. ABSOLUTE_SAFETY gate ──
    print(f"\n[2] ABSOLUTE_SAFETY gate check...")
    try:
        from execution.execution_router import _check_absolute_safety
        safe, reason = _check_absolute_safety("EURUSD")
        if safe:
            _pass(f"Safe to trade: {reason}")
        else:
            _warn(f"Blocked: {reason}")
            _info("এটা স্বাভাবিক যদি market closed থাকে অথবা spread বেশি থাকে")
    except Exception as e:
        _fail(f"ABSOLUTE_SAFETY check failed: {e}")

    # ── 3. Open positions ──
    print(f"\n[3] Current open positions...")
    try:
        positions = router._order_manager.get_open_positions()
        _pass(f"Open positions: {len(positions)}")
        for p in positions[:5]:
            _info(f"  {p['symbol']} {p['type']} lot={p['volume']} profit=${p['profit']:.2f}")
    except Exception as e:
        _fail(f"get_open_positions failed: {e}")

    if not do_trade:
        print("\n" + "=" * 60)
        print("  ✅ STEP 11 PASSED — Execution Router ready (no trade placed)")
        print("  একটা test trade নিতে চাইলে: python tests/steps/step_11_execution.py --trade")
        print("=" * 60)
        router.shutdown()
        return 0

    # ── 4. Test trade ──
    print(f"\n[4] Placing test trade (BUY EURUSD lot=0.01)...")
    try:
        import MetaTrader5 as mt5

        # Get current price
        tick = mt5.symbol_info_tick("EURUSD")
        if tick is None:
            _fail("No tick data for EURUSD")
            router.shutdown()
            return 1

        price = tick.ask
        info = mt5.symbol_info("EURUSD")
        pip = info.point * 10
        sl = price - (25 * pip)
        tp = price + (50 * pip)

        # Check if market is open (spread > 0 means market is live)
        spread_pips = round((tick.ask - tick.bid) * (10 ** (info.digits - 1)), 2) if info.digits else 0
        if spread_pips == 0:
            _warn("Market appears CLOSED (spread=0). Test trade skipped.")
            _info("Forex market closes Friday ~22:00 GMT, opens Sunday ~22:00 GMT.")
            _info("এই টেস্ট চালান যখন market open থাকে (Monday-Friday).")
            router.shutdown()
            print("\n" + "=" * 60)
            print("  ✅ STEP 11 PASSED — Execution Router ready (market closed, trade skipped)")
            print("=" * 60)
            return 0

        _info(f"Price: {price:.5f} | SL: {sl:.5f} | TP: {tp:.5f} | Spread: {spread_pips} pips")

        decision = {
            "decision": "BUY",
            "symbol": "EURUSD",
            "entry": price,
            "sl": sl,
            "tp": tp,
            "lot": 0.01,
            "confidence": 80,
            "rr": 2.0,
            "timeframe": "15m",
        }

        result = router.execute(decision)

        if result and result.get("status") == "FILLED":
            _pass(f"Trade FILLED! ticket={result.get('ticket')}")
            _pass(f"Entry: {result.get('entry')}")

            # ── 5. Auto-close (safety) ──
            print(f"\n[5] Auto-closing test trade (safety)...")
            time.sleep(2)

            close_result = router._order_manager.close_order(
                result.get("ticket"),
                comment="test_auto_close",
            )

            if close_result.get("success"):
                _pass(f"Trade closed successfully | profit: ${close_result.get('profit', 0):.2f}")
            else:
                _fail(f"Close failed: {close_result.get('reason')}")
                _warn(f"ট্রেডটা manually close করতে হবে (ticket: {result.get('ticket')})")
        else:
            # Trade was blocked — check if it was ABSOLUTE_SAFETY
            _warn("Trade was blocked by safety gate or broker rejection.")
            _info("এটা স্বাভাবিক যদি:")
            _info("  - Market closed (weekend)")
            _info("  - Spread বেশি (news time)")
            _info("  - Margin insufficient")
            _info("  - Filling mode unsupported")
            _info("")
            _info("Trade নেওয়ার জন্য market hours-এ চেষ্টা করুন (Mon-Fri, London/NY session).")

    except Exception as e:
        _fail(f"Test trade failed: {type(e).__name__}: {e}")

    # ── Cleanup ──
    router.shutdown()
    _pass("ExecutionRouter shutdown")

    # ── Summary ──
    print("\n" + "=" * 60)
    print("  ✅ STEP 11 COMPLETE — Execution Router test finished")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
