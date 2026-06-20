# ai/ai_analyst.py  —  Day 10 | LLM Analyst Brain
# Primary: Groq (fast)  |  Fallback: Gemini Flash
#
# Day 37: GROQ_MODEL / GEMINI_MODEL are now read from .env (with the
# original hardcoded values as defaults), so you can swap reasoning models
# without touching code — e.g. drop in a bigger Groq model or a different
# Gemini tier for trade reasoning.

import os
import json
import re
from dotenv import load_dotenv
from utils.logger import get_logger

load_dotenv()
log = get_logger("ai_analyst")


class AIAnalyst:
    """
    LLM-powered market analyst।
    Rule engine এর পর second opinion দেয়।

    Flow:
        Technical data → Context builder → LLM → JSON report
    """

    GROQ_MODEL   = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    def __init__(self):
        self._groq_client   = None
        self._gemini_model  = None
        self._init_clients()

    def _init_clients(self):
        # Groq setup
        groq_key = os.getenv("GROQ_API_KEY")
        if groq_key:
            try:
                from groq import Groq
                self._groq_client = Groq(api_key=groq_key)
                log.info(f"Groq client initialized | model={self.GROQ_MODEL}")
            except Exception as e:
                log.warning(f"Groq init failed: {e}")

        # Gemini setup (fallback)
        gemini_key = os.getenv("GEMINI_API_KEY")
        if gemini_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=gemini_key)
                self._gemini_model = genai.GenerativeModel(self.GEMINI_MODEL)
                log.info(f"Gemini client initialized (fallback ready) | model={self.GEMINI_MODEL}")
            except Exception as e:
                log.warning(f"Gemini init failed: {e}")

    # ── Public method ──────────────────────────────────────────
    def analyze(
        self,
        ind_ctx:    dict,
        pat_ctx:    dict,
        sr_ctx:     dict,
        regime:     dict,
        signal:     dict,
        mtf_bias:   str = "NEUTRAL",
        symbol:     str = "EURUSD",
    ) -> dict:
        """
        সব technical context নিয়ে LLM analyst এর opinion নেয়।
        Returns structured dict।
        """
        context = self._build_context(
            ind_ctx, pat_ctx, sr_ctx, regime, signal, mtf_bias, symbol
        )
        prompt  = self._build_prompt(context)

        # Primary: Groq
        raw = None
        if self._groq_client:
            raw = self._call_groq(prompt)

        # Fallback: Gemini
        if raw is None and self._gemini_model:
            raw = self._call_gemini(prompt)

        if raw is None:
            return self._fallback_result("No LLM available")

        result = self._parse_response(raw)
        log.info(
            f"LLM → Signal: {result.get('signal')} | "
            f"Confidence: {result.get('confidence')}%"
        )
        return result

    # ── Context builder ────────────────────────────────────────
    def _build_context(
        self, ind, pat, sr, regime, signal, mtf_bias, symbol
    ) -> str:
        return f"""
SYMBOL        : {symbol}
TIMEFRAME     : 15M

── PRICE & TREND ──
Close         : {ind.get('close', 'N/A')}
Trend         : {ind.get('trend', 'N/A')}
EMA9          : {ind.get('ema9', 'N/A')}
SMA20         : {ind.get('sma20', 'N/A')}

── MOMENTUM ──
RSI (14)      : {ind.get('rsi', 'N/A')}
MACD Signal   : {ind.get('macd_signal', 'N/A')}
MACD Value    : {ind.get('macd', 'N/A')}

── VOLATILITY ──
ATR           : {ind.get('atr', 'N/A')}
BB Position   : {ind.get('bb_position', 'N/A')}

── PATTERNS ──
Recent        : {pat.get('recent_patterns', [])}
Signal        : {pat.get('pattern_signal', 'N/A')}

── SUPPORT / RESISTANCE ──
Location      : {sr.get('location', 'N/A')}
Nearest S     : {sr.get('nearest_support', 'N/A')}
Nearest R     : {sr.get('nearest_resistance', 'N/A')}
Pivot PP      : {sr.get('pivot_pp', 'N/A')}

── MARKET REGIME (Day 8) ──
Regime        : {regime.get('regime', 'N/A')}
Direction     : {regime.get('direction', 'N/A')}
Strength      : {regime.get('strength', 'N/A')}
Volatility    : {regime.get('volatility', 'N/A')}
ADX           : {regime.get('adx', 'N/A')}

── RULE ENGINE SIGNAL (Day 9) ──
Signal        : {signal.get('signal', 'N/A')}
Confidence    : {signal.get('confidence', 0)}%
Entry         : {signal.get('entry', 'N/A')}
Blocked by    : {signal.get('blocked_by', 'None')}
Reasons       : {signal.get('reasons', [])}

── MULTI-TIMEFRAME ──
MTF Bias      : {mtf_bias}
""".strip()

    # ── Prompt ────────────────────────────────────────────────
    def _build_prompt(self, context: str) -> str:
        return f"""You are a professional forex trader and market analyst with 15 years of experience.

Analyze the following market data carefully.

{context}

Rules:
1. Combine all signals — do not rely on one indicator alone
2. Respect market regime — in strong trends, counter-trend trades are risky
3. If signals conflict, recommend WAIT
4. Be conservative — protecting capital is priority
5. Explain your reasoning clearly

Return ONLY valid JSON, no extra text:

{{
  "analysis": "2-3 sentence market summary",
  "signal": "BUY or SELL or WAIT",
  "confidence": 0-100,
  "reasoning": "Why this signal, what confirms it, what are the risks",
  "key_risk": "The main risk in this setup",
  "invalidation": "What would invalidate this signal"
}}"""

    # ── LLM callers ───────────────────────────────────────────
    def _call_groq(self, prompt: str) -> str | None:
        try:
            resp = self._groq_client.chat.completions.create(
                model=self.GROQ_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=600,
            )
            return resp.choices[0].message.content
        except Exception as e:
            log.warning(f"Groq call failed: {e} — trying Gemini")
            return None

    def _call_gemini(self, prompt: str) -> str | None:
        try:
            resp = self._gemini_model.generate_content(prompt)
            return resp.text
        except Exception as e:
            log.error(f"Gemini call failed: {e}")
            return None

    # ── Response parser ────────────────────────────────────────
    def _parse_response(self, raw: str) -> dict:
        try:
            # JSON block বের করো (LLM কখনো markdown দেয়)
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                return json.loads(match.group())
        except (json.JSONDecodeError, AttributeError):
            pass

        log.warning("Could not parse LLM JSON — returning raw text")
        return {
            "analysis":    raw[:200] if raw else "Parse error",
            "signal":      "WAIT",
            "confidence":  0,
            "reasoning":   "JSON parse failed",
            "key_risk":    "Unknown",
            "invalidation": "Unknown",
        }

    def _fallback_result(self, reason: str) -> dict:
        return {
            "analysis":    reason,
            "signal":      "WAIT",
            "confidence":  0,
            "reasoning":   "LLM unavailable — use rule engine signal",
            "key_risk":    "N/A",
            "invalidation": "N/A",
        }

    # ── Print ──────────────────────────────────────────────────
    def print_summary(self, result: dict) -> None:
        icons = {"BUY": "🟢", "SELL": "🔴", "WAIT": "🟡"}
        icon  = icons.get(result.get("signal", "WAIT"), "🟡")
        bar   = "═" * 44

        log.info(bar)
        log.info(f"  {icon}  LLM ANALYST REPORT")
        log.info(bar)
        log.info(f"  Signal      : {result.get('signal')}")
        log.info(f"  Confidence  : {result.get('confidence')}%")
        log.info(f"  Analysis    : {result.get('analysis', '')[:80]}")
        log.info(f"  Reasoning   : {result.get('reasoning', '')[:100]}")
        log.info(f"  Key risk    : {result.get('key_risk', '')}")
        log.info(f"  Invalidation: {result.get('invalidation', '')}")
        log.info(bar)

    def get_ai_context(self, result: dict) -> dict:
        return {
            "llm_signal":      result.get("signal", "WAIT"),
            "llm_confidence":  result.get("confidence", 0),
            "llm_analysis":    result.get("analysis", ""),
            "llm_reasoning":   result.get("reasoning", ""),
            "llm_key_risk":    result.get("key_risk", ""),
        }