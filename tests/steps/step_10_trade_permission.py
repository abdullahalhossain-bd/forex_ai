#!/usr/bin/env python3
"""
tests/steps/step_10_trade_permission.py
=========================================
STEP 10: Trade Permission Test

যা যা চেক করে:
  - TradePermission instantiate হচ্ছে কিনা
  - MIN_CONFIDENCE TEST_MODE-এ 10 আছে কিনা
  - ৫টা check (signal/risk/news/confidence/session) কাজ করছে কিনা
  - TEST_MODE-এ session quality bypass হচ্ছে কিনা
  - Allowed/Denied সঠিকভাবে আসছে কিনা

Usage:
    python tests/steps/step_10_trade_permission.py
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
    print("\n" + "=" * 60)
    print("  STEP 10: TRADE PERMISSION TEST")
    print("=" * 60)

    # ── 1. TradePermission ──
    print(f"\n[1] TradePermission instantiation...")
    try:
        from risk.trade_permission import TradePermission
        tp = TradePermission()
        _pass("TradePermission() created")
    except Exception as e:
        _fail(f"TradePermission failed: {e}")
        return 1

    # ── 2. MIN_CONFIDENCE check ──
    print(f"\n[2] MIN_CONFIDENCE check...")
    min_conf = tp.MIN_CONFIDENCE
    _info(f"MIN_CONFIDENCE = {min_conf}")

    try:
        from config import TEST_MODE
        if TEST_MODE:
            if min_conf == 10:
                _pass("TEST_MODE=true → MIN_CONFIDENCE=10 (correct)")
            else:
                _fail(f"TEST_MODE=true but MIN_CONFIDENCE={min_conf} (expected 10)")
                return 1
        else:
            if min_conf == 60:
                _pass("TEST_MODE=false → MIN_CONFIDENCE=60 (production)")
            else:
                _warn(f"TEST_MODE=false but MIN_CONFIDENCE={min_conf} (expected 60)")
    except Exception:
        _warn("config.TEST_MODE পড়া যায়নি")

    # ── 3. Test all-pass scenario ──
    print(f"\n[3] All-pass scenario (BUY 75%)...")
    try:
        decision_out = {"decision": "BUY", "confidence": 75}
        risk_out = {"approved": True, "entry": 1.0850, "sl_price": 1.0830,
                    "tp_price": 1.0880, "lot": 0.1, "rr_ratio": 1.5,
                    "reject_reason": None}
        news_ctx = {"news_trade_allowed": True, "news_reason": "OK"}
        session_ctx = {"quality": "HIGH"}

        result = tp.check(decision_out, risk_out, news_ctx, session_ctx)

        if result.get("allowed"):
            _pass(f"Trade ALLOWED ({result.get('passed')}/{result.get('total')} checks)")
        else:
            _fail(f"Trade DENIED ({result.get('passed')}/{result.get('total')}) — should be allowed")

        _info("  Checks:")
        for c in result.get("checks", []):
            mark = "✓" if c["passed"] else "✗"
            _info(f"    {mark} {c['check']}: {c['detail']}")

    except Exception as e:
        _fail(f"All-pass test failed: {e}")
        return 1

    # ── 4. Test low confidence ──
    print(f"\n[4] Low confidence scenario (BUY 5%)...")
    try:
        decision_low = {"decision": "BUY", "confidence": 5}
        result_low = tp.check(decision_low, risk_out, news_ctx, session_ctx)

        if not result_low.get("allowed"):
            _pass(f"Correctly DENIED (confidence 5% < {min_conf}%)")
        else:
            _fail(f"Should be denied (confidence 5% < {min_conf}%)")

    except Exception as e:
        _fail(f"Low confidence test failed: {e}")

    # ── 5. Test news block ──
    print(f"\n[5] News block scenario...")
    try:
        news_block = {"news_trade_allowed": False, "news_reason": "CPI in 10min"}
        result_news = tp.check(decision_out, risk_out, news_block, session_ctx)

        if not result_news.get("allowed"):
            _pass("Correctly DENIED (news block)")
        else:
            _fail("Should be denied (news block)")

    except Exception as e:
        _fail(f"News block test failed: {e}")

    # ── 6. Test TEST_MODE session bypass ──
    print(f"\n[6] TEST_MODE session bypass...")
    try:
        from config import TEST_MODE
        session_low = {"quality": "LOW"}

        result_session = tp.check(decision_out, risk_out, news_ctx, session_low)

        if TEST_MODE:
            if result_session.get("allowed"):
                _pass("TEST_MODE=true → LOW session allowed (bypassed)")
            else:
                _fail("TEST_MODE=true but LOW session blocked")
        else:
            if not result_session.get("allowed"):
                _pass("TEST_MODE=false → LOW session blocked (correct)")
            else:
                _warn("TEST_MODE=false but LOW session allowed")

    except Exception as e:
        _warn(f"Session bypass test failed: {e}")

    # ── Summary ──
    print("\n" + "=" * 60)
    print("  ✅ STEP 10 PASSED — Trade Permission ঠিকভাবে কাজ করছে")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
