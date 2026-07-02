# analysis/book_rules_index.py
# ============================================================
# Machine-Readable Book Rules Registry
# ============================================================
# Maps every extractable rule from "The Only Technical Analysis
# Book You Will Ever Need" (Pages 1-151) to its implementation.
#
# This registry can be queried programmatically to:
#   - List all rules by chapter
#   - List all rules by category (pattern, indicator, risk, etc.)
#   - Find implementation file/function for a given rule
#   - Verify completeness (all rules have implementations)
#   - Generate documentation
#
# Usage:
#   from analysis.book_rules_index import BOOK_RULES, get_rules_by_chapter
#   chapter_5_rules = get_rules_by_chapter(5)
# ============================================================

from dataclasses import dataclass, field
from typing import Optional, List, Dict


@dataclass(frozen=True)
class BookRule:
    """Single rule extracted from the book."""
    rule_id: str                    # e.g., "P106-HAMMER"
    page: int                       # book page number
    chapter: int                    # chapter number
    category: str                   # "pattern" | "indicator" | "risk" | "trend" | "strategy"
    name: str                       # human-readable name
    rule_type: str                  # "deterministic" | "needs_confirmation" | "design_principle"
    implementation_file: str        # path to implementation
    implementation_function: str    # function/class name
    description: str                # short description
    no_trade_condition: bool = False  # True if this rule defines a NO_TRADE state


# ═══════════════════════════════════════════════════════════════
# COMPLETE RULE REGISTRY (Pages 1-151)
# ═══════════════════════════════════════════════════════════════

BOOK_RULES: List[BookRule] = [


    # ── CHAPTER 1: TA FUNDAMENTALS (Pages 9-21) ──────────────
    BookRule("P9-TA_FOUNDATION", 9, 1, "fundamental", "TA Foundation", "design_principle",
             "data/indicators.py", "Indicators.add_all",
             "OHLC data is the foundation of TA"),
    BookRule("P15-LIMITATIONS", 15, 1, "fundamental", "TA Limitations", "design_principle",
             "agents/analysis_agent.py", "AnalysisAgent.run",
             "TA should be combined with fundamental/sentiment analysis"),

    # ── CHAPTER 2: S/R, VOLUME, CHARTS (Pages 22-36) ─────────
    BookRule("P22-SR_ZONE", 22, 2, "pattern", "S/R Zone Detection", "deterministic",
             "analysis/support_resistance.py", "SupportResistance.analyze",
             "Swing high/low cluster → S/R zone"),
    BookRule("P25-ZONE_STRENGTH", 25, 2, "pattern", "Zone Strength (2/3/4+)", "deterministic",
             "analysis/support_resistance.py", "_classify_strength",
             "2=Weak, 3=Medium, 4+=Strong"),
    BookRule("P25-ROLE_REVERSAL", 25, 2, "pattern", "Role Reversal", "deterministic",
             "analysis/support_resistance.py", "_detect_role_reversal",
             "Broken support→resistance, broken resistance→support"),
    BookRule("P28-OBV", 28, 2, "indicator", "On-Balance Volume", "deterministic",
             "data/indicators.py", "_add_obv",
             "Volume confirms price trend"),
    BookRule("P32-VOLUME_RSI", 32, 2, "indicator", "Volume RSI", "deterministic",
             "data/indicators_ext.py", "_volume_rsi",
             "RSI applied to volume"),

    # ── CHAPTER 3: INDICATORS (Pages 37-55) ──────────────────
    BookRule("P38-MA", 38, 3, "indicator", "Moving Average", "deterministic",
             "data/indicators.py", "_add_moving_averages",
             "SMA + EMA, trend identification"),
    BookRule("P42-RSI", 42, 3, "indicator", "RSI (14)", "deterministic",
             "data/indicators.py", "_add_rsi",
             "RSI = 100 - 100/(1+RS), overbought>70, oversold<30"),
    BookRule("P44-STOCHASTIC", 44, 3, "indicator", "Stochastic", "deterministic",
             "data/indicators.py", "_add_stochastic",
             "%K + %D oscillator"),
    BookRule("P46-FIBONACCI", 46, 3, "indicator", "Fibonacci Retracement", "deterministic",
             "analysis/fibonacci.py", "FibonacciEngine.analyze",
             "23.6%, 38.2%, 50%, 61.8%, 78.6%"),
    BookRule("P50-BOLLINGER", 50, 3, "indicator", "Bollinger Bands", "deterministic",
             "data/indicators.py", "_add_bollinger",
             "SMA ± 2×StdDev"),
    BookRule("P53-ATR", 53, 3, "indicator", "ATR", "deterministic",
             "analysis/_engine_utils.py", "atr_series",
             "Volatility measure for SL sizing"),

    # ── CHAPTER 4: TREND + MTF (Pages 56-71) ─────────────────
    BookRule("P59-HH_HL_UPTREND", 59, 4, "trend", "HH/HL Uptrend", "deterministic",
             "analysis/structure.py", "MarketStructureEngine",
             "Higher Highs + Higher Lows = uptrend"),
    BookRule("P59-LH_LL_DOWNTREND", 59, 4, "trend", "LH/LL Downtrend", "deterministic",
             "analysis/structure.py", "MarketStructureEngine",
             "Lower Highs + Lower Lows = downtrend"),
    BookRule("P59-SIDEWAYS", 59, 4, "trend", "Sideways (no-trade)", "deterministic",
             "analysis/structure.py", "MarketStructureEngine",
             "No clear HH/HL or LH/LL → WAIT",
             no_trade_condition=True),
    BookRule("P62-TRENDLINE", 62, 4, "pattern", "Wick-based Trendline", "deterministic",
             "analysis/trendline_engine.py", "TrendlineEngine.analyze",
             "Connect swing wick extremes"),
    BookRule("P63-BOS", 63, 4, "trend", "Break of Structure", "deterministic",
             "analysis/structure.py", "_detect_bos",
             "Trend continuation signal"),
    BookRule("P63-CHOCH", 63, 4, "trend", "Change of Character", "deterministic",
             "analysis/structure.py", "_detect_choch",
             "Trend reversal signal (needs confirmation)"),
    BookRule("P69-MTF_3TIER", 69, 4, "trend", "3-Tier MTF System", "deterministic",
             "analysis/structure_mtf.py", "MTFStructureEngine",
             "Trend→Signal→Entry timeframe hierarchy"),

    # ── CHAPTER 5: CANDLESTICK PATTERNS (Pages 72-99) ────────
    BookRule("P79-HAMMER", 79, 5, "pattern", "Hammer", "deterministic",
             "analysis/high_reliability_patterns.py", "_detect_hammer",
             "Long lower wick ≥2× body, bullish reversal"),
    BookRule("P80-SHOOTING_STAR", 80, 5, "pattern", "Shooting Star", "deterministic",
             "analysis/high_reliability_patterns.py", "_detect_shooting_star",
             "Long upper wick ≥2× body, bearish reversal"),
    BookRule("P82-INVERTED_HAMMER", 82, 5, "pattern", "Inverted Hammer", "deterministic",
             "analysis/high_reliability_patterns.py", "_detect_inverted_hammer",
             "Hammer shape in downtrend (needs confirmation)"),
    BookRule("P83-HANGING_MAN", 83, 5, "pattern", "Hanging Man", "deterministic",
             "analysis/high_reliability_patterns.py", "_detect_hanging_man",
             "Hammer shape in uptrend, bearish warning"),
    BookRule("P85-DOJI", 85, 5, "pattern", "Doji", "deterministic",
             "analysis/high_reliability_patterns.py", "_detect_doji",
             "Open≈Close, indecision",
             no_trade_condition=True),  # Multi-Doji → WAIT
    BookRule("P88-BULL_MARUBOZU", 88, 5, "pattern", "Bullish Marubozu", "deterministic",
             "analysis/high_reliability_patterns.py", "_detect_bullish_marubozu",
             "Body ≥90% range, strong buyer momentum"),
    BookRule("P88-BEAR_MARUBOZU", 88, 5, "pattern", "Bearish Marubozu", "deterministic",
             "analysis/high_reliability_patterns.py", "_detect_bearish_marubozu",
             "Body ≥90% range, strong seller momentum"),
    BookRule("P90-BULL_ENGULFING", 90, 5, "pattern", "Bullish Engulfing", "deterministic",
             "analysis/high_reliability_patterns.py", "_detect_bullish_engulfing",
             "2nd candle engulfs 1st body, bullish reversal"),
    BookRule("P90-BEAR_ENGULFING", 90, 5, "pattern", "Bearish Engulfing", "deterministic",
             "analysis/high_reliability_patterns.py", "_detect_bearish_engulfing",
             "2nd candle engulfs 1st body, bearish reversal"),
    BookRule("P92-TWEEZER_TOP", 92, 5, "pattern", "Tweezer Top", "deterministic",
             "analysis/high_reliability_patterns.py", "_detect_tweezer_top",
             "Equal high rejected twice, bearish"),
    BookRule("P92-TWEEZER_BOTTOM", 92, 5, "pattern", "Tweezer Bottom", "deterministic",
             "analysis/high_reliability_patterns.py", "_detect_tweezer_bottom",
             "Equal low rejected twice, bullish"),
    BookRule("P94-PIERCING_LINE", 94, 5, "pattern", "Piercing Line", "deterministic",
             "analysis/high_reliability_patterns.py", "_detect_piercing_line",
             "Bullish candle closes ≥50% into prior bearish body"),
    BookRule("P94-DARK_CLOUD", 94, 5, "pattern", "Dark Cloud Cover", "deterministic",
             "analysis/high_reliability_patterns.py", "_detect_dark_cloud_cover",
             "Bearish candle closes ≥50% into prior bullish body"),
    BookRule("P96-HARAMI", 96, 5, "pattern", "Harami (Bull/Bear)", "deterministic",
             "analysis/high_reliability_patterns.py", "_detect_harami",
             "Small candle inside large candle, momentum weakening"),
    BookRule("P97-MORNING_STAR", 97, 5, "pattern", "Morning Star", "deterministic",
             "analysis/high_reliability_patterns.py", "_detect_morning_star",
             "Bearish→indecision→bullish, confirmed reversal"),
    BookRule("P97-EVENING_STAR", 97, 5, "pattern", "Evening Star", "deterministic",
             "analysis/high_reliability_patterns.py", "_detect_evening_star",
             "Bullish→indecision→bearish, confirmed reversal"),
    BookRule("P98-THREE_SOLDIERS", 98, 5, "pattern", "Three White Soldiers", "deterministic",
             "analysis/high_reliability_patterns.py", "_detect_three_white_soldiers",
             "3 consecutive large bullish candles, continuation"),
    BookRule("P98-THREE_CROWS", 98, 5, "pattern", "Three Black Crows", "deterministic",
             "analysis/high_reliability_patterns.py", "_detect_three_black_crows",
             "3 consecutive large bearish candles, continuation"),
    BookRule("P98-THREE_INSIDE_UP", 98, 5, "pattern", "Three Inside Up", "deterministic",
             "analysis/high_reliability_patterns.py", "_detect_three_inside_up",
             "Bullish Harami + confirmation candle"),
    BookRule("P98-THREE_INSIDE_DOWN", 98, 5, "pattern", "Three Inside Down", "deterministic",
             "analysis/high_reliability_patterns.py", "_detect_three_inside_down",
             "Bearish Harami + confirmation candle"),

    # ── CHAPTER 6: CHART PATTERNS (Pages 100-118) ────────────
    BookRule("P103-DOUBLE_TOP", 103, 6, "pattern", "Double Top", "deterministic",
             "analysis/advanced_patterns.py", "detect_double_top_bottom",
             "Two peaks at same level, bearish reversal"),
    BookRule("P103-DOUBLE_BOTTOM", 103, 6, "pattern", "Double Bottom", "deterministic",
             "analysis/advanced_patterns.py", "detect_double_top_bottom",
             "Two troughs at same level, bullish reversal"),
    BookRule("P106-HEAD_SHOULDERS", 106, 6, "pattern", "Head & Shoulders", "deterministic",
             "analysis/advanced_patterns.py", "detect_head_and_shoulders",
             "3-peak reversal with neckline break"),
    BookRule("P107-RISING_WEDGE", 107, 6, "pattern", "Rising Wedge", "deterministic",
             "analysis/advanced_patterns.py", "detect_wedge",
             "Converging up trendlines, bearish (counter-intuitive)"),
    BookRule("P108-FALLING_WEDGE", 108, 6, "pattern", "Falling Wedge", "deterministic",
             "analysis/advanced_patterns.py", "detect_wedge",
             "Converging down trendlines, bullish"),
    BookRule("P110-BULL_FLAG", 110, 6, "pattern", "Bullish Flag", "deterministic",
             "analysis/advanced_patterns.py", "detect_flag",
             "Strong up→sideways consolidation→breakout up"),
    BookRule("P110-BEAR_FLAG", 110, 6, "pattern", "Bearish Flag", "deterministic",
             "analysis/advanced_patterns.py", "detect_flag",
             "Strong down→sideways consolidation→breakout down"),
    BookRule("P111-CUP_HANDLE", 111, 6, "pattern", "Cup with Handle", "needs_confirmation",
             "analysis/advanced_patterns.py", "detect_cup_and_handle",
             "U-shape cup + shallow handle, bullish continuation"),
    BookRule("P112-RECTANGLE", 112, 6, "pattern", "Rectangle", "deterministic",
             "analysis/advanced_patterns.py", "detect_rectangle",
             "Price between parallel horizontal lines",
             no_trade_condition=True),  # No breakout → NO_TRADE
    BookRule("P113-ASCENDING_TRIANGLE", 113, 6, "pattern", "Ascending Triangle", "deterministic",
             "analysis/advanced_patterns.py", "detect_triangle",
             "Flat resistance + rising support, bullish"),
    BookRule("P114-DESCENDING_TRIANGLE", 114, 6, "pattern", "Descending Triangle", "deterministic",
             "analysis/advanced_patterns.py", "detect_triangle",
             "Flat support + falling resistance, bearish"),
    BookRule("P115-SYMMETRICAL_TRIANGLE", 115, 6, "pattern", "Symmetrical Triangle", "deterministic",
             "analysis/advanced_patterns.py", "detect_triangle",
             "Converging trendlines, direction-neutral until breakout",
             no_trade_condition=True),  # No breakout → NO_TRADE

    # ── CHAPTER 7: TRADING STRATEGIES (Pages 119-130) ────────
    BookRule("P120-MOMENTUM_SCREEN", 120, 7, "strategy", "52-Week High Momentum", "deterministic",
             "analysis/advanced_patterns.py", "detect_momentum_screen",
             "Price within 10% of high = momentum candidate"),
    BookRule("P124-POSITION_SIZING", 124, 7, "risk", "1-2% Position Sizing", "deterministic",
             "risk/position_sizer.py", "PositionSizer.calculate",
             "Max 1-2% account risk per trade"),
    BookRule("P126-RISK_REWARD", 126, 7, "risk", "Risk-Reward Gate", "deterministic",
             "risk/risk_engine.py", "RiskEngine",
             "Reject trades <1:1, prefer ≥1:2"),

    # ── CHAPTER 8: RISK MANAGEMENT (Pages 131-141) ───────────
    BookRule("P134-STOP_LOSS", 134, 8, "risk", "Stop-Loss Discipline", "deterministic",
             "risk/risk_engine.py", "RiskEngine.calculate",
             "Always use stop-loss"),
    BookRule("P134-TRAILING_STOP", 134, 8, "risk", "Trailing Stop", "deterministic",
             "risk/risk_engine.py", "RiskEngine",
             "Adjust SL to lock in profits"),
    BookRule("P136-DIVERSIFICATION", 136, 8, "risk", "Correlation-Based Diversification", "deterministic",
             "risk/book_guardrails.py", "check_correlation_exposure",
             "Avoid stacking correlated FX pairs"),
    BookRule("P138-ANTI_REVENGE", 138, 8, "risk", "Anti-Revenge-Trading", "deterministic",
             "risk/book_guardrails.py", "check_anti_revenge_trading",
             "Block oversized trades after loss streak",
             no_trade_condition=True),
    BookRule("P138-COST_AWARE_EV", 138, 8, "risk", "Cost-Aware EV Gate", "deterministic",
             "risk/book_guardrails.py", "check_cost_aware_ev",
             "Net EV after costs must be > 0",
             no_trade_condition=True),

    # ── CONCLUSION (Pages 142-151) ───────────────────────────
    BookRule("P142-HYBRID_SYSTEM", 142, 9, "fundamental", "Hybrid TA+Fundamental", "design_principle",
             "agents/analysis_agent.py", "AnalysisAgent.run",
             "Combine TA with fundamental + sentiment analysis"),
]


# ═══════════════════════════════════════════════════════════════
# QUERY FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def get_all_rules() -> List[BookRule]:
    """Return all book rules."""
    return BOOK_RULES


def get_rules_by_chapter(chapter: int) -> List[BookRule]:
    """Return all rules from a specific chapter."""
    return [r for r in BOOK_RULES if r.chapter == chapter]


def get_rules_by_category(category: str) -> List[BookRule]:
    """Return all rules of a specific category.
    Categories: 'pattern', 'indicator', 'risk', 'trend', 'strategy', 'fundamental'
    """
    return [r for r in BOOK_RULES if r.category == category]


def get_no_trade_conditions() -> List[BookRule]:
    """Return all rules that define NO_TRADE states."""
    return [r for r in BOOK_RULES if r.no_trade_condition]


def get_deterministic_rules() -> List[BookRule]:
    """Return all deterministic (directly codeable) rules."""
    return [r for r in BOOK_RULES if r.rule_type == "deterministic"]


def get_rules_needing_confirmation() -> List[BookRule]:
    """Return rules that need additional confirmation logic."""
    return [r for r in BOOK_RULES if r.rule_type == "needs_confirmation"]


def get_design_principles() -> List[BookRule]:
    """Return architectural design principles."""
    return [r for r in BOOK_RULES if r.rule_type == "design_principle"]


def find_rule(rule_id: str) -> Optional[BookRule]:
    """Find a specific rule by ID."""
    for r in BOOK_RULES:
        if r.rule_id == rule_id:
            return r
    return None


def get_implementation_map() -> Dict[str, List[str]]:
    """Return {file_path: [function_names]} mapping."""
    impl_map: Dict[str, List[str]] = {}
    for r in BOOK_RULES:
        if r.implementation_file not in impl_map:
            impl_map[r.implementation_file] = []
        if r.implementation_function not in impl_map[r.implementation_file]:
            impl_map[r.implementation_file].append(r.implementation_function)
    return impl_map


def get_stats() -> dict:
    """Return summary statistics about the rule registry."""
    return {
        "total_rules":         len(BOOK_RULES),
        "deterministic":       len(get_deterministic_rules()),
        "needs_confirmation":  len(get_rules_needing_confirmation()),
        "design_principles":   len(get_design_principles()),
        "no_trade_conditions": len(get_no_trade_conditions()),
        "by_chapter":          {ch: len(get_rules_by_chapter(ch)) for ch in range(1, 10)},
        "by_category":         {cat: len(get_rules_by_category(cat))
                                for cat in ["pattern", "indicator", "risk", "trend",
                                            "strategy", "fundamental"]},
        "implementation_files": len(get_implementation_map()),
    }


# ═══════════════════════════════════════════════════════════════
# CLI ENTRY
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  BOOK RULES REGISTRY — Master Index")
    print("=" * 60)

    stats = get_stats()
    print(f"\nTotal Rules:           {stats['total_rules']}")
    print(f"Deterministic:         {stats['deterministic']}")
    print(f"Needs Confirmation:    {stats['needs_confirmation']}")
    print(f"Design Principles:     {stats['design_principles']}")
    print(f"No-Trade Conditions:   {stats['no_trade_conditions']}")
    print(f"Implementation Files:  {stats['implementation_files']}")

    print(f"\nBy Chapter:")
    for ch, count in stats["by_chapter"].items():
        if count > 0:
            print(f"  Chapter {ch}: {count} rules")

    print(f"\nBy Category:")
    for cat, count in stats["by_category"].items():
        if count > 0:
            print(f"  {cat}: {count} rules")

    print(f"\nNo-Trade Conditions ({len(get_no_trade_conditions())}):")
    for r in get_no_trade_conditions():
        print(f"  [{r.rule_id}] {r.name} (P{r.page})")

    print("\n" + "=" * 60)
