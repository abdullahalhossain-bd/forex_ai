#!/usr/bin/env python3
"""
tests/steps/step_01_mt5_connection.py
======================================
STEP 1: MT5 Connection Test

যা যা চেক করে:
  - MetaTrader5 package installed কিনা
  - MT5 terminal initialize হচ্ছে কিনা
  - Login সফল হচ্ছে কিনা
  - Account info পাওয়া যাচ্ছে কিনা (balance/equity/margin)
  - Trade allowed কিনা

Usage:
    python tests/steps/step_01_mt5_connection.py
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
    print("  STEP 1: MT5 CONNECTION TEST")
    print("=" * 60)

    # ── 1. Check MetaTrader5 package ──
    print("\n[1] MetaTrader5 package install করা আছে কিনা...")
    try:
        import MetaTrader5 as mt5
        _pass(f"MetaTrader5 package found (version: {mt5.__version__ if hasattr(mt5, '__version__') else 'unknown'})")
    except ImportError:
        _fail("MetaTrader5 package ইনস্টল করা নেই")
        print(f"\n  সমাধান: pip install MetaTrader5")
        print(f"  নোট: MetaTrader5 শুধু Windows-এ কাজ করে, MT5 terminal চালু থাকা লাগবে")
        return 1

    # ── 2. Check .env credentials ──
    print("\n[2] .env-তে MT5 credentials আছে কিনা...")
    login = os.getenv("MT5_LOGIN")
    password = os.getenv("MT5_PASSWORD")
    server = os.getenv("MT5_SERVER")

    if not login:
        _fail("MT5_LOGIN .env-তে নেই")
        return 1
    if not password:
        _fail("MT5_PASSWORD .env-তে নেই")
        return 1
    if not server:
        _fail("MT5_SERVER .env-তে নেই")
        return 1
    _pass(f"Credentials found: login={login}, server={server}")

    # ── 3. Initialize MT5 ──
    print("\n[3] MT5 terminal initialize...")
    path = os.getenv("MT5_PATH") or None
    init_kwargs = {"path": path} if path else {}

    if not mt5.initialize(**init_kwargs):
        err = mt5.last_error()
        _fail(f"mt5.initialize() failed: {err}")
        print(f"\n  সমাধান:")
        print(f"  1. MT5 terminal চালু করুন")
        print(f"  2. একই account-এ login করুন")
        print(f"  3. আবার চেষ্টা করুন")
        return 1
    _pass("MT5 terminal initialized")

    # ── 4. Login ──
    print("\n[4] Login করছে...")
    try:
        login_int = int(login)
    except ValueError:
        _fail(f"MT5_LOGIN একটা number হতে হবে, পাওয়া গেছে: '{login}'")
        mt5.shutdown()
        return 1

    if not mt5.login(login=login_int, password=password, server=server):
        err = mt5.last_error()
        _fail(f"Login failed: {err}")
        print(f"\n  সমাধান:")
        print(f"  - Login/password/server ঠিক আছে কিনা যাচাই করুন")
        print(f"  - MT5 terminal-এ manually login করে দেখুন")
        mt5.shutdown()
        return 1
    _pass(f"Login successful (account: {login_int})")

    # ── 5. Account info ──
    print("\n[5] Account info পড়ছে...")
    info = mt5.account_info()
    if info is None:
        _fail(f"account_info() returned None: {mt5.last_error()}")
        mt5.shutdown()
        return 1

    _pass(f"Balance:      ${info.balance:.2f}")
    _pass(f"Equity:       ${info.equity:.2f}")
    _pass(f"Margin:       ${info.margin:.2f}")
    _pass(f"Free Margin:  ${info.margin_free:.2f}")
    _pass(f"Margin Level: {info.margin_level:.1f}%")
    _pass(f"Currency:     {info.currency}")
    _pass(f"Leverage:     1:{info.leverage}")
    _pass(f"Trade Allowed: {info.trade_allowed}")

    if not info.trade_allowed:
        _warn("trade_allowed=False — সম্ভবত market closed অথবা account restricted")

    # ── 6. Cleanup ──
    mt5.shutdown()
    _pass("MT5 connection shutdown")

    # ── Summary ──
    print("\n" + "=" * 60)
    print("  ✅ STEP 1 PASSED — MT5 connection ঠিকভাবে কাজ করছে")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
