"""
debug_llm_failure.py — Diagnose what happens when ALL LLM calls fail.

This script simulates the Groq 429 storm by:
  1. Disabling all LLM clients (set them to None)
  2. Running one symbol cycle through AnalysisAgent
  3. Printing every None that flows through the pipeline

If you see 'TypeError: NoneType object is not subscriptable' here,
you've found the exact crash point — without needing Groq to be up.

Run from project root:
    python debug_llm_failure.py
"""
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

# ── Step 1: Force-disable all LLM clients ─────────────────────
print("=" * 70)
print("  LLM FAILURE DIAGNOSTIC — simulating Groq 429 storm")
print("=" * 70)
print()
print("Step 1: Force-disabling all LLM clients...")

# Patch ai_analyst module
import ai.ai_analyst as _ai_mod
_ai_mod._groq_client = None
_ai_mod._gemini_client = None
print("  [OK] ai_analyst: Groq + Gemini clients = None")

# Patch master_analyst module
import agents.master_analyst as _ma_mod
_ma_mod._groq_client = None
_ma_mod._gemini_client = None
_ma_mod.LLM_AVAILABLE = False
print("  [OK] master_analyst: Groq + Gemini clients = None, LLM_AVAILABLE=False")

# Patch sentiment_model module
import intelligence.sentiment_model as _sm_mod
_sm_mod._groq_client = None
_sm_mod._gemini_client = None
_sm_mod.LLM_AVAILABLE = False
print("  [OK] sentiment_model: Groq + Gemini clients = None, LLM_AVAILABLE=False")

print()
print("Step 2: Building a fake market_output for EURUSD 15m...")

# Build minimal market_output
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Create a fake OHLCV DataFrame with 100 candles
np.random.seed(42)
dates = pd.date_range(end=datetime.now(), periods=100, freq="15min")
close = 1.1000 + np.random.randn(100).cumsum() * 0.0005
df = pd.DataFrame({
    "time": dates,
    "open":  close - np.random.rand(100) * 0.0003,
    "high":  close + np.random.rand(100) * 0.0005,
    "low":   close - np.random.rand(100) * 0.0005,
    "close": close,
    "volume": np.random.randint(100, 1000, 100),
})

# Minimal ind_ctx
ind_ctx = {
    "close": float(close[-1]),
    "trend": "neutral",
    "ema9": float(close[-9:].mean()),
    "sma20": float(close[-20:].mean()),
    "rsi": 50.0,
    "macd": 0.0,
    "macd_signal": 0.0,
    "atr": 0.0008,
    "bb_position": "middle",
    "price": float(close[-1]),
    "pip_value": 10.0,
}

market_output = {
    "df": df,
    "ind_ctx": ind_ctx,
    "regime": {"regime": "NORMAL", "volatility": "NORMAL"},
    "mtf_bias": "NEUTRAL",
    "symbol": "EURUSD",
    "timeframe": "15m",
}

print("  [OK] market_output built")
print(f"        symbol={market_output['symbol']} timeframe={market_output['timeframe']}")
print(f"        close={ind_ctx['close']:.5f} trend={ind_ctx['trend']}")
print()

# ── Step 3: Run AnalysisAgent.run() with full traceback ──────
print("Step 3: Running AnalysisAgent.run() with LLM disabled...")
print("  (If this crashes, the traceback below shows the EXACT NoneType")
print("   subscript point — that's the bug to fix.)")
print()

import traceback
from agents.analysis_agent import AnalysisAgent

agent = AnalysisAgent()
try:
    result = agent.run(market_output, memory_ctx={"total_trades": 0})
    print("  [OK] AnalysisAgent.run() completed without crash")
    print()
    print("  Result keys:")
    for k in sorted(result.keys()):
        v = result[k]
        vtype = type(v).__name__
        if isinstance(v, dict):
            print(f"    {k:25s} : dict ({len(v)} keys)")
        elif isinstance(v, str):
            print(f"    {k:25s} : str = {v!r}")
        else:
            print(f"    {k:25s} : {vtype}")
    print()
    print(f"  final_signal = {result.get('final_signal')!r}")
    print(f"  signal       = {result.get('signal', {}).get('signal')!r}")
except Exception as e:
    print(f"  [CRASH] {type(e).__name__}: {e}")
    print()
    print("  FULL TRACEBACK:")
    traceback.print_exc()
    print()
    print("=" * 70)
    print("  ⚠️  CRASH FOUND — see traceback above")
    print("  This is the exact 'NoneType subscript' crash that happens")
    print("  on every symbol cycle when Groq is rate-limited.")
    print("=" * 70)
    sys.exit(1)

print()
print("=" * 70)
print("  ✅  AnalysisAgent handles LLM failure gracefully.")
print("  If production still crashes, the issue is elsewhere —")
print("  paste this output + the production crash traceback.")
print("=" * 70)
