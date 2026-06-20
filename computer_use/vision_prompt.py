# computer_use/vision_prompt.py  —  Day 47 | Vision Prompt Engineering
# ============================================================
# Chart Vision-এর জন্য carefully engineered prompt templates।
#
# তিন ধরনের prompt:
#   1. BASIC_CHART_PROMPT     — শুধু image দিলে
#   2. CONTEXT_CHART_PROMPT   — image + symbol + timeframe + indicators
#   3. CONFLICT_CHECK_PROMPT  — vision vs quant comparison
# ============================================================

import json


# ═══════════════════════════════════════════════════════════════
# 1. BASIC CHART ANALYSIS PROMPT
# ═══════════════════════════════════════════════════════════════

BASIC_CHART_SYSTEM = """You are an elite professional forex trader with 20 years of experience.
You can read charts visually like a human — you understand candle shapes, patterns, zones, and momentum.

Analyze the TradingView chart screenshot provided.

Return ONLY valid JSON. No markdown, no extra text, no code blocks.

JSON schema:
{
  "pair": "detected pair or UNKNOWN",
  "timeframe": "detected timeframe or UNKNOWN",
  "trend": "BULLISH" | "BEARISH" | "SIDEWAYS",
  "trend_strength": "STRONG" | "MODERATE" | "WEAK",
  "support": [float, float],
  "resistance": [float, float],
  "pattern": ["pattern1", "pattern2"],
  "market_condition": "brief description",
  "momentum": "STRONG" | "MODERATE" | "WEAK" | "DIVERGING",
  "entry_zones": ["zone description"],
  "risk_areas": ["risk description"],
  "market_psychology": "what is the market telling us",
  "confidence": 0-100
}"""


# ═══════════════════════════════════════════════════════════════
# 2. CONTEXT-AWARE CHART PROMPT (with quant data)
# ═══════════════════════════════════════════════════════════════

CONTEXT_CHART_SYSTEM = """You are an elite professional forex trader and chart analyst.

You will receive:
1. A TradingView chart screenshot
2. Quantitative context (symbol, timeframe, current price, indicators)

Your job: analyze the VISUAL chart AND incorporate the quantitative context.
The visual analysis should CONFIRM or CONTRADICT the quant data.

Return ONLY valid JSON. No markdown, no extra text.

JSON schema:
{
  "pair": "symbol",
  "timeframe": "timeframe",
  "trend": "BULLISH" | "BEARISH" | "SIDEWAYS",
  "trend_strength": "STRONG" | "MODERATE" | "WEAK",
  "support": [float],
  "resistance": [float],
  "pattern": ["pattern names"],
  "candlestick_patterns": ["hammer", "engulfing", etc],
  "chart_patterns": ["double_bottom", "triangle", etc],
  "market_condition": "description",
  "momentum": "STRONG" | "MODERATE" | "WEAK" | "DIVERGING",
  "entry_zones": ["description"],
  "risk_areas": ["description"],
  "market_psychology": "crowd behavior analysis",
  "visual_vs_quant": "CONFIRMS" | "CONTRADICTS" | "PARTIAL",
  "conflict_detail": "if contradiction, explain what differs",
  "confidence": 0-100,
  "pattern_confidence": 0-100,
  "trend_confidence": 0-100,
  "entry_confidence": 0-100
}"""


def build_context_prompt(
    symbol: str,
    timeframe: str,
    current_price: float,
    rsi: float = None,
    macd: str = None,
    trend: str = None,
    support: float = None,
    resistance: float = None,
) -> str:
    """Context-aware prompt-এর user message build করো।"""

    ctx = {
        "symbol": symbol,
        "timeframe": timeframe,
        "current_price": current_price,
    }

    if rsi is not None:
        ctx["RSI_14"] = round(rsi, 1)
        ctx["RSI_signal"] = (
            "OVERSOLD" if rsi < 30 else
            "OVERBOUGHT" if rsi > 70 else
            "NEUTRAL"
        )
    if macd:
        ctx["MACD_signal"] = macd
    if trend:
        ctx["quant_trend"] = trend
    if support:
        ctx["nearest_support"] = support
    if resistance:
        ctx["nearest_resistance"] = resistance

    return (
        "Quantitative context for this chart:\n\n"
        f"{json.dumps(ctx, indent=2)}\n\n"
        "Now analyze the chart screenshot visually and return JSON."
    )


# ═══════════════════════════════════════════════════════════════
# 3. CONFLICT CHECK PROMPT
# ═══════════════════════════════════════════════════════════════

CONFLICT_CHECK_SYSTEM = """You are a senior risk manager reviewing a potential trading conflict.

You have:
1. Quantitative analysis result (from technical indicators)
2. Visual analysis result (from chart screenshot)

They may disagree. Your job: identify the conflict, assess severity, and recommend action.

Return ONLY valid JSON:
{
  "has_conflict": true | false,
  "conflict_type": "TREND" | "PATTERN" | "MOMENTUM" | "NONE",
  "quant_says": "BUY/SELL/WAIT",
  "vision_says": "BUY/SELL/WAIT",
  "conflict_severity": "HIGH" | "MEDIUM" | "LOW" | "NONE",
  "explanation": "what is conflicting and why it matters",
  "recommendation": "WAIT_FOR_CONFIRMATION" | "TRUST_QUANT" | "TRUST_VISION" | "PROCEED",
  "confidence_adjustment": -30 to +10,
  "final_bias": "BUY" | "SELL" | "WAIT"
}"""


def build_conflict_prompt(quant_ctx: dict, vision_result: dict) -> str:
    """Conflict detection prompt তৈরি করো।"""
    return (
        "=== QUANTITATIVE ANALYSIS ===\n"
        f"{json.dumps(quant_ctx, indent=2, default=str)}\n\n"
        "=== VISUAL ANALYSIS ===\n"
        f"{json.dumps(vision_result, indent=2, default=str)}\n\n"
        "Compare these two analyses and identify any conflicts. Return JSON."
    )


# ═══════════════════════════════════════════════════════════════
# 4. MULTI-TIMEFRAME VISION PROMPT
# ═══════════════════════════════════════════════════════════════

MTF_VISION_SYSTEM = """You are a professional forex trader doing multi-timeframe visual analysis.

You will see a single chart. Based on visual cues (candle structure, patterns, momentum),
determine what the HIGHER timeframe context likely looks like.

Return ONLY valid JSON:
{
  "visible_timeframe_analysis": {
    "trend": "BULLISH/BEARISH/SIDEWAYS",
    "key_level": float,
    "pattern": "pattern name or NONE"
  },
  "implied_higher_tf": {
    "likely_bias": "BULLISH/BEARISH/NEUTRAL",
    "reason": "visual reasoning"
  },
  "trade_bias": "BUY" | "SELL" | "WAIT",
  "confidence": 0-100
}"""