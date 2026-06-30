#!/usr/bin/env python3
"""
tests/steps/step_05_session.py
================================
STEP 5: Session Analyzer Test

যা যা চেক করে:
  - DEAD_ZONES খালি আছে কিনা (Day 81+ hotfix)
  - ২৪ ঘন্টার প্রতিটার জন্য session detection
  - DST detection কাজ করছে কিনা
  - Strategy mode সঠিকভাবে select হচ্ছে কিনা
  - trade_allowed সব session-এ True (dead zone removed)
  - Pair preference কাজ করছে কিনা

Usage:
    python tests/steps/step_05_session.py
"""
import os
import sys
from datetime import datetime, timezone
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
    print("  STEP 5: SESSION ANALYZER TEST")
    print("=" * 60)

    try:
        from analysis.session_analyzer import SessionAnalyzer
        from analysis.session_rules import DEAD_ZONES
    except ImportError as e:
        _fail(f"Import failed: {e}")
        return 1

    sa = SessionAnalyzer()
    _pass("SessionAnalyzer() created")

    # ── 1. DEAD_ZONES empty ──
    print("\n[1] DEAD_ZONES খালি কিনা...")
    if len(DEAD_ZONES) > 0:
        _fail(f"DEAD_ZONES = {DEAD_ZONES} (খালি হওয়া উচিত)")
        return 1
    _pass("DEAD_ZONES = [] (Day 81+ hotfix active)")

    # ── 2. 24-hour session detection ──
    print("\n[2] ২৪ ঘন্টার session detection...")
    sessions_seen = set()
    all_ok = True
    for hour in range(24):
        dt = datetime(2026, 6, 24, hour, 0, tzinfo=timezone.utc)
        sess = sa.get_current_session(dt)

        primary = sess.get("primary_session", "UNKNOWN")
        sessions_seen.add(primary)

        if sess.get("is_dead_zone"):
            _fail(f"Hour {hour:02d}: is_dead_zone=True (should be False)")
            all_ok = False

    if all_ok:
        _pass("সব ২৪ ঘন্টায় is_dead_zone=False")
    else:
        _fail("কিছু ঘন্টায় dead_zone=True")

    _info(f"Sessions detected: {sorted(sessions_seen)}")

    # Expected sessions
    expected = {"LONDON", "NEW_YORK", "TOKYO", "SYDNEY", "LONDON_NY_OVERLAP", "BETWEEN_SESSIONS"}
    missing = expected - sessions_seen
    if missing:
        _warn(f"Missing sessions: {missing}")
    else:
        _pass("সব expected sessions detect হচ্ছে")

    # ── 3. DST detection ──
    print("\n[3] DST detection...")
    us_dst = sa._is_us_dst(datetime(2026, 6, 24, tzinfo=timezone.utc))
    eu_dst = sa._is_eu_dst(datetime(2026, 6, 24, tzinfo=timezone.utc))
    if us_dst and eu_dst:
        _pass(f"June DST: US={us_dst}, EU={eu_dst}")
    else:
        _fail(f"June DST: US={us_dst}, EU={eu_dst} (দুটোই True হওয়া উচিত)")

    # ── 4. Strategy modes ──
    print("\n[4] Strategy modes...")
    strategies_ok = True
    for session in ["LONDON", "NEW_YORK", "TOKYO", "SYDNEY", "LONDON_NY_OVERLAP"]:
        strat = sa.get_strategy_mode(session, gmt_hour=9)
        if not strat.get("strategy"):
            _fail(f"{session}: no strategy")
            strategies_ok = False
        elif not strat.get("trade_allowed"):
            _fail(f"{session}: trade_allowed=False")
            strategies_ok = False
        else:
            _info(f"  {session}: {strat['strategy']} (trade={strat['trade_allowed']})")

    if strategies_ok:
        _pass("সব session-এ trade_allowed=True")

    # ── 5. Current session ──
    print("\n[5] Current session...")
    current = sa.get_current_session()
    _pass(f"Current: {current['primary_session']} ({current['gmt_time']})")
    _pass(f"is_dead_zone: {current['is_dead_zone']}")
    _pass(f"is_overlap: {current['is_overlap']}")
    _pass(f"london_open_window: {current['london_open_window']}")

    # ── 6. Full analyze with SMC ──
    print("\n[6] Full analyze() with SMC fusion...")
    try:
        full = sa.analyze(pair="EURUSD", smc_ctx={"smc_signal": "BUY", "smc_score": 75})
        trade_allowed = full.get("trade_allowed", False)
        if trade_allowed:
            _pass(f"Full analyze: trade_allowed=True")
        else:
            _fail(f"Full analyze: trade_allowed=False")
            all_ok = False
        _info(f"  Session: {full.get('session_info', {}).get('primary_session')}")
    except Exception as e:
        _fail(f"Full analyze failed: {e}")
        all_ok = False

    # ── Summary ──
    print("\n" + "=" * 60)
    if all_ok and strategies_ok:
        print("  ✅ STEP 5 PASSED — Session Analyzer ঠিকভাবে কাজ করছে")
    else:
        print("  ❌ STEP 5 FAILED — Session Analyzer-এ সমস্যা আছে")
    print("=" * 60)
    return 0 if (all_ok and strategies_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
