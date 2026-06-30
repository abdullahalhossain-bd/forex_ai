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
import time
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
        self._gemini_client = None  # google.genai Client object
        self._init_clients()

    # ── Public read-only accessors ──────────────────────────────────
    # Added so external callers (main.py status check, health monitor) can
    # introspect which LLM is wired without poking at underscore-prefixed
    # attributes (which previously caused AttributeError in main.py:279).
    @property
    def groq_client(self):
        return self._groq_client

    @property
    def gemini_client(self):
        return self._gemini_client

    @property
    def groq_model(self) -> str:
        return self.GROQ_MODEL

    @property
    def gemini_model(self) -> str:
        return self.GEMINI_MODEL

    @property
    def active_provider(self) -> str:
        """Return 'groq', 'gemini', or 'none' depending on which client is wired."""
        if self._groq_client is not None:
            return "groq"
        if self._gemini_client is not None:
            return "gemini"
        return "none"

    def _init_clients(self):
        """Initialize LLM clients using LLMKeyManager (multi-key rotation)."""
        try:
            from core.llm_key_manager import get_llm_key_manager
            manager = get_llm_key_manager()
            self._key_manager = manager
            self._groq_client = manager.get_groq_client()
            if self._groq_client is not None:
                log.info(f"Groq client initialized | model={self.GROQ_MODEL}")
            self._gemini_client = manager.get_gemini_client()
            if self._gemini_client is not None:
                log.info(f"Gemini client initialized (fallback ready) | model={self.GEMINI_MODEL}")
            if self._groq_client is None and self._gemini_client is None:
                log.warning("No LLM client available (Groq + Gemini both failed)")
        except Exception as e:
            log.warning(f"LLMKeyManager init failed, falling back to single-key: {e}")
            self._key_manager = None
            # Fallback: single-key mode (backwards compat)
            groq_key = os.getenv("GROQ_API_KEY_1") or os.getenv("GROQ_API_KEY", "")
            if groq_key:
                try:
                    from groq import Groq
                    self._groq_client = Groq(api_key=groq_key)
                    log.info(f"Groq client initialized (single-key fallback) | model={self.GROQ_MODEL}")
                except Exception as e2:
                    log.warning(f"Groq init failed: {e2}")
            gemini_key = os.getenv("GEMINI_API_KEY_1") or os.getenv("GEMINI_API_KEY", "")
            if gemini_key:
                try:
                    from google import genai as google_genai
                    self._gemini_client = google_genai.Client(api_key=gemini_key)
                    log.info(f"Gemini client initialized (single-key fallback) | model={self.GEMINI_MODEL}")
                except Exception as e2:
                    log.warning(f"Gemini init failed: {e2}")

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
        advanced_pat_ctx: dict = None,
        **kwargs,
    ) -> dict:
        """
        সব technical context নিয়ে LLM analyst এর opinion নেয়।
        Returns structured dict।
        """
        context = self._build_context(
            ind_ctx, pat_ctx, sr_ctx, regime, signal, mtf_bias, symbol, advanced_pat_ctx
        )
        prompt  = self._build_prompt(context)

        # ── Day 90 — LLM cache lookup ──────────────────────────
        # Same prompt within 5 min → return cached response.
        # This is the BIGGEST token saver because AIAnalyst gets
        # called once per symbol per cycle, and 6 symbols × 60s loop
        # = lots of redundant calls when market is quiet.
        try:
            from core.llm_cache import get_llm_cache
            _cache = get_llm_cache()
            _cache_key = _cache.make_key("groq", self.GROQ_MODEL, prompt)
            _cached = _cache.get(_cache_key)
            if _cached is not None:
                log.debug(f"[AIAnalyst] LLM cache HIT — skipping API call")
                result = self._parse_response(_cached)
                result["_cache_hit"] = True
                return result
        except Exception:
            pass

        # Primary: Groq
        raw = None
        if self._groq_client:
            raw = self._call_groq(prompt)

        # ── Day 91 — Cerebras / SambaNova / OpenRouter fallback ──
        # All three are OpenAI-compatible; reuse _call_openai_compat
        # helper that takes a client + model + manager hooks.
        if raw is None and self._key_manager is not None:
            # Try Cerebras (currently blocked by Cloudflare on Linux VPS,
            # but harmless to attempt — adds <100ms when key unavailable)
            if self._key_manager.has_any_cerebras:
                raw = self._call_openai_compat(
                    provider_name="Cerebras",
                    client_getter=self._key_manager.get_cerebras_client,
                    success_marker=self._key_manager.mark_cerebras_success,
                    failure_marker=self._key_manager.mark_cerebras_failure,
                    model_env="CEREBRAS_MODEL",
                    default_model="llama3.1-8b-instruct",
                    prompt=prompt,
                )
        if raw is None and self._key_manager is not None:
            if self._key_manager.has_any_sambanova:
                raw = self._call_openai_compat(
                    provider_name="SambaNova",
                    client_getter=self._key_manager.get_sambanova_client,
                    success_marker=self._key_manager.mark_sambanova_success,
                    failure_marker=self._key_manager.mark_sambanova_failure,
                    model_env="SAMBANOVA_MODEL",
                    default_model="Meta-Llama-3.1-8B-Instruct",
                    prompt=prompt,
                )
        if raw is None and self._key_manager is not None:
            if self._key_manager.has_any_openrouter:
                # OpenRouter has multiple free models — try fallback chain
                or_models = [os.getenv("OPENROUTER_MODEL", "google/gemma-4-26b-a4b-it:free")]
                fb1 = os.getenv("OPENROUTER_MODEL_FALLBACK_1", "")
                fb2 = os.getenv("OPENROUTER_MODEL_FALLBACK_2", "")
                if fb1: or_models.append(fb1)
                if fb2: or_models.append(fb2)
                for or_model in or_models:
                    raw = self._call_openai_compat(
                        provider_name=f"OpenRouter({or_model})",
                        client_getter=self._key_manager.get_openrouter_client,
                        success_marker=self._key_manager.mark_openrouter_success,
                        failure_marker=self._key_manager.mark_openrouter_failure,
                        model_env=None,  # use explicit model below
                        default_model=or_model,
                        prompt=prompt,
                    )
                    if raw is not None:
                        break

        # Fallback: Gemini
        if raw is None and self._gemini_client:
            raw = self._call_gemini(prompt)

        if raw is None:
            return self._fallback_result("No LLM available")

        # ── Day 90 — cache store ───────────────────────────────
        try:
            _cache.set(_cache_key, raw, token_estimate=400)
        except Exception:
            pass

        result = self._parse_response(raw)
        log.info(
            f"LLM -> Signal: {result.get('signal')} | "
            f"Confidence: {result.get('confidence')}%"
        )
        return result

    # ── Context builder ────────────────────────────────────────
    def _build_context(
        self, ind, pat, sr, regime, signal, mtf_bias, symbol, advanced_pat=None
    ) -> str:
        adv_patterns_str = "None"
        if advanced_pat and isinstance(advanced_pat, dict):
            adv_patterns_str = str(advanced_pat.get('recent_patterns', advanced_pat))

        return f"""
SYMBOL        : {symbol}
TIMEFRAME     : 15M

-- PRICE & TREND --
Close         : {ind.get('close', 'N/A')}
Trend         : {ind.get('trend', 'N/A')}
EMA9          : {ind.get('ema9', 'N/A')}
SMA20         : {ind.get('sma20', 'N/A')}

-- MOMENTUM --
RSI (14)      : {ind.get('rsi', 'N/A')}
MACD Signal   : {ind.get('macd_signal', 'N/A')}
MACD Value    : {ind.get('macd', 'N/A')}

-- VOLATILITY --
ATR           : {ind.get('atr', 'N/A')}
BB Position   : {ind.get('bb_position', 'N/A')}

-- PATTERNS --
Recent        : {pat.get('recent_patterns', [])}
Advanced Pat  : {adv_patterns_str}
Signal        : {pat.get('pattern_signal', 'N/A')}

-- SUPPORT / RESISTANCE --
Location      : {sr.get('location', 'N/A')}
Nearest S     : {sr.get('nearest_support', 'N/A')}
Nearest R     : {sr.get('nearest_resistance', 'N/A')}
Pivot PP      : {sr.get('pivot_pp', 'N/A')}

-- MARKET REGIME --
Regime        : {regime.get('regime', 'N/A')}
Direction     : {regime.get('direction', 'N/A')}
Strength      : {regime.get('strength', 'N/A')}
Volatility    : {regime.get('volatility', 'N/A')}
ADX           : {regime.get('adx', 'N/A')}

-- RULE ENGINE SIGNAL --
Signal        : {signal.get('signal', 'N/A')}
Confidence    : {signal.get('confidence', 0)}%
Entry         : {signal.get('entry', 'N/A')}
Blocked by    : {signal.get('blocked_by', 'None')}
Reasons       : {signal.get('reasons', [])}

-- MULTI-TIMEFRAME --
MTF Bias      : {mtf_bias}
""".strip()

    # ── Prompt ────────────────────────────────────────────────
    def _build_prompt(self, context: str) -> str:
        return f"""You are an elite professional forex trader and market analyst with 20 years of experience.
You specialize in Smart Money Concepts (SMC), institutional order flow, and price action analysis.

Analyze the following market data carefully and provide a structured trade decision.

{context}

ANALYSIS RULES:
1. Combine ALL signals — do not rely on one indicator alone
2. Respect market regime — in strong trends, counter-trend trades are extremely risky
3. If signals conflict, recommend WAIT — capital preservation is paramount
4. Consider confluence — multiple confirming factors increase conviction
5. Always explain WHY — your reasoning must be transparent and verifiable
6. Consider the session context — London/NY overlap has different dynamics than Asian session
7. Evaluate risk/reward — only recommend trades with R:R >= 2:1

OUTPUT FORMAT — Return ONLY valid JSON, no extra text:

{{
  "analysis": "2-3 sentence market summary explaining the current state",
  "signal": "BUY or SELL or WAIT",
  "confidence": 0-100,
  "reasoning": "Detailed explanation: WHY this direction, what confirms it, what are the confluences",
  "key_risk": "The single most important risk that could invalidate this trade",
  "invalidation": "Specific price level or condition that would invalidate this signal",
  "market_condition": "TRENDING_UP or TRENDING_DOWN or RANGING or VOLATILE",
  "risk_warning": "Any additional risk warning for the trader"
}}"""

    # ── LLM callers (multi-key retry) ───────────────────────────
    def _call_groq(self, prompt: str) -> str | None:
        """Call Groq with multi-key retry. If current key fails, tries next.

        If ALL keys are exhausted (e.g. Groq free-tier TPD hit), waits
        for the soonest-recovering key instead of bailing immediately —
        this prevents the 429 storm + supervisor restart loop seen in
        production logs.

        Day 81+ hotfix: per-cycle throttle caps total LLM calls per
        symbol cycle to MAX_LLM_CALLS_PER_CYCLE (default 5).  Also
        enforces LLM_CALL_INTERVAL_SEC between calls (default 1.0s)
        to prevent the Groq free-tier rate-limit storm.
        """
        # Per-cycle throttle check
        if hasattr(self, '_key_manager') and self._key_manager:
            allowed, reason = self._key_manager.check_cycle_throttle()
            if not allowed:
                log.info(f"[AIAnalyst] Groq skipped — {reason}")
                return None

        max_retries = 3
        for attempt in range(max_retries):
            client = self._groq_client
            if client is None and hasattr(self, '_key_manager') and self._key_manager:
                client = self._key_manager.get_groq_client()
            if client is None and hasattr(self, '_key_manager') and self._key_manager:
                # All keys exhausted — wait for one to recover (max 5 min)
                if self._key_manager.wait_for_any_groq(max_wait=300):
                    client = self._key_manager.get_groq_client()
            if client is None:
                log.warning("No Groq client available after wait — falling back")
                return None
            try:
                resp = client.chat.completions.create(
                    model=self.GROQ_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2,
                    # Day 90 — token economy: 600→400 (saves ~33% per call).
                    # The classic AIAnalyst's response is much shorter than
                    # MasterAnalyst's (just signal + reasoning, no full plan).
                    max_tokens=int(os.getenv("AI_ANALYST_MAX_TOKENS", "400")),
                )
                # Success — mark key as healthy
                if hasattr(self, '_key_manager') and self._key_manager:
                    self._key_manager.mark_groq_success()
                return resp.choices[0].message.content
            except Exception as e:
                from core.llm_key_manager import log_llm_call_failure
                info = log_llm_call_failure(
                    log, "Groq", self.GROQ_MODEL, attempt, max_retries, e
                )
                if hasattr(self, '_key_manager') and self._key_manager:
                    self._key_manager.mark_groq_failure(
                        info["error_str"], info["rate_limited"]
                    )
                    # Get a fresh client with a different key
                    self._groq_client = self._key_manager.get_groq_client()
                if attempt < max_retries - 1:
                    time.sleep(1)
        return None

    # ── Day 91 — OpenAI-compatible fallback (Cerebras / SambaNova / OpenRouter)
    def _call_openai_compat(
        self,
        *,
        provider_name: str,
        client_getter,
        success_marker,
        failure_marker,
        model_env: str | None,
        default_model: str,
        prompt: str,
    ) -> str | None:
        """Generic OpenAI-compatible chat completion call.

        All three new providers (Cerebras, SambaNova, OpenRouter) expose
        the same /v1/chat/completions endpoint with .chat.completions.
        create() surface. This helper avoids duplicating the call+retry
        boilerplate across three near-identical blocks.

        Returns:
            str response text on success, None on failure (caller should
            try the next fallback).
        """
        max_tokens = int(os.getenv("AI_ANALYST_MAX_TOKENS", "400"))
        try:
            client = client_getter()
            if client is None:
                return None
            model = default_model
            if model_env:
                model = os.getenv(model_env, default_model)
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=max_tokens,
            )
            success_marker()
            text = resp.choices[0].message.content
            log.info(f"[AIAnalyst] {provider_name} OK | model={model}")
            return text.strip() if text else None
        except Exception as e:
            from core.llm_key_manager import log_llm_call_failure
            info = log_llm_call_failure(
                log, provider_name, default_model, 0, 1, e
            )
            failure_marker(info["error_str"], info["rate_limited"])
            return None

    def _call_gemini(self, prompt: str) -> str | None:
        """Call Gemini with multi-key retry."""
        max_retries = 3
        for attempt in range(max_retries):
            client = self._gemini_client
            if client is None and hasattr(self, '_key_manager') and self._key_manager:
                client = self._key_manager.get_gemini_client()
            if client is None:
                log.warning("No Gemini client available")
                return None
            try:
                resp = client.models.generate_content(
                    model=self.GEMINI_MODEL,
                    contents=prompt,
                )
                if hasattr(self, '_key_manager') and self._key_manager:
                    self._key_manager.mark_gemini_success()
                return resp.text
            except Exception as e:
                from core.llm_key_manager import log_llm_call_failure
                info = log_llm_call_failure(
                    log, "Gemini", self.GEMINI_MODEL, attempt, max_retries, e
                )
                if hasattr(self, '_key_manager') and self._key_manager:
                    self._key_manager.mark_gemini_failure(
                        info["error_str"], info["rate_limited"]
                    )
                    self._gemini_client = self._key_manager.get_gemini_client()
                if attempt < max_retries - 1:
                    time.sleep(1)
        return None

    # ── Response parser ────────────────────────────────────────
    def _parse_response(self, raw: str) -> dict:
        try:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                parsed = json.loads(match.group())
                return {
                    "analysis":         parsed.get("analysis", "No analysis provided"),
                    "signal":           parsed.get("signal", "WAIT"),
                    "confidence":       min(99, max(0, int(parsed.get("confidence", 0)))),
                    "reasoning":        parsed.get("reasoning", ""),
                    "key_risk":         parsed.get("key_risk", "Unknown"),
                    "invalidation":     parsed.get("invalidation", "Unknown"),
                    "market_condition": parsed.get("market_condition", "UNKNOWN"),
                    "risk_warning":     parsed.get("risk_warning", ""),
                }
        except (json.JSONDecodeError, AttributeError):
            pass

        log.warning("Could not parse LLM JSON — returning raw text")
        return {
            "analysis":         raw[:200] if raw else "Parse error",
            "signal":           "WAIT",
            "confidence":       0,
            "reasoning":        "JSON parse failed",
            "key_risk":         "Unknown",
            "invalidation":     "Unknown",
            "market_condition": "UNKNOWN",
            "risk_warning":     "LLM response could not be parsed",
        }

    def _fallback_result(self, reason: str) -> dict:
        return {
            "analysis":         reason,
            "signal":           "WAIT",
            "confidence":       0,
            "reasoning":        "LLM unavailable — use rule engine signal",
            "key_risk":         "N/A",
            "invalidation":     "N/A",
            "market_condition": "UNKNOWN",
            "risk_warning":     "AI analysis unavailable",
        }

    # ── Print ──────────────────────────────────────────────────
    def print_summary(self, result: dict) -> None:
        icons = {"BUY": "[BUY]", "SELL": "[SELL]", "WAIT": "[WAIT]"}
        icon  = icons.get(result.get("signal", "WAIT"), "[WAIT]")
        bar   = "=" * 44

        log.info(bar)
        log.info(f"   {icon}  LLM ANALYST REPORT")
        log.info(bar)
        log.info(f"   Signal      : {result.get('signal')}")
        log.info(f"   Confidence  : {result.get('confidence')}%")
        log.info(f"   Analysis    : {result.get('analysis', '')[:80]}")
        log.info(f"   Reasoning   : {result.get('reasoning', '')[:100]}")
        log.info(f"   Key risk    : {result.get('key_risk', '')}")
        log.info(f"   Invalidation: {result.get('invalidation', '')}")
        log.info(bar)

    def get_ai_context(self, result: dict) -> dict:
        return {
            "llm_signal":           result.get("signal", "WAIT"),
            "llm_confidence":       result.get("confidence", 0),
            "llm_analysis":         result.get("analysis", ""),
            "llm_reasoning":        result.get("reasoning", ""),
            "llm_key_risk":         result.get("key_risk", ""),
            "llm_market_condition": result.get("market_condition", "UNKNOWN"),
            "llm_risk_warning":     result.get("risk_warning", ""),
        }