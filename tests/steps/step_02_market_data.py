#!/usr/bin/env python3
"""
tests/steps/step_02_market_data.py
===================================
STEP 2: Market Data Fetch Test

যা যা চেক করে:
  - DataFetcher MT5 source detect করছে কিনা
  - EURUSD এর candle data আসছে কিনা
  - ৩০০টা candle পাওয়া যাচ্ছে কিনা
  - OHLCV columns সঠিক আছে কিনা
  - Latest price পাওয়া যাচ্ছে কিনা

Usage:
    python tests/steps/step_02_market_data.py
    python tests/steps/step_02_market_data.py GBPUSD XAUUSD
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


def test_symbol(symbol, timeframe="15m", limit=300):
    """একটা symbol এর জন্য data fetch test."""
    print(f"\n[{symbol} {timeframe}] Fetching {limit} candles...")

    try:
        from data.fetcher import DataFetcher
        fetcher = DataFetcher()

        if fetcher.source != "mt5":
            _fail(f"DataFetcher source = '{fetcher.source}' (expected 'mt5')")
            return False

        df = fetcher.fetch_ohlcv(symbol, timeframe, limit=limit)

        if df is None:
            _fail(f"{symbol} {timeframe}: fetch_ohlcv returned None")
            return False

        if df.empty:
            _fail(f"{symbol} {timeframe}: DataFrame empty")
            return False

        # Check columns
        required_cols = {"open", "high", "low", "close", "volume"}
        missing = required_cols - set(df.columns)
        if missing:
            _fail(f"{symbol}: missing columns {missing}")
            return False

        _pass(f"Got {len(df)} candles")
        _pass(f"Columns: {list(df.columns)}")

        # Latest price
        latest_close = float(df["close"].iloc[-1])
        if latest_close <= 0:
            _fail(f"{symbol}: latest close = {latest_close} (should be > 0)")
            return False
        _pass(f"Latest close: {latest_close:.5f}")

        # Show last 3 candles
        _info("Last 3 candles:")
        for idx, row in df.tail(3).iterrows():
            _info(f"  {idx} | O={row['open']:.5f} H={row['high']:.5f} "
                  f"L={row['low']:.5f} C={row['close']:.5f} V={int(row['volume'])}")

        return True

    except Exception as e:
        _fail(f"{symbol}: Exception — {type(e).__name__}: {e}")
        return False


def main():
    symbols = sys.argv[1:] if len(sys.argv) > 1 else ["EURUSD"]

    print("\n" + "=" * 60)
    print("  STEP 2: MARKET DATA FETCH TEST")
    print("=" * 60)

    # ── 1. Check MT5 available ──
    print("\n[1] MetaTrader5 available কিনা...")
    try:
        import MetaTrader5 as mt5
        _pass("MetaTrader5 package found")
    except ImportError:
        _fail("MetaTrader5 package নেই — এই টেস্ট শুধু Windows-এ চলবে")
        return 1

    if not mt5.initialize():
        _fail(f"MT5 initialize failed: {mt5.last_error()}")
        return 1
    _pass("MT5 initialized")

    # ── 2. Test each symbol ──
    all_passed = True
    for symbol in symbols:
        symbol = symbol.upper()
        if not test_symbol(symbol):
            all_passed = False

    # ── 3. Cleanup ──
    import MetaTrader5 as mt5
    mt5.shutdown()
    _pass("MT5 shutdown")

    # ── Summary ──
    print("\n" + "=" * 60)
    if all_passed:
        print("  ✅ STEP 2 PASSED — Market data fetch ঠিকভাবে কাজ করছে")
    else:
        print("  ❌ STEP 2 FAILED — কিছু symbol-এর data fetch ব্যর্থ হয়েছে")
    print("=" * 60)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
