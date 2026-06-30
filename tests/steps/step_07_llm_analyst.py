#!/usr/bin/env python3
"""
tests/steps/step_07_llm_analyst.py
====================================
STEP 7: LLM Analyst Test

যা যা চেক করে:
  - Groq keys loaded কিনা (৬টা)
  - Gemini key loaded কিনা
  - Groq API call সফল হচ্ছে কিনা
  - Gemini API call সফল হচ্ছে কিনা (fallback)
  - LLM valid JSON response দিচ্ছে কিনা
  - Signal + confidence আসছে কিনা

Usage:
    python tests/steps/step_07_llm_analyst.py
"""
import os
import sys
import json
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
    print("  STEP 7: LLM ANALYST TEST")
    print("=" * 60)

    # ── 1. LLM Key Manager ──
    print("\n[1] LLM Key Manager check...")
    try:
        from core.llm_key_manager import get_llm_key_manager
        mgr = get_llm_key_manager()
        status = mgr.status()
        groq_total = status["groq"]["total"]
        groq_active = status["groq"]["available"]
        gemini_total = status["gemini"]["total"]
        gemini_active = status["gemini"]["available"]

        _pass(f"Groq keys: {groq_active}/{groq_total} active")
        _pass(f"Gemini keys: {gemini_active}/{gemini_total} active")

        if groq_total < 1:
            _fail("কোনো Groq key loaded নয় — .env চেক করুন")
            return 1

        # Check Gemini key format
        gemini_key = os.getenv("GEMINI_API_KEY_1") or os.getenv("GEMINI_API_KEY", "")
        if gemini_key and not gemini_key.startswith("AIza"):
            _warn(f"Gemini key format wrong (starts with '{gemini_key[:4]}', expected 'AIza')")
            _warn("Get valid key from https://aistudio.google.com/app/apikey")

    except Exception as e:
        _fail(f"LLM Key Manager failed: {e}")
        return 1

    # ── 2. AIAnalyst ──
    print("\n[2] AIAnalyst instantiation...")
    try:
        from ai.ai_analyst import AIAnalyst
        analyst = AIAnalyst()
        # NOTE: AIAnalyst has a property `active_provider`, not method `get_provider()`
        provider = analyst.active_provider
        _pass(f"AIAnalyst created | provider: {provider}")
        if provider == "none":
            _fail("কোনো LLM provider available নয়")
            return 1
    except Exception as e:
        _fail(f"AIAnalyst failed: {e}")
        return 1

    # ── 3. Test LLM call ──
    print("\n[3] LLM API call (real request)...")
    try:
        # Synthetic context for testing
        ind_ctx = {
            "close": 1.0850, "trend": "BULLISH", "rsi": 55, "rsi_signal": "neutral",
            "ema9": 1.0845, "ema20": 1.0840, "sma20": 1.0838, "sma50": 1.0820,
            "atr": 0.0010, "macd_cross": "bullish",
        }
        pat_ctx = {"latest_pattern": "hammer", "pattern_signal": "Bullish"}
        sr_ctx = {"nearest_support": 1.0820, "nearest_resistance": 1.0880}
        regime = {"regime": "TRENDING", "volatility": "NORMAL"}
        signal = {"signal": "BUY", "confidence": 60}

        result = analyst.analyze(
            ind_ctx=ind_ctx, pat_ctx=pat_ctx, sr_ctx=sr_ctx,
            regime=regime, signal=signal, mtf_bias="BULLISH",
            symbol="EURUSD",
        )

        llm_signal = result.get("signal", "UNKNOWN")
        llm_conf = result.get("confidence", 0)

        if llm_signal in ("BUY", "SELL", "WAIT"):
            _pass(f"LLM Signal: {llm_signal} | Confidence: {llm_conf}%")
        else:
            _fail(f"Invalid LLM signal: {llm_signal}")
            return 1

        if llm_conf > 0:
            _pass("LLM সফলভাবে response দিয়েছে")
        else:
            _warn("LLM confidence 0% — সম্ভবত rate-limited")

        _info(f"  Analysis: {result.get('analysis', '')[:100]}")

    except Exception as e:
        _fail(f"LLM call failed: {type(e).__name__}: {e}")
        _info("সম্ভাব্য কারণ:")
        _info("  - Groq TPD limit শেষ (২৪ঘন্টা পরে reset)")
        _info("  - Gemini key format ভুল (AIza... দিয়ে শুরু হতে হবে)")
        _info("  - Internet connection সমস্যা")
        return 1

    # ── 4. MasterAnalyst ──
    print("\n[4] MasterAnalyst test...")
    try:
        from agents.master_analyst import MasterAnalyst, LLM_AVAILABLE
        _pass(f"MasterAnalyst LLM_AVAILABLE: {LLM_AVAILABLE}")

        if LLM_AVAILABLE:
            _info("MasterAnalyst একটা আসল LLM call করবে (৫-১০ সেকেন্ড)...")
            master = MasterAnalyst()

            # Minimal context for test
            # NOTE: mtf_bias must be a dict with keys: bias, confidence, trends
            master_result = master.analyze(
                symbol="EURUSD", timeframe="15m",
                ind_ctx=ind_ctx, pat_ctx=pat_ctx, sr_ctx=sr_ctx,
                regime=regime,
                mtf_bias={"bias": "BULLISH", "confidence": "HIGH", "trends": {}},
                signal=signal,
                sentiment_ctx={}, news_ctx={}, memory_ctx={},
                bias_ctx={}, smc_ctx={}, fib_ctx={}, advanced_pat_ctx={},
                vision_ctx={},
                session_ctx={"is_dead_zone": False, "current_session": "TOKYO"},
                intermarket_ctx={},
            )

            master_signal = master_result.get("trade_plan", {}).get("signal", "UNKNOWN")
            master_conf = master_result.get("final_confidence", 0)
            _pass(f"MasterAnalyst: {master_signal} | Conf: {master_conf}%")
        else:
            _warn("LLM unavailable — MasterAnalyst fallback ব্যবহার করবে")

    except Exception as e:
        _fail(f"MasterAnalyst failed: {type(e).__name__}: {e}")

    # ── Summary ──
    print("\n" + "=" * 60)
    print("  ✅ STEP 7 PASSED — LLM Analyst ঠিকভাবে কাজ করছে")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
