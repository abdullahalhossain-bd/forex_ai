#!/usr/bin/env python3
"""
tests/steps/step_03_indicators.py
==================================
STEP 3: Technical Indicators Test

যা যা চেক করে:
  - Indicators class instantiate হচ্ছে কিনা
  - RSI, EMA, SMA, ATR, MACD সব ক্যালকুলেট হচ্ছে কিনা
  - Values NaN না (valid float)
  - AI context dict সঠিকভাবে generate হচ্ছে

Usage:
    python tests/steps/step_03_indicators.py
    python tests/steps/step_03_indicators.py GBPUSD
"""
import os
import sys
import math
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
    print(f"  STEP 3: TECHNICAL INDICATORS TEST ({symbol})")
    print("=" * 60)

    # ── 1. Fetch data first ──
    print(f"\n[1] {symbol} এর candle data আনছে...")
    try:
        from data.fetcher import DataFetcher
        fetcher = DataFetcher()
        if fetcher.source != "mt5":
            _fail(f"DataFetcher source = '{fetcher.source}' (MT5 দরকার)")
            return 1
        df = fetcher.fetch_ohlcv(symbol, "15m", limit=300)
        if df is None or df.empty:
            _fail(f"{symbol} data fetch failed")
            return 1
        _pass(f"Got {len(df)} candles")
    except Exception as e:
        _fail(f"Data fetch exception: {e}")
        return 1

    # ── 2. Indicators class ──
    print(f"\n[2] Indicators class instantiate...")
    try:
        from data.indicators import Indicators
        ind = Indicators()
        _pass("Indicators() created")
    except ImportError as e:
        _fail(f"Indicators import failed: {e}")
        print(f"  সমাধান: pip install ta")
        return 1
    except Exception as e:
        _fail(f"Indicators instantiation failed: {e}")
        return 1

    # ── 3. Add all indicators ──
    print(f"\n[3] সব indicators যোগ করছে...")
    try:
        df = ind.add_all(df)
        _pass(f"add_all() completed — {len(df.columns)} columns total")
    except Exception as e:
        _fail(f"add_all() failed: {type(e).__name__}: {e}")
        return 1

    # ── 4. Check individual indicators ──
    print(f"\n[4] প্রতিটা indicator verify করছে...")
    last_row = df.iloc[-1]

    # NOTE: Indicators class uses underscores in column names
    # (ema_9, ema_21, sma_20, sma_50, sma_200) — NOT ema9/sma20 etc.
    indicators_to_check = [
        ("rsi",      "RSI",       0,   100),
        ("ema_9",    "EMA 9",     None, None),
        ("ema_21",   "EMA 21",    None, None),
        ("sma_20",   "SMA 20",    None, None),
        ("sma_50",   "SMA 50",    None, None),
        ("sma_200",  "SMA 200",   None, None),
        ("atr",      "ATR",       0,    None),
        ("macd",     "MACD",      None, None),
        ("trend",    "Trend",     None, None),
        ("rsi_signal","RSI Signal",None, None),
    ]

    all_ok = True
    for col, name, min_val, max_val in indicators_to_check:
        if col not in df.columns:
            _fail(f"{name}: column '{col}' missing")
            all_ok = False
            continue

        val = last_row[col]
        if isinstance(val, float) and math.isnan(val):
            _fail(f"{name}: NaN value")
            all_ok = False
            continue

        if min_val is not None and isinstance(val, (int, float)) and val < min_val:
            _fail(f"{name}: {val} < {min_val}")
            all_ok = False
            continue

        if max_val is not None and isinstance(val, (int, float)) and val > max_val:
            _fail(f"{name}: {val} > {max_val}")
            all_ok = False
            continue

        if isinstance(val, float):
            _pass(f"{name}: {val:.5f}")
        else:
            _pass(f"{name}: {val}")

    # ── 5. AI context ──
    print(f"\n[5] AI context dict generate...")
    try:
        ctx = ind.get_ai_context(df)
        if not isinstance(ctx, dict):
            _fail(f"get_ai_context returned {type(ctx)} (dict expected)")
            return 1

        # NOTE: get_ai_context uses "price" key, not "close"
        required_keys = {"price", "trend", "rsi", "atr"}
        missing = required_keys - set(ctx.keys())
        if missing:
            _fail(f"AI context missing keys: {missing}")
            return 1

        _pass(f"AI context keys ({len(ctx)}): {list(ctx.keys())}")
        _info(f"  price  = {ctx.get('price')}")
        _info(f"  trend  = {ctx.get('trend')}")
        _info(f"  rsi    = {ctx.get('rsi')}")
        _info(f"  atr    = {ctx.get('atr')}")
        _info(f"  macd   = {ctx.get('macd')}")
        _info(f"  sma_20 = {ctx.get('sma_20')}")
        _info(f"  sma_50 = {ctx.get('sma_50')}")

    except Exception as e:
        _fail(f"get_ai_context() failed: {e}")
        return 1

    # ── Summary ──
    print("\n" + "=" * 60)
    if all_ok:
        print(f"  ✅ STEP 3 PASSED — Indicators ঠিকভাবে calculate হচ্ছে ({symbol})")
    else:
        print(f"  ❌ STEP 3 FAILED — কিছু indicator সমস্যা আছে ({symbol})")
    print("=" * 60)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
