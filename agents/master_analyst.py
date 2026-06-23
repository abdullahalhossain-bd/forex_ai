# agents/master_analyst.py  —  Day 42 + Day 44 + Day 47 + Day 63 + Day 65
# ============================================================
# Day 63: Session Intelligence context যোগ হয়েছে।
# Day 65: Intermarket / Global Macro Intelligence context যোগ হয়েছে।
#
# নতুন context block (Day 65): "global_market_intelligence"
#   - DXY/Gold/Oil/US10Y/SP500/VIX trends
#   - Risk-On / Risk-Off regime + trading mode
#   - USD bias + per-currency macro bias + pair bias
#   - Macro Score (0-100), cross-asset confirmation, event risk penalty
#
# LLM system prompt-এ macro awareness rules যোগ হয়েছে।
# Final confidence-এ macro score weight + event-risk penalty যোগ হয়েছে।
# ============================================================

import json
import os
import re
from datetime import datetime

from dotenv import load_dotenv
from utils.logger import get_logger

load_dotenv()
log = get_logger("master_analyst")

# ── LLM client initialization (Day 37+ runtime unification) ──────────
# Per user request, Anthropic + OpenRouter are no longer used.
# MasterAnalyst now uses Groq (primary) + Gemini (fallback) — the same
# providers that AIAnalyst uses — so the system runs on free-tier keys only.
# Day 72+: Multi-key rotation via LLMKeyManager (unlimited keys per provider).
LLM_AVAILABLE = False
_provider = "none"
_groq_client = None
_gemini_client = None
_key_manager = None
MODEL = ""
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
MAX_TOK = 1500

try:
    from core.llm_key_manager import get_llm_key_manager
    _key_manager = get_llm_key_manager()
    # Day 76: Swap priority — Gemini first (higher free limits), Groq as fallback
    # Groq free tier = 100K tokens/day, Gemini = much higher, fewer rate limits
    _gemini_client = _key_manager.get_gemini_client()
    if _gemini_client is not None:
        MODEL = GEMINI_MODEL
        LLM_AVAILABLE = True
        _provider = "gemini"
        log.info(f"[MasterAnalyst] Gemini client initialized (primary) | model={MODEL}")
    if not LLM_AVAILABLE:
        _groq_client = _key_manager.get_groq_client()
        if _groq_client is not None:
            MODEL = GROQ_MODEL
            LLM_AVAILABLE = True
            _provider = "groq"
            log.info(f"[MasterAnalyst] Groq client initialized (fallback) | model={MODEL}")
except Exception as e:
    log.warning(f"[MasterAnalyst] LLMKeyManager init failed: {e} — trying single-key")
    # Day 76: Try Gemini first (single-key fallback)
    gemini_key = os.getenv("GEMINI_API_KEY_1") or os.getenv("GEMINI_API_KEY", "")
    if gemini_key:
        try:
            from google import genai as google_genai
            _gemini_client = google_genai.Client(api_key=gemini_key)
            MODEL = GEMINI_MODEL
            LLM_AVAILABLE = True
            _provider = "gemini"
            log.info(f"[MasterAnalyst] Gemini client initialized (single-key primary) | model={MODEL}")
        except Exception as e2:
            log.warning(f"[MasterAnalyst] Gemini init failed: {e2}")
    # Fallback to Groq if Gemini not available
    if not LLM_AVAILABLE:
        groq_key = os.getenv("GROQ_API_KEY_1") or os.getenv("GROQ_API_KEY", "")
        if groq_key:
            try:
                from groq import Groq
                _groq_client = Groq(api_key=groq_key)
                MODEL = GROQ_MODEL
                LLM_AVAILABLE = True
                _provider = "groq"
                log.info(f"[MasterAnalyst] Groq client initialized (single-key fallback) | model={MODEL}")
            except Exception as e2:
                log.warning(f"[MasterAnalyst] Groq init failed: {e2}")
            try:
                from google import genai as google_genai
                _gemini_client = google_genai.Client(api_key=gemini_key)
                MODEL = GEMINI_MODEL
                LLM_AVAILABLE = True
                _provider = "gemini"
                log.info(f"[MasterAnalyst] Gemini client initialized (single-key fallback) | model={MODEL}")
            except Exception as e2:
                log.warning(f"[MasterAnalyst] Gemini init failed: {e2}")

if not LLM_AVAILABLE:
    log.warning(
        "[MasterAnalyst] No LLM available (Groq/Gemini keys missing). "
        "MasterAnalyst will fall back to rule-engine signal."
    )


class MasterAnalyst:
    """
    Day 42 + Day 44 + Day 47 + Day 63 + Day 65 — Professional Forex Trader Brain।

    Now session-aware AND macro-aware: different strategy suggestions
    based on current market session, AND global intermarket context
    (DXY/Gold/Oil/Yields/SP500/VIX) instead of treating forex as an
    isolated market.
    """

    _SYSTEM = """You are an elite professional forex trader with 20+ years of institutional experience.
You have deep expertise in Smart Money Concepts (SMC), price action, intermarket analysis,
and behavioral market microstructure. You think like a hedge fund portfolio manager —
you protect capital first, you wait patiently for A+ setups, and you NEVER force a trade.

# YOUR MINDSET
- Capital preservation is rule #1. A bad day with no trades is better than a bad day with trades.
- Patience beats aggression. If the setup is not crystal clear, WAIT.
- You trade CONFLUENCE, not single signals. 3+ aligned reasons to enter > 1 strong signal.
- You respect market sessions, macroeconomic context, and intermarket correlations.
- You think in probabilities, not certainties. Every trade has risk — name it.

# ANALYSIS FRAMEWORK (use this mental checklist)
Before deciding BUY/SELL/WAIT, walk through these layers IN ORDER:

1. **Session & Time-of-Day**: Where are we in the 24h cycle? London/NY overlap = premium.
   Asian session = range. Dead zone = NO TRADE.
2. **Macro Regime**: Risk-on or risk-off? DXY/Gold/VIX alignment with the pair?
   If macro OPPOSES the technical signal strongly, lower confidence or WAIT.
3. **Higher Timeframe Bias**: Daily/4H trend direction. Don't fight the HTF trend
   unless there's a clear SMC reversal (CHoCH + BOS + displacement).
4. **Market Structure (SMC)**: BOS confirmed? CHoCH? Order block tap? FVG fill?
   Liquidity sweep + rejection? These are institutional footprints — follow them.
5. **Pattern & Fibonacci**: Confluence at key fib level (50%/61.8%/78.6%)?
   Pattern direction matches HTF bias?
6. **Support/Resistance**: Price at premium/discount zone? Near pivot?
   Equal highs/lows (liquidity pools) nearby?
7. **Momentum**: RSI divergence? MACD cross? Overbought/oversold extreme?
8. **Sentiment & News**: Retail positioning contrarian signal? High-impact news within 30min?
9. **History**: How did similar setups perform in the last 20 trades on this pair?
10. **Self-Critique**: What am I missing? What's the bear case for my bull trade (or vice versa)?

# SESSION RULES (critical — follow strictly)
1. DEAD_ZONE or session_trade_allowed=false → return WAIT immediately, no exceptions.
2. LONDON_NY_OVERLAP → only A+ setups (3+ confluences, full SMC alignment).
3. LONDON → LONDON_BREAKOUT strategy. Look for Asian range sweep + BOS confirmation.
4. NEW_YORK → TREND_CONTINUATION from London. Don't reverse without strong SMC.
5. TOKYO/SYDNEY → RANGE_TRADING only. Fade extremes, avoid breakout entries.
6. london_open_window=true → wait for liquidity sweep THEN enter on BOS, never before.
7. If pair_session_label is POOR or AVOID → lower confidence by 15% or WAIT.
8. in_session_transition=true → extra caution. Reduce position size or WAIT.

# GLOBAL MACRO RULES (Day 65)
9. Forex is NOT isolated. Check macro_pair_bias and macro_regime FIRST.
10. If macro_pair_bias OPPOSES technical signal AND cross_asset_confirmed=true → WAIT or low confidence.
11. If macro_pair_bias AGREES with technical signal → STRONG confluence ("Macro + SMC Fusion").
    This is the highest-quality setup — mention explicitly in market_story.
12. event_risk_elevated=true (FOMC/NFP/CPI within 60min) → reduce confidence by event_risk_penalty.
13. trading_mode=DEFENSIVE (VIX elevated) → only A+ setups. CAUTIOUS → reduce confidence 10%.

# CONFIDENCE CALIBRATION (be honest — fake confidence loses money)
- 85-100: A+ setup. 4+ confluences aligned. HTF + SMC + macro + session all agree.
- 70-84:  A setup. 3+ confluences. One minor concern noted in self_critique.
- 55-69:  B setup. 2 confluences. Smaller position size, tighter SL.
- 0-54:   Not tradeable. Return WAIT with explicit reason.

# TRADE PLAN REQUIREMENTS
- Entry: precise price level (not zone), with reasoning.
- SL: behind structure (swing low/high, order block, FVG edge) — never arbitrary pips.
- TP1: 1R minimum, at first liquidity pool / S/R / fib extension.
- TP2: 2R+ at next liquidity target. Partial close at TP1.
- Reasoning: 1-2 sentences naming the TOP 2-3 confluences (not all of them).

# OUTPUT — JSON ONLY, no markdown, no extra text:
{
  "market_story": "3-5 sentence narrative: session context + macro regime + key structural observation",
  "key_levels": [float, float, float],
  "trade_plan": {
    "signal": "BUY" | "SELL" | "WAIT",
    "entry": float | null,
    "sl": float | null,
    "tp1": float | null,
    "tp2": float | null,
    "confidence": integer (0-100),
    "reasoning": "Top 2-3 confluences that justify this trade (or why WAIT)"
  },
  "risks": ["specific risk 1", "specific risk 2"],
  "self_critique": "What could go wrong? What am I missing? Be honest.",
  "no_trade_reason": "Only if signal is WAIT — explicit reason"
}"""

    def analyze(
        self,
        symbol:       str,
        timeframe:    str,
        ind_ctx:      dict,
        pat_ctx:      dict,
        sr_ctx:       dict,
        regime:       dict,
        mtf_bias:     dict,
        signal:       dict,
        sentiment_ctx: dict = None,
        news_ctx:     dict = None,
        memory_ctx:   dict = None,
        bias_ctx:     dict = None,
        smc_ctx:      dict = None,
        fib_ctx:      dict = None,
        advanced_pat_ctx: dict = None,
        vision_ctx:   dict = None,
        session_ctx:  dict = None,   # ← Day 63
        intermarket_ctx: dict = None, # ← Day 65
    ) -> dict:

        context = self._build_context(
            symbol, timeframe, ind_ctx, pat_ctx, sr_ctx,
            regime, mtf_bias, signal,
            sentiment_ctx or {},
            news_ctx or {},
            memory_ctx or {},
            bias_ctx or {},
            smc_ctx or {},
            fib_ctx or {},
            advanced_pat_ctx or {},
            vision_ctx or {},
            session_ctx or {},        # ← Day 63
            intermarket_ctx or {},    # ← Day 65
        )

        if not LLM_AVAILABLE:
            return self._fallback_result(signal, "LLM not available")

        try:
            raw    = self._call_llm(context)
            parsed = self._parse_response(raw)
        except Exception as e:
            from core.llm_key_manager import log_llm_call_failure
            log_llm_call_failure(log, "MasterAnalyst", MODEL, 0, 1, e)
            return self._fallback_result(signal, str(e))

        final_conf = self._calculate_final_confidence(
            llm_conf       = parsed.get("trade_plan", {}).get("confidence", 50),
            technical_conf = signal.get("confidence", 50),
            sentiment_conf = (sentiment_ctx or {}).get("sentiment_conf", 50),
            memory_ctx     = memory_ctx or {},
            smc_ctx        = smc_ctx or {},
            session_ctx    = session_ctx or {},      # ← Day 63
            intermarket_ctx = intermarket_ctx or {},  # ← Day 65
        )

        result = {
            **parsed,
            "final_confidence": final_conf,
            "llm_raw":          raw,
            "error":            None,
        }

        log.info(
            f"[MasterAnalyst] {symbol} | "
            f"Session: {(session_ctx or {}).get('current_session', 'N/A')} | "
            f"Macro: {(intermarket_ctx or {}).get('macro_regime', 'N/A')} | "
            f"Signal: {parsed.get('trade_plan', {}).get('signal')} | "
            f"Final Conf: {final_conf}%"
        )
        return result

    def _build_context(
        self,
        symbol, timeframe,
        ind_ctx, pat_ctx, sr_ctx,
        regime, mtf_bias, signal,
        sentiment_ctx, news_ctx,
        memory_ctx, bias_ctx,
        smc_ctx, fib_ctx, advanced_pat_ctx,
        vision_ctx,
        session_ctx,        # ← Day 63
        intermarket_ctx,    # ← Day 65
    ) -> str:

        # ── Technical ─────────────────────────────────────────
        trend       = ind_ctx.get("trend", "unknown")
        rsi         = ind_ctx.get("rsi", 50)
        rsi_sig     = ind_ctx.get("rsi_signal", "neutral")
        macd_cross  = ind_ctx.get("macd_cross", "")
        close_price = ind_ctx.get("price", ind_ctx.get("close", 0))
        atr         = ind_ctx.get("atr", 0)
        bb_pct      = ind_ctx.get("bb_pct", 0.5)

        # ── Pattern ───────────────────────────────────────────
        latest_pat  = pat_ctx.get("latest_pattern", "none")
        pat_signal  = pat_ctx.get("pattern_signal", "")
        recent_pats = pat_ctx.get("recent_patterns", [])

        # ── S/R ───────────────────────────────────────────────
        nearest_sup = sr_ctx.get("nearest_support")
        nearest_res = sr_ctx.get("nearest_resistance")
        location    = sr_ctx.get("price_location", "mid_range")
        pivot       = sr_ctx.get("pivot")

        # ── Regime ────────────────────────────────────────────
        market_regime = regime.get("regime", "UNKNOWN")
        direction     = regime.get("direction", "NEUTRAL")
        strength      = regime.get("strength", "WEAK")
        volatility    = regime.get("volatility", "NORMAL")

        # ── MTF ───────────────────────────────────────────────
        mtf_overall = mtf_bias.get("bias", "NEUTRAL") if mtf_bias else "NEUTRAL"
        mtf_conf    = mtf_bias.get("confidence", "LOW") if mtf_bias else "LOW"
        mtf_trends  = mtf_bias.get("trends", {}) if mtf_bias else {}

        # ── Rule signal ───────────────────────────────────────
        rule_signal = signal.get("signal", "NO TRADE")
        rule_conf   = signal.get("confidence", 0)

        # ── Bias ──────────────────────────────────────────────
        bias_label   = bias_ctx.get("bias", "NEUTRAL")
        bias_conf    = bias_ctx.get("confidence_pct", 0)
        has_conflict = bias_ctx.get("has_conflict", False)

        # ── Sentiment ─────────────────────────────────────────
        sent_score   = sentiment_ctx.get("sentiment_score", 0)
        sent_bias    = sentiment_ctx.get("sentiment_bias", "NEUTRAL")
        sent_conf    = sentiment_ctx.get("sentiment_conf", 0)
        retail_long  = sentiment_ctx.get("retail_long_pct", 50)
        fg_label     = sentiment_ctx.get("fg_label", "NEUTRAL")
        dxy_trend_sent = sentiment_ctx.get("dxy_trend", "NEUTRAL")
        sent_reasons = sentiment_ctx.get("sentiment_reasons", [])

        # ── News ──────────────────────────────────────────────
        trade_allowed = news_ctx.get("trade_allowed", True) if news_ctx else True
        upcoming_news = news_ctx.get("upcoming_events", []) if news_ctx else []
        news_risk     = news_ctx.get("risk_level", "LOW") if news_ctx else "LOW"

        # ── Memory ────────────────────────────────────────────
        win_rate       = memory_ctx.get("overall_win_rate", 0)
        total_trades   = memory_ctx.get("total_trades", 0)
        recent_results = memory_ctx.get("recent_results", [])
        lessons        = memory_ctx.get("lessons", [])

        # ── SMC ───────────────────────────────────────────────
        smc_signal    = smc_ctx.get("smc_signal", "WAIT")
        smc_direction = smc_ctx.get("smc_direction", "NEUTRAL")
        smc_score     = smc_ctx.get("smc_score", 0)
        smc_grade     = smc_ctx.get("smc_grade", "INVALID")
        smc_factors   = smc_ctx.get("smc_factors", {})
        smc_analysis  = smc_ctx.get("smc_analysis", "")
        smc_ob_zone   = smc_ctx.get("smc_h4_ob_zone")
        smc_fvg_zone  = smc_ctx.get("smc_h4_fvg_zone")
        smc_h4_bos    = smc_ctx.get("smc_h4_bos", "NONE")
        smc_h4_choch  = smc_ctx.get("smc_h4_choch", "NONE")

        # ── Vision ────────────────────────────────────────────
        vision_trend  = vision_ctx.get("vision_trend", "N/A")
        vision_conf   = vision_ctx.get("vision_confidence", 0)

        # ── Fib ───────────────────────────────────────────────
        fib_zone    = fib_ctx.get("fib_zone", "N/A")
        fib_in_gold = fib_ctx.get("fib_in_golden", False)
        fib_signal  = fib_ctx.get("fib_signal", "WAIT")

        # ── Session (Day 63) ──────────────────────────────────
        curr_session     = session_ctx.get("current_session", "UNKNOWN")
        sess_volatility  = session_ctx.get("session_volatility", "NORMAL")
        sess_strategy    = session_ctx.get("session_strategy", "WAIT")
        sess_trade_ok    = session_ctx.get("session_trade_allowed", True)
        sess_min_conf    = session_ctx.get("session_min_confidence", 70)
        sess_risk_mult   = session_ctx.get("session_risk_mult", 1.0)
        pair_priority    = session_ctx.get("pair_session_priority", 50)
        pair_label       = session_ctx.get("pair_session_label", "FAIR")
        is_overlap       = session_ctx.get("is_overlap", False)
        is_dead_zone     = session_ctx.get("is_dead_zone", False)
        london_open_win  = session_ctx.get("london_open_window", False)
        in_transition    = session_ctx.get("in_session_transition", False)
        transition_type  = session_ctx.get("transition_type")
        transition_alert = session_ctx.get("transition_alert")
        session_score    = session_ctx.get("session_score", 0)
        session_grade    = session_ctx.get("session_grade", "C")
        fusion_allowed   = session_ctx.get("fusion_allowed", False)
        fusion_score     = session_ctx.get("fusion_score", 0)
        preferred_pairs  = session_ctx.get("preferred_pairs", [])
        gmt_time         = session_ctx.get("gmt_time", "N/A")

        # ── Intermarket / Macro (Day 65) ───────────────────────
        dxy_trend         = intermarket_ctx.get("dxy_trend", "NEUTRAL")
        dxy_change        = intermarket_ctx.get("dxy_change_pct", 0)
        gold_trend        = intermarket_ctx.get("gold_trend", "NEUTRAL")
        oil_trend         = intermarket_ctx.get("oil_trend", "NEUTRAL")
        us10y_trend       = intermarket_ctx.get("us10y_trend", "NEUTRAL")
        sp500_trend       = intermarket_ctx.get("sp500_trend", "NEUTRAL")
        vix_value         = intermarket_ctx.get("vix_value")
        vix_trend         = intermarket_ctx.get("vix_trend", "NEUTRAL")
        macro_regime      = intermarket_ctx.get("macro_regime", "NEUTRAL")
        macro_regime_conf = intermarket_ctx.get("macro_regime_confidence", 0)
        trading_mode      = intermarket_ctx.get("trading_mode", "NORMAL")
        usd_bias          = intermarket_ctx.get("usd_bias", "NEUTRAL")
        usd_confirmations = intermarket_ctx.get("usd_confirmations", [])
        macro_pair_bias   = intermarket_ctx.get("macro_pair_bias", "NEUTRAL")
        macro_currency_bias = intermarket_ctx.get("macro_currency_bias", {})
        macro_score       = intermarket_ctx.get("macro_score", 0)
        cross_asset_conf  = intermarket_ctx.get("cross_asset_confirmed", False)
        cross_asset_note  = intermarket_ctx.get("cross_asset_note", "")
        event_risk_elev   = intermarket_ctx.get("event_risk_elevated", False)
        event_risk_pen    = intermarket_ctx.get("event_risk_penalty", 0)
        macro_corr        = intermarket_ctx.get("macro_correlations", {})

        ctx = {
            "pair":      symbol,
            "timeframe": timeframe,
            "timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),

            # ── Day 63: Session Intelligence ──
            "session_intelligence": {
                "current_session":       curr_session,
                "gmt_time":              gmt_time,
                "session_volatility":    sess_volatility,
                "session_strategy":      sess_strategy,
                "session_trade_allowed": sess_trade_ok,
                "minimum_confidence":    sess_min_conf,
                "risk_multiplier":       sess_risk_mult,
                "pair_priority_score":   pair_priority,
                "pair_session_label":    pair_label,
                "is_overlap_session":    is_overlap,
                "is_dead_zone":          is_dead_zone,
                "london_open_window":    london_open_win,
                "in_session_transition": in_transition,
                "transition_type":       transition_type,
                "transition_alert":      transition_alert,
                "session_score":         session_score,
                "session_grade":         session_grade,
                "smc_session_fusion_allowed": fusion_allowed,
                "smc_session_fusion_score":   fusion_score,
                "preferred_pairs":       preferred_pairs[:5],
            },

            # ── Day 65: Global Market / Intermarket Intelligence ──
            "global_market_intelligence": {
                "dxy_trend":               dxy_trend,
                "dxy_change_pct":          dxy_change,
                "gold_trend":              gold_trend,
                "oil_trend":               oil_trend,
                "us10y_yield_trend":       us10y_trend,
                "sp500_trend":             sp500_trend,
                "vix_value":               vix_value,
                "vix_trend":               vix_trend,
                "macro_regime":            macro_regime,          # RISK_ON / RISK_OFF / NEUTRAL
                "macro_regime_confidence": macro_regime_conf,
                "trading_mode":            trading_mode,          # NORMAL / CAUTIOUS / DEFENSIVE
                "usd_bias":                usd_bias,              # STRONG / MODERATE / NEUTRAL
                "usd_confirmations":       usd_confirmations,
                "macro_pair_bias":         macro_pair_bias,       # BUY / SELL / NEUTRAL for THIS pair
                "macro_currency_bias":     macro_currency_bias,
                "macro_score":             macro_score,           # 0-100
                "cross_asset_confirmed":   cross_asset_conf,
                "cross_asset_note":        cross_asset_note,
                "event_risk_elevated":     event_risk_elev,
                "event_risk_penalty":      event_risk_pen,
                "intermarket_correlations": macro_corr,
            },

            "price_action": {
                "current_price":   close_price,
                "trend":           trend,
                "rsi":             round(rsi, 1),
                "rsi_signal":      rsi_sig,
                "macd_cross":      macd_cross,
                "atr":             round(atr, 5),
                "bb_position_pct": round(bb_pct * 100, 1),
            },

            "patterns": {
                "latest_pattern": latest_pat,
                "pattern_signal": pat_signal,
                "recent":         recent_pats[-3:] if recent_pats else [],
            },

            "support_resistance": {
                "nearest_support":    nearest_sup,
                "nearest_resistance": nearest_res,
                "price_location":     location,
                "pivot":              pivot,
            },

            "market_regime": {
                "regime":     market_regime,
                "direction":  direction,
                "strength":   strength,
                "volatility": volatility,
            },

            "multi_timeframe": {
                "overall_bias": mtf_overall,
                "confidence":   mtf_conf,
                "timeframes":   mtf_trends,
            },

            "market_bias_engine": {
                "bias":         bias_label,
                "confidence":   bias_conf,
                "has_conflict": has_conflict,
            },

            "smart_money_concepts": {
                "signal":               smc_signal,
                "direction":            smc_direction,
                "confluence_score":     smc_score,
                "grade":                smc_grade,
                "factors_present":      [k for k, v in smc_factors.items() if v],
                "h4_order_block_zone":  smc_ob_zone,
                "h4_fvg_zone":          smc_fvg_zone,
                "h4_bos":               smc_h4_bos,
                "h4_choch":             smc_h4_choch,
                "summary":              smc_analysis,
            },

            "fibonacci": {
                "zone":         fib_zone,
                "in_golden":    fib_in_gold,
                "signal":       fib_signal,
            },

            "vision_ai": {
                "trend":      vision_trend,
                "confidence": vision_conf,
            },

            "sentiment": {
                "score":           sent_score,
                "bias":            sent_bias,
                "confidence":      sent_conf,
                "retail_long_pct": retail_long,
                "fear_greed":      fg_label,
                "dxy_trend":       dxy_trend_sent,
                "key_reasons":     sent_reasons[:3],
            },

            "news": {
                "trade_allowed":   trade_allowed,
                "risk_level":      news_risk,
                "upcoming_events": upcoming_news[:3],
            },

            "rule_engine": {
                "signal":     rule_signal,
                "confidence": rule_conf,
            },

            "trade_history": {
                "total_trades":   total_trades,
                "win_rate_pct":   win_rate,
                "recent_results": recent_results[-5:],
                "key_lessons":    lessons[:3],
            },
        }

        return json.dumps(ctx, indent=2, default=str)

    def _call_llm(self, context: str) -> str:
        """Call LLM with Groq (primary) → Gemini (fallback) chain.
        Multi-key rotation: if one key fails, automatically tries next.
        Anthropic + OpenRouter are intentionally NOT used per user request."""
        user_prompt = (
            "Here is the complete market intelligence package (session-aware AND "
            "macro/intermarket-aware) for analysis:\n\n"
            f"{context}\n\n"
            "IMPORTANT: Check session_intelligence block first, then "
            "global_market_intelligence block. Follow session rules and macro rules strictly.\n"
            "Provide your professional trade decision as JSON."
        )

        import time as _time
        from core.llm_key_manager import log_llm_call_failure

        # Day 76: Primary: Gemini (higher free limits), Fallback: Groq
        # Try Gemini first (multi-key retry)
        max_retries = 3
        for attempt in range(max_retries):
            client = _gemini_client
            if client is None and _key_manager is not None:
                client = _key_manager.get_gemini_client()
            if client is None:
                log.debug("[MasterAnalyst] No Gemini client available (keys exhausted or missing)")
                break
            try:
                full_prompt = f"{self._SYSTEM}\n\n{user_prompt}"
                resp = client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=full_prompt,
                )
                if _key_manager is not None:
                    _key_manager.mark_gemini_success()
                return resp.text.strip()
            except Exception as e:
                info = log_llm_call_failure(
                    log, "Gemini", GEMINI_MODEL, attempt, max_retries, e
                )
                if _key_manager is not None:
                    _key_manager.mark_gemini_failure(
                        info["error_str"], info["rate_limited"]
                    )
                    import sys
                    current_module = sys.modules[__name__]
                    current_module._gemini_client = _key_manager.get_gemini_client()
                if attempt < max_retries - 1:
                    _time.sleep(1)

        # Fallback: Groq (with multi-key retry)
        for attempt in range(max_retries):
            client = _groq_client
            if client is None and _key_manager is not None:
                client = _key_manager.get_groq_client()
            if client is None:
                log.error("[MasterAnalyst] No Groq client available (keys exhausted or missing)")
                break
            try:
                resp = client.chat.completions.create(
                    model=GROQ_MODEL,
                    max_tokens=MAX_TOK,
                    temperature=0.2,
                    messages=[
                        {"role": "system", "content": self._SYSTEM},
                        {"role": "user", "content": user_prompt},
                    ],
                )
                if _key_manager is not None:
                    _key_manager.mark_groq_success()
                return resp.choices[0].message.content.strip()
            except Exception as e:
                info = log_llm_call_failure(
                    log, "Groq", GROQ_MODEL, attempt, max_retries, e
                )
                if _key_manager is not None:
                    _key_manager.mark_groq_failure(
                        info["error_str"], info["rate_limited"]
                    )
                    # Get fresh client with different key
                    import sys
                    current_module = sys.modules[__name__]
                    current_module._groq_client = _key_manager.get_groq_client()
                if attempt < max_retries - 1:
                    _time.sleep(1)

        raise RuntimeError("[MasterAnalyst] No LLM client available (all keys failed)")

    def _parse_response(self, raw: str) -> dict:
        text = raw.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            log.error(f"[MasterAnalyst] JSON parse error: {e}")
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                raise

        data.setdefault("market_story", "Market analysis pending.")
        data.setdefault("key_levels", [])
        data.setdefault("trade_plan", {
            "signal": "WAIT", "entry": None, "sl": None,
            "tp1": None, "tp2": None, "confidence": 0,
            "reasoning": "Insufficient data."
        })
        data.setdefault("risks", [])
        data.setdefault("self_critique", "")
        data.setdefault("no_trade_reason", "")

        sig = data["trade_plan"].get("signal", "WAIT").upper()
        if sig not in ("BUY", "SELL", "WAIT"):
            sig = "WAIT"
        data["trade_plan"]["signal"] = sig
        return data

    def _calculate_final_confidence(
        self,
        llm_conf:       int,
        technical_conf: int,
        sentiment_conf: int,
        memory_ctx:     dict,
        smc_ctx:        dict = None,
        session_ctx:    dict = None,       # ← Day 63
        intermarket_ctx: dict = None,       # ← Day 65
    ) -> int:
        """
        Weighted average:
            LLM opinion          : 30%
            Technical signals    : 20%
            Sentiment             : 10%
            Historical success    : 8%
            SMC confluence        : 10%
            Session score         : 12%
            Macro score (Day 65)  : 10%   ← new

        Total = 100%
        """
        smc_ctx         = smc_ctx or {}
        session_ctx      = session_ctx or {}
        intermarket_ctx  = intermarket_ctx or {}

        win_rate      = memory_ctx.get("overall_win_rate", 50)
        smc_score     = smc_ctx.get("smc_score", 50)
        session_score = session_ctx.get("session_score", 50)
        macro_score   = intermarket_ctx.get("macro_score", 50)

        weighted = (
            llm_conf       * 0.30 +
            technical_conf * 0.20 +
            sentiment_conf * 0.10 +
            win_rate       * 0.08 +
            smc_score      * 0.10 +
            session_score  * 0.12 +
            macro_score    * 0.10
        )

        # Session risk multiplier adjustment
        sess_risk = session_ctx.get("session_risk_mult", 1.0)
        if sess_risk < 1.0:
            weighted *= sess_risk

        # Recent trades momentum
        recent = memory_ctx.get("recent_results", [])
        if recent:
            last_5      = recent[-5:]
            win_streak  = sum(1 for r in last_5 if r == "WIN")
            loss_streak = sum(1 for r in last_5 if r == "LOSS")
            if win_streak >= 3:
                weighted += 3
            if loss_streak >= 3:
                weighted -= 5

        # SMC grade bonus
        if smc_ctx.get("smc_grade") in ("A+", "A"):
            weighted += 3

        # Session overlap bonus
        if session_ctx.get("is_overlap"):
            weighted += 2

        # Day 65 — Macro alignment bonus / event risk penalty
        if intermarket_ctx.get("cross_asset_confirmed"):
            weighted += 3
        if intermarket_ctx.get("event_risk_elevated"):
            weighted -= intermarket_ctx.get("event_risk_penalty", 0)
        if intermarket_ctx.get("trading_mode") == "DEFENSIVE":
            weighted -= 8
        elif intermarket_ctx.get("trading_mode") == "CAUTIOUS":
            weighted -= 4

        # Dead zone penalty (should not reach here normally)
        if session_ctx.get("is_dead_zone"):
            weighted = 0

        return max(0, min(99, round(weighted)))

    def _fallback_result(self, signal: dict, reason: str) -> dict:
        sig  = signal.get("signal", "WAIT")
        conf = signal.get("confidence", 0)
        return {
            "market_story":     f"LLM unavailable — using rule engine signal: {sig}",
            "key_levels":       [],
            "trade_plan": {
                "signal":     sig,
                "entry":      None,
                "sl":         None,
                "tp1":        None,
                "tp2":        None,
                "confidence": conf,
                "reasoning":  f"Fallback — {reason}",
            },
            "risks":            ["LLM analysis unavailable"],
            "self_critique":    "",
            "no_trade_reason":  "" if sig != "WAIT" else reason,
            "final_confidence": conf,
            "llm_raw":          "",
            "error":            reason,
        }

    def get_ai_context(self, result: dict) -> dict:
        plan = result.get("trade_plan", {})
        return {
            "master_signal":     plan.get("signal", "WAIT"),
            "master_entry":      plan.get("entry"),
            "master_sl":         plan.get("sl"),
            "master_tp1":        plan.get("tp1"),
            "master_tp2":        plan.get("tp2"),
            "master_confidence": result.get("final_confidence", 0),
            "master_story":      result.get("market_story", ""),
            "master_risks":      result.get("risks", []),
            "master_critique":   result.get("self_critique", ""),
        }

    def print_summary(self, result: dict) -> None:
        plan = result.get("trade_plan", {})
        sig  = plan.get("signal", "WAIT")
        icons = {"BUY": "🟢", "SELL": "🔴", "WAIT": "🟡"}
        icon  = icons.get(sig, "⚪")
        bar   = "═" * 56

        print(f"\n{bar}")
        print(f"  🧠  MASTER ANALYST  (Day 42 + 44 + 47 + 63 + 65)")
        print(bar)
        print(f"  Signal          : {icon}  {sig}")
        print(f"  Final Confidence: {result.get('final_confidence', 0)}%")
        print(f"  LLM Confidence  : {plan.get('confidence', 0)}%")
        if sig in ("BUY", "SELL"):
            print(f"  Entry           : {plan.get('entry')}")
            print(f"  SL              : {plan.get('sl')}")
            print(f"  TP1             : {plan.get('tp1')}")
            print(f"  TP2             : {plan.get('tp2')}")
        print()
        print(f"  ── Market Story ──")
        story = result.get("market_story", "")
        words = story.split()
        line  = "  "
        for word in words:
            if len(line) + len(word) > 54:
                print(line)
                line = "  " + word + " "
            else:
                line += word + " "
        if line.strip():
            print(line)
        print()

        key_levels = result.get("key_levels", [])
        if key_levels:
            print(f"  ── Key Levels ──")
            print(f"  {key_levels}")
            print()

        risks = result.get("risks", [])
        if risks:
            print(f"  ── Risks ──")
            for r in risks:
                print(f"  ⚠  {r}")
            print()

        critique = result.get("self_critique", "")
        if critique:
            print(f"  ── Self Critique ──")
            print(f"  {critique}")
            print()

        reasoning = plan.get("reasoning", "")
        if reasoning:
            print(f"  ── Reasoning ──")
            print(f"  {reasoning}")

        if result.get("error"):
            print(f"\n  ⚠  Error: {result['error']}")

        print(bar + "\n")