# analysis/session_rules.py  —  Day 63 | Session Rules & Strategy Definitions
# ============================================================
# Forex market session time windows (GMT), characteristics,
# strategy modes, dead zones, and DST awareness.
# ============================================================

from datetime import timezone

# ── Session Time Windows (GMT, start inclusive, end exclusive) ─
SESSION_WINDOWS = {
    "SYDNEY": {
        "start": 22,   # 22:00 GMT
        "end":   7,    # 07:00 GMT next day (crosses midnight)
        "crosses_midnight": True,
    },
    "TOKYO": {
        "start": 0,    # 00:00 GMT
        "end":   9,    # 09:00 GMT
        "crosses_midnight": False,
    },
    "LONDON": {
        "start": 8,    # 08:00 GMT
        "end":   17,   # 17:00 GMT
        "crosses_midnight": False,
    },
    "NEW_YORK": {
        "start": 13,   # 13:00 GMT
        "end":   22,   # 22:00 GMT
        "crosses_midnight": False,
    },
    "LONDON_NY_OVERLAP": {
        "start": 13,   # 13:00 GMT
        "end":   17,   # 17:00 GMT
        "crosses_midnight": False,
    },
}

# ── Dead Zones (avoid trading) ────────────────────────────────
DEAD_ZONES = [
    {"start": 22, "end": 24, "reason": "Sydney open — very low liquidity"},
    {"start": 0,  "end": 2,  "reason": "Early Tokyo — low volume"},
]

# ── Session Characteristics ───────────────────────────────────
SESSION_CHARACTERISTICS = {
    "SYDNEY": {
        "volatility":    "LOW",
        "behavior":      "RANGING",
        "description":   "Low volatility range formation. Avoid breakout trades.",
        "risk_level":    "LOW",
    },
    "TOKYO": {
        "volatility":    "MEDIUM",
        "behavior":      "RANGING",
        "description":   "JPY movement dominant. Consolidation. Suited for range strategies.",
        "risk_level":    "LOW",
    },
    "LONDON": {
        "volatility":    "HIGH",
        "behavior":      "TRENDING",
        "description":   "Highest liquidity globally. Breakouts and liquidity sweeps common.",
        "risk_level":    "MEDIUM",
    },
    "NEW_YORK": {
        "volatility":    "HIGH",
        "behavior":      "TRENDING",
        "description":   "USD volatility. Trend continuation from London direction.",
        "risk_level":    "MEDIUM",
    },
    "LONDON_NY_OVERLAP": {
        "volatility":    "VERY_HIGH",
        "behavior":      "INSTITUTIONAL",
        "description":   "Maximum volume. Best setups. Only A+ trades allowed.",
        "risk_level":    "LOW",   # risk is low because setups are highest quality
    },
    "DEAD_ZONE": {
        "volatility":    "VERY_LOW",
        "behavior":      "NO_TRADE",
        "description":   "Low liquidity. Spreads widen. No trading recommended.",
        "risk_level":    "VERY_HIGH",
    },
    "BETWEEN_SESSIONS": {
        "volatility":    "LOW",
        "behavior":      "WAIT",
        "description":   "Between sessions. Wait for next session open.",
        "risk_level":    "HIGH",
    },
}

# ── Strategy Modes Per Session ────────────────────────────────
SESSION_STRATEGIES = {
    "SYDNEY": {
        "strategy":          "RANGE_TRADING",
        "action":            "Buy near range low, Sell near range high",
        "avoid":             "Breakout trades — false signals likely",
        "min_confidence":    65,
        "risk_multiplier":   0.7,
        "note":              "Low volatility. Tight SL. Small targets.",
    },
    "TOKYO": {
        "strategy":          "RANGE_TRADING",
        "action":            "JPY pairs: fade extremes. Range-bound entries.",
        "avoid":             "Trending breakouts — consolidation phase",
        "min_confidence":    65,
        "risk_multiplier":   0.8,
        "note":              "JPY dominates. USDJPY, EURJPY best suited.",
    },
    "LONDON": {
        "strategy":          "LONDON_BREAKOUT",
        "action":            "Asian range breakout. Liquidity sweep + BOS entry.",
        "avoid":             "Counter-trend during strong London moves",
        "min_confidence":    70,
        "risk_multiplier":   1.0,
        "note":              "Check Asian high/low for liquidity sweep direction.",
    },
    "NEW_YORK": {
        "strategy":          "TREND_CONTINUATION",
        "action":            "Continue London trend. USD news-driven moves.",
        "avoid":             "Reversals without strong SMC confirmation",
        "min_confidence":    72,
        "risk_multiplier":   1.0,
        "note":              "Follow London direction. Check order flow.",
    },
    "LONDON_NY_OVERLAP": {
        "strategy":          "A_PLUS_ONLY",
        "action":            "Full SMC confluence required. Institutional setups only.",
        "avoid":             "Anything below A+ grade",
        "min_confidence":    85,
        "risk_multiplier":   1.2,
        "note":              "Best trading window. Wait for perfect setup.",
    },
    "DEAD_ZONE": {
        "strategy":          "NO_TRADE",
        "action":            "Do nothing. Prepare for next session.",
        "avoid":             "All trades",
        "min_confidence":    999,  # impossible to meet
        "risk_multiplier":   0.0,
        "note":              "Low liquidity. Spreads wide. High slippage risk.",
    },
    "BETWEEN_SESSIONS": {
        "strategy":          "WAIT",
        "action":            "Wait for next session to open.",
        "avoid":             "Forcing trades",
        "min_confidence":    80,
        "risk_multiplier":   0.6,
        "note":              "Transitioning between sessions. Low participation.",
    },
}

# ── London Open Window (first 2 hours — best manipulation window) ─
LONDON_OPEN_WINDOW = {"start": 8, "end": 10}

# ── Minimum SMC Requirements per session ─────────────────────
SMC_REQUIREMENTS = {
    "SYDNEY":            {"min_smc_score": 50, "require_bos": False, "require_ob": False},
    "TOKYO":             {"min_smc_score": 55, "require_bos": False, "require_ob": False},
    "LONDON":            {"min_smc_score": 65, "require_bos": True,  "require_ob": True},
    "NEW_YORK":          {"min_smc_score": 65, "require_bos": True,  "require_ob": False},
    "LONDON_NY_OVERLAP": {"min_smc_score": 75, "require_bos": True,  "require_ob": True},
    "DEAD_ZONE":         {"min_smc_score": 999, "require_bos": True, "require_ob": True},
    "BETWEEN_SESSIONS":  {"min_smc_score": 70, "require_bos": False, "require_ob": False},
}