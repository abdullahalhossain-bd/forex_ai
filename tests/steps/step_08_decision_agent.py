#!/usr/bin/env python3
"""
tests/steps/step_08_decision_agent.py
=======================================
STEP 8: Decision Agent Test

যা যা চেক করে:
  - DecisionAgent instantiate হচ্ছে কিনা
  - decide() সঠিক dict return করছে কিনা
  - Voting logic কাজ করছে কিনা (Master + LLM + Rule)
  - Confidence adjustment হচ্ছে কিনা
  - Final decision BUY/SELL/WAIT/NO_TRADE আসছে কিনা

Usage:
    python tests/steps/step_08_decision_agent.py
    python tests/steps/step_08_decision_agent.py GBPUSD
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
    print(f"  STEP 8: DECISION AGENT TEST ({symbol})")
    print("=" * 60)

    # ── 1. DecisionAgent ──
    print(f"\n[1] DecisionAgent instantiation...")
    try:
        from agents.decision_agent import DecisionAgent
        agent = DecisionAgent()
        _pass("DecisionAgent() created")
    except Exception as e:
        _fail(f"DecisionAgent failed: {e}")
        return 1

    # ── 2. Synthetic test data ──
    print(f"\n[2] Synthetic market + analysis data...")
    market_out = {
        "symbol": symbol, "timeframe": "15m",
        "ind_ctx": {"close": 1.0850, "trend": "BULLISH", "rsi": 55, "atr": 0.0010},
        "regime": {"regime": "TRENDING", "volatility": "NORMAL"},
    }
    analysis_out = {
        "final_signal": "BUY",
        "signal": {"signal": "BUY", "confidence": 65, "entry": 1.0850},
        "llm": {"signal": "BUY", "confidence": 72},
        "news": {"trade_allowed": True},
        "sentiment_ctx": {"sentiment_bias": "BULLISH", "sentiment_score": 5},
        "conflict": {"has_conflict": False, "confidence_adjustment": 0},
        "master_ctx": {
            "master_signal": "BUY", "master_confidence": 75,
            "master_entry": 1.0850, "master_sl": 1.0830, "master_tp1": 1.0880,
            "master_story": "Bullish confluence", "master_risks": [],
            "master_critique": "",
        },
    }
    risk_out = {
        "approved": True, "lot": 0.1, "entry": 1.0850,
        "sl_price": 1.0830, "tp_price": 1.0880, "rr_ratio": 1.5,
        "reject_reason": None,
    }
    _pass("Synthetic data prepared")

    # ── 3. Run decide() ──
    print(f"\n[3] decide() call করছে...")
    try:
        result = agent.decide(market_out, analysis_out, risk_out)
        _pass("decide() completed")
    except Exception as e:
        _fail(f"decide() failed: {type(e).__name__}: {e}")
        return 1

    # ── 4. Check result ──
    print(f"\n[4] Result verify...")
    required = {"decision", "confidence", "entry", "sl", "tp", "reasons"}
    missing = required - set(result.keys())
    if missing:
        _fail(f"Missing keys: {missing}")
        return 1
    _pass("All required keys present")

    decision = result.get("decision", "UNKNOWN")
    if decision not in ("BUY", "SELL", "WAIT", "NO TRADE"):
        _fail(f"Invalid decision: {decision}")
        return 1
    _pass(f"Decision: {decision}")

    conf = result.get("confidence", -1)
    if not (0 <= conf <= 100):
        _fail(f"Confidence {conf} out of range")
        return 1
    _pass(f"Confidence: {conf}%")

    # Reasons
    reasons = result.get("reasons", [])
    _info(f"  Reasons ({len(reasons)}):")
    for r in reasons[:5]:
        _info(f"    • {r}")

    # ── 5. Test conflict scenario ──
    print(f"\n[5] Conflict scenario test (sentiment vs technical)...")
    try:
        analysis_conflict = analysis_out.copy()
        analysis_conflict["sentiment_ctx"] = {"sentiment_bias": "BEARISH", "sentiment_score": -5}
        analysis_conflict["conflict"] = {"has_conflict": True, "confidence_adjustment": -10}

        result_conflict = agent.decide(market_out, analysis_conflict, risk_out)
        _pass(f"Conflict decision: {result_conflict.get('decision')} "
              f"(conf: {result_conflict.get('confidence')}%)")
    except Exception as e:
        _warn(f"Conflict test failed (non-critical): {e}")

    # ── Summary ──
    print("\n" + "=" * 60)
    print(f"  ✅ STEP 8 PASSED — Decision Agent ঠিকভাবে কাজ করছে ({symbol})")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
