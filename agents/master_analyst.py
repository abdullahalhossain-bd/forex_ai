# agents/master_analyst.py  —  Day 42 (Master Analyst) + Day 44 (SMC context)
# ============================================================
# AI Trader-এর Final Reasoning Layer।
#
# সব intelligence module-এর output একত্র করে একটা
# professional "market story" + trade plan তৈরি করে।
#
# Pipeline:
#   Technical + Patterns + Fibonacci + Market Structure
#   + Sentiment + News + Trade History + SMC (Day 44)
#        ↓
#   Context Builder
#        ↓
#   LLM (claude-sonnet-4-6)  ←— Master Analyst Prompt
#        ↓
#   Structured JSON output (market_story, trade_plan, risks)
#        ↓
#   Self-Critique Loop
#        ↓
#   Final Confidence Score
#        ↓
#   Risk Engine → Execution
# ============================================================

import json
import os
import re
from datetime import datetime

from utils.logger import get_logger

log = get_logger("master_analyst")

# ── Anthropic client (same pattern as ai_analyst.py) ─────────
try:
    import anthropic
    _client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    LLM_AVAILABLE = True
except Exception:
    LLM_AVAILABLE = False
    log.warning("[MasterAnalyst] anthropic package not found — LLM disabled")

MODEL    = "claude-sonnet-4-6"
MAX_TOK  = 1500


# ═══════════════════════════════════════════════════════════════
# MASTER ANALYST
# ═══════════════════════════════════════════════════════════════

class MasterAnalyst:
    """
    Professional Forex Trader Brain।

    সব module-এর output একত্র করে:
    1. Market story তৈরি করে
    2. Key levels identify করে
    3. Trade plan বানায়
    4. নিজে নিজে critique করে
    5. Final confidence calculate করে
    """

    # ── System Prompt ─────────────────────────────────────────
    _SYSTEM = """You are an elite professional forex trader and market analyst with 20 years of experience, fluent in both classic technical analysis and Smart Money Concepts (SMC) — order blocks, fair value gaps, liquidity sweeps, BOS/CHoCH.

Your job is to synthesize ALL available market intelligence into ONE coherent trade decision.

Rules:
1. Do NOT force a trade. If conditions are unclear or risky, return WAIT.
2. A good trader knows when NOT to trade.
3. Think like a story: What is the market doing? Why? Where is it going?
4. Consider ALL inputs — technical, sentiment, news, history, AND smart_money_concepts.
5. The `smart_money_concepts` block reflects institutional order-flow context (H4 order
   blocks / fair value gaps / structure shifts, confirmed on M15). Treat a high SMC
   confluence score (smc_score >= 65, grade A or A+) as a strong supporting factor — but
   never let it override a clear news block or a critical multi-timeframe conflict.
6. Self-critique: What could go wrong? Am I missing something?

Output ONLY valid JSON. No markdown, no extra text, no code blocks.

JSON schema:
{
  "market_story": "2-4 sentence narrative of what the market is doing and why",
  "key_levels": [float, float, float],
  "trade_plan": {
    "signal": "BUY" | "SELL" | "WAIT",
    "entry": float | null,
    "sl": float | null,
    "tp1": float | null,
    "tp2": float | null,
    "confidence": integer (0-100),
    "reasoning": "1-2 sentence rationale"
  },
  "risks": ["risk 1", "risk 2"],
  "self_critique": "What could go wrong or what am I missing?",
  "no_trade_reason": "Only filled if signal is WAIT — why not trading"
}"""

    # ─────────────────────────────────────────────
    # MAIN METHOD
    # ─────────────────────────────────────────────

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
    ) -> dict:
        """
        সব context নিয়ে Master Analyst LLM-কে call করো।

        Returns:
            {
                "market_story": str,
                "key_levels": list,
                "trade_plan": {signal, entry, sl, tp1, tp2, confidence, reasoning},
                "risks": list,
                "self_critique": str,
                "final_confidence": int,
                "llm_raw": str,
                "error": str | None
            }
        """
        # Build structured context
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
        )

        # LLM call
        if not LLM_AVAILABLE:
            return self._fallback_result(signal, "LLM not available")

        try:
            raw = self._call_llm(context)
            parsed = self._parse_response(raw)
        except Exception as e:
            log.error(f"[MasterAnalyst] LLM error: {e}")
            return self._fallback_result(signal, str(e))

        # Final confidence = weighted average
        final_conf = self._calculate_final_confidence(
            llm_conf      = parsed.get("trade_plan", {}).get("confidence", 50),
            technical_conf = signal.get("confidence", 50),
            sentiment_conf = (sentiment_ctx or {}).get("sentiment_conf", 50),
            memory_ctx     = memory_ctx or {},
            smc_ctx        = smc_ctx or {},
        )

        result = {
            **parsed,
            "final_confidence": final_conf,
            "llm_raw":          raw,
            "error":            None,
        }

        log.info(
            f"[MasterAnalyst] {symbol} | "
            f"Signal: {parsed.get('trade_plan', {}).get('signal')} | "
            f"LLM Conf: {parsed.get('trade_plan', {}).get('confidence')}% | "
            f"Final Conf: {final_conf}%"
        )
        return result

    # ─────────────────────────────────────────────
    # CONTEXT BUILDER  ⭐⭐⭐⭐⭐
    # ─────────────────────────────────────────────

    def _build_context(
        self,
        symbol, timeframe,
        ind_ctx, pat_ctx, sr_ctx,
        regime, mtf_bias, signal,
        sentiment_ctx, news_ctx,
        memory_ctx, bias_ctx,
        smc_ctx,
        fib_ctx=None,
        advanced_pat_ctx=None,
        vision_ctx=None,
    ) -> str:
        """
        সব module-এর output একটা clean, structured JSON string-এ সাজাও।
        LLM raw indicator numbers দেখলে confuse হয় — তাই human-readable।
        """

        # ── Technical summary ──────────────────────
        trend       = ind_ctx.get("trend", "unknown")
        rsi         = ind_ctx.get("rsi", 50)
        rsi_sig     = ind_ctx.get("rsi_signal", "neutral")
        macd_cross  = ind_ctx.get("macd_cross", "")
        close_price = ind_ctx.get("price", ind_ctx.get("close", 0))
        atr         = ind_ctx.get("atr", 0)
        bb_pct      = ind_ctx.get("bb_pct", 0.5)

        # ── Pattern summary ────────────────────────
        latest_pat  = pat_ctx.get("latest_pattern", "none")
        pat_signal  = pat_ctx.get("pattern_signal", "")
        recent_pats = pat_ctx.get("recent_patterns", [])

        # ── S/R summary ────────────────────────────
        nearest_sup = sr_ctx.get("nearest_support")
        nearest_res = sr_ctx.get("nearest_resistance")
        location    = sr_ctx.get("price_location", "mid_range")
        pivot       = sr_ctx.get("pivot")

        # ── Regime ────────────────────────────────
        market_regime   = regime.get("regime", "UNKNOWN")
        direction       = regime.get("direction", "NEUTRAL")
        strength        = regime.get("strength", "WEAK")
        volatility      = regime.get("volatility", "NORMAL")

        # ── MTF ───────────────────────────────────
        mtf_overall = mtf_bias.get("bias", "NEUTRAL") if mtf_bias else "NEUTRAL"
        mtf_conf    = mtf_bias.get("confidence", "LOW") if mtf_bias else "LOW"
        mtf_trends  = mtf_bias.get("trends", {}) if mtf_bias else {}

        # ── Rule signal ───────────────────────────
        rule_signal = signal.get("signal", "NO TRADE")
        rule_conf   = signal.get("confidence", 0)

        # ── Bias ──────────────────────────────────
        bias_label  = bias_ctx.get("bias", "NEUTRAL")
        bias_conf   = bias_ctx.get("confidence_pct", 0)
        has_conflict = bias_ctx.get("has_conflict", False)

        # ── Sentiment ─────────────────────────────
        sent_score  = sentiment_ctx.get("sentiment_score", 0)
        sent_bias   = sentiment_ctx.get("sentiment_bias", "NEUTRAL")
        sent_conf   = sentiment_ctx.get("sentiment_conf", 0)
        retail_long = sentiment_ctx.get("retail_long_pct", 50)
        fg_label    = sentiment_ctx.get("fg_label", "NEUTRAL")
        dxy_trend   = sentiment_ctx.get("dxy_trend", "NEUTRAL")
        sent_reasons = sentiment_ctx.get("sentiment_reasons", [])

        # ── News ──────────────────────────────────
        trade_allowed = news_ctx.get("trade_allowed", True) if news_ctx else True
        upcoming_news = news_ctx.get("upcoming_events", []) if news_ctx else []
        news_risk     = news_ctx.get("risk_level", "LOW") if news_ctx else "LOW"

        # ── Memory / History ──────────────────────
        win_rate      = memory_ctx.get("overall_win_rate", 0)
        total_trades  = memory_ctx.get("total_trades", 0)
        recent_results = memory_ctx.get("recent_results", [])
        lessons       = memory_ctx.get("lessons", [])

        # ── SMC (Day 44) ───────────────────────────
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

        # ── Fibonacci (if available) ────────────────
        fib_levels = fib_ctx.get("fib_levels", []) if fib_ctx else []
        fib_confluence = fib_ctx.get("confluence", {}) if fib_ctx else {}
        fib_valid = fib_ctx.get("fib_valid", False) if fib_ctx else False

        # ── Advanced patterns (if available) ──────────
        adv_pat_list = advanced_pat_ctx.get("patterns", []) if advanced_pat_ctx else []
        adv_combined = advanced_pat_ctx.get("combined_signal", "NONE") if advanced_pat_ctx else "NONE"

        # ── Vision AI (if available) ─────────────────
        vision_trend = vision_ctx.get("vision_trend", "UNKNOWN") if vision_ctx else "UNKNOWN"
        vision_conf = vision_ctx.get("vision_confidence", 0) if vision_ctx else 0

        # ── Build JSON context ─────────────────────
        ctx = {
            "pair":      symbol,
            "timeframe": timeframe,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if hasattr(datetime, 'timezone') else datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),

            "price_action": {
                "current_price":  close_price,
                "trend":          trend,
                "rsi":            round(rsi, 1),
                "rsi_signal":     rsi_sig,
                "macd_cross":     macd_cross,
                "atr":            round(atr, 5),
                "bb_position_pct": round(bb_pct * 100, 1),
            },

            "patterns": {
                "latest_pattern": latest_pat,
                "pattern_signal": pat_signal,
                "recent":        recent_pats[-3:] if recent_pats else [],
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
                "signal":          smc_signal,
                "direction":       smc_direction,
                "confluence_score": smc_score,
                "grade":           smc_grade,
                "factors_present": [k for k, v in smc_factors.items() if v],
                "h4_order_block_zone": smc_ob_zone,
                "h4_fvg_zone":         smc_fvg_zone,
                "h4_bos":              smc_h4_bos,
                "h4_choch":            smc_h4_choch,
                "summary":             smc_analysis,
            },

            "sentiment": {
                "score":              sent_score,
                "bias":               sent_bias,
                "confidence":         sent_conf,
                "retail_long_pct":    retail_long,
                "fear_greed":         fg_label,
                "dxy_trend":          dxy_trend,
                "key_reasons":        sent_reasons[:3],
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
                "total_trades":    total_trades,
                "win_rate_pct":    win_rate,
                "recent_results":  recent_results[-5:],
                "key_lessons":     lessons[:3],
            },

            "fibonacci": {
                "valid": fib_valid,
                "levels": fib_levels[:5],
                "confluence": fib_confluence,
            } if fib_ctx else None,

            "advanced_patterns": {
                "detected": adv_pat_list[:3],
                "combined_signal": adv_combined,
            } if advanced_pat_ctx else None,

            "vision_ai": {
                "trend": vision_trend,
                "confidence": vision_conf,
            } if vision_ctx else None,
        }

        # Remove None entries to keep context clean
        ctx = {k: v for k, v in ctx.items() if v is not None}

        return json.dumps(ctx, indent=2, default=str)

    # ─────────────────────────────────────────────
    # LLM CALL
    # ─────────────────────────────────────────────

    def _call_llm(self, context: str) -> str:
        user_prompt = (
            "Here is the complete market intelligence package for analysis:\n\n"
            f"{context}\n\n"
            "Synthesize all this information and provide your professional trade decision as JSON."
        )

        response = _client.messages.create(
            model      = MODEL,
            max_tokens = MAX_TOK,
            system     = self._SYSTEM,
            messages   = [{"role": "user", "content": user_prompt}],
        )
        return response.content[0].text.strip()

    # ─────────────────────────────────────────────
    # RESPONSE PARSER
    # ─────────────────────────────────────────────

    def _parse_response(self, raw: str) -> dict:
        """LLM output parse করো — markdown fence strip করে।"""
        text = raw.strip()

        # Strip ```json ... ``` fences if present
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            log.error(f"[MasterAnalyst] JSON parse error: {e}\nRaw: {text[:300]}")
            # Try to extract JSON substring
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                raise

        # Ensure required fields exist with defaults
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

        # Normalize signal
        sig = data["trade_plan"].get("signal", "WAIT").upper()
        if sig not in ("BUY", "SELL", "WAIT"):
            sig = "WAIT"
        data["trade_plan"]["signal"] = sig

        return data

    # ─────────────────────────────────────────────
    # FINAL CONFIDENCE  ⭐⭐⭐⭐⭐
    # ─────────────────────────────────────────────

    def _calculate_final_confidence(
        self,
        llm_conf:       int,
        technical_conf: int,
        sentiment_conf: int,
        memory_ctx:     dict,
        smc_ctx:        dict = None,
    ) -> int:
        """
        Weighted average:
            LLM opinion         : 35%
            Technical signals   : 30%
            Sentiment           : 15%
            Historical success  : 10%
            SMC confluence       : 10%   (Day 44)

        History bonus/penalty based on win rate.
        """
        smc_ctx = smc_ctx or {}
        win_rate     = memory_ctx.get("overall_win_rate", 50)
        hist_score   = win_rate   # 0–100
        smc_score    = smc_ctx.get("smc_score", 50)

        weighted = (
            llm_conf       * 0.35 +
            technical_conf * 0.30 +
            sentiment_conf * 0.15 +
            hist_score     * 0.10 +
            smc_score       * 0.10
        )

        # Recent trades momentum bonus
        recent = memory_ctx.get("recent_results", [])
        if recent:
            last_5    = recent[-5:]
            win_streak = sum(1 for r in last_5 if r == "WIN")
            loss_streak = sum(1 for r in last_5 if r == "LOSS")
            if win_streak >= 3:
                weighted += 3
            if loss_streak >= 3:
                weighted -= 5   # on losing run → reduce confidence

        # A+/A grade SMC setup → small confidence bump (institutional confluence)
        if smc_ctx.get("smc_grade") in ("A+", "A"):
            weighted += 3

        return max(0, min(99, round(weighted)))

    # ─────────────────────────────────────────────
    # FALLBACK (no LLM)
    # ─────────────────────────────────────────────

    def _fallback_result(self, signal: dict, reason: str) -> dict:
        sig = signal.get("signal", "WAIT")
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
            "risks":           ["LLM analysis unavailable"],
            "self_critique":   "",
            "no_trade_reason": "" if sig != "WAIT" else reason,
            "final_confidence": conf,
            "llm_raw":          "",
            "error":            reason,
        }

    # ─────────────────────────────────────────────
    # AI CONTEXT  (DecisionAgent handoff)
    # ─────────────────────────────────────────────

    def get_ai_context(self, result: dict) -> dict:
        """DecisionAgent-এ inject করার জন্য।"""
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

    # ─────────────────────────────────────────────
    # PRINT SUMMARY
    # ─────────────────────────────────────────────

    def print_summary(self, result: dict) -> None:
        plan = result.get("trade_plan", {})
        sig  = plan.get("signal", "WAIT")
        icons = {"BUY": "🟢", "SELL": "🔴", "WAIT": "🟡"}
        icon  = icons.get(sig, "⚪")
        bar   = "═" * 56

        print(f"\n{bar}")
        print(f"  🧠  MASTER ANALYST  (Day 42 + Day 44 SMC)")
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
        # Word-wrap at 52 chars
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
