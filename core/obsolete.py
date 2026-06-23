"""
core/obsolete.py — Explicit registry of obsolete / orphan modules
==================================================================

The repository audit identified ~30 modules that exist on disk but are not
wired into the live runtime. Some are dead-by-design (superseded by a
newer implementation), some are dead-by-omission (the orchestrator stack
references sub-modules that were never created), and some are dead-by-
duplication (parallel implementations of the same class).

Per the project's "no silent orphan modules" rule, every such module is
listed here with:
  * the module path
  * a category (DEAD / SUPERSEDED / BROKEN / DUPLICATE / SMOKE_ONLY)
  * a one-line justification
  * the recommended action

Runtime code is expected to import `OBSOLETE_MODULES` and surface it in
health reports so operators can see exactly what is intentionally not
wired in.

This file is the single source of truth — do not duplicate this list
elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List


class ObsoleteCategory(str, Enum):
    DEAD = "dead"                  # zero importers, no replacement in flight
    SUPERSEDED = "superseded"      # replaced by a newer module
    BROKEN = "broken"              # imports something that does not exist
    DUPLICATE = "duplicate"        # byte-identical or near-identical twin
    SMOKE_ONLY = "smoke_only"      # only imported by tests/test_pipeline.py
    LEGACY_STUB = "legacy_stub"    # placeholder / 0-byte file


@dataclass(frozen=True)
class ObsoleteEntry:
    path: str
    category: ObsoleteCategory
    reason: str
    action: str


OBSOLETE_MODULES: List[ObsoleteEntry] = [
    # ── agents/ ──────────────────────────────────────────────────────
    ObsoleteEntry(
        "agents/chart_agent.py",
        ObsoleteCategory.SUPERSEDED,
        "Standalone Playwright S/R drawer; superseded by computer_use/chart_drawer.py + coordinate_mapper.py.",
        "Delete or move to legacy/. Wired runtime uses computer_use/ stack.",
    ),

    # ── ai/ ──────────────────────────────────────────────────────────
    ObsoleteEntry(
        "ai/automated_retraining.py",
        ObsoleteCategory.DEAD,
        "Zero importers; no CLI entry point. Depends on ai/model_versioning which has an mlflow init bug.",
        "Kept on disk; wired via core/runtime.py boot_ai() with safe try/except. Marked legacy.",
    ),
    ObsoleteEntry(
        "ai/model_versioning.py",
        ObsoleteCategory.SMOKE_ONLY,
        "MLflow init runs at import time even when mlflow is absent → NameError. Only consumed by automated_retraining + core/monitoring_system.",
        "Patched: mlflow calls now guarded behind MLFLOW_AVAILABLE flag.",
    ),

    # ── analysis/ — the Day 61–64 SMC/Liquidity/Currency cluster ─────
    ObsoleteEntry(
        "analysis/smart_money.py",
        ObsoleteCategory.DEAD,
        "Day-61 master SMC orchestrator never wired into agents/analysis_agent.py (still uses Day-44 smc_engine).",
        "Marked legacy. Future: replace smc_engine with smart_money in AnalysisAgent.run().",
    ),
    ObsoleteEntry(
        "analysis/structure.py",
        ObsoleteCategory.DEAD,
        "Only consumer is dead analysis/smart_money.py.",
        "Marked legacy (transitively dead).",
    ),
    ObsoleteEntry(
        "analysis/liquidity.py",
        ObsoleteCategory.DEAD,
        "Class-name collision with analysis/liquidity_engine.py. Only consumer is dead smart_money.py.",
        "Marked legacy. Rename to liquidity_intel.py if revived.",
    ),
    ObsoleteEntry(
        "analysis/liquidity_engine.py",
        ObsoleteCategory.DEAD,
        "Day-62 liquidity orchestrator never wired into AnalysisAgent.",
        "Marked legacy. Wire via AnalysisAgent when adopting Day-62 pipeline.",
    ),
    ObsoleteEntry(
        "analysis/liquidity_zones.py",
        ObsoleteCategory.DEAD,
        "Only consumer is dead liquidity_engine.py.",
        "Marked legacy (transitively dead).",
    ),
    ObsoleteEntry(
        "analysis/stop_hunt_detector.py",
        ObsoleteCategory.DEAD,
        "Only consumer is dead liquidity_engine.py.",
        "Marked legacy (transitively dead).",
    ),
    ObsoleteEntry(
        "analysis/session_analysis.py",
        ObsoleteCategory.DEAD,
        "London-manipulation detector; only consumer is dead liquidity_engine.py.",
        "Marked legacy (transitively dead).",
    ),
    ObsoleteEntry(
        "analysis/currency_strength.py",
        ObsoleteCategory.DEAD,
        "Day-64 currency-strength orchestrator never wired into AnalysisAgent.",
        "Marked legacy. Wire via AnalysisAgent when adopting Day-64 pipeline.",
    ),
    ObsoleteEntry(
        "analysis/currency_ranker.py",
        ObsoleteCategory.DEAD,
        "Only consumer is dead currency_strength.py.",
        "Marked legacy (transitively dead).",
    ),
    ObsoleteEntry(
        "analysis/strength_calculator.py",
        ObsoleteCategory.DEAD,
        "Only consumer is dead currency_strength.py.",
        "Marked legacy (transitively dead).",
    ),
    ObsoleteEntry(
        "analysis/mtf_analyzer.py",
        ObsoleteCategory.LEGACY_STUB,
        "Only _detect_bos/_detect_choch/_detect_liquidity_sweep helpers are used by smc_engine. Public analyze() pipeline (~700 LOC) never invoked.",
        "Kept (helpers are live). Public analyze() marked dormant.",
    ),
    ObsoleteEntry(
        "analysis/database/__init__.py",
        ObsoleteCategory.LEGACY_STUB,
        "Empty placeholder subpackage; no concrete DB modules.",
        "Kept as marker; will populate if analysis ever needs its own DB.",
    ),

    # ── broker/ — the dead MT5 data cluster + a few smoke-only guards
    ObsoleteEntry(
        "broker/market_data_manager.py",
        ObsoleteCategory.DEAD,
        "Zero importers. Was meant to be the single MT5 data entry point.",
        "Marked legacy. If reviving MT5 data path, wire into server/signal_pipeline.py.",
    ),
    ObsoleteEntry(
        "broker/mt5_data.py",
        ObsoleteCategory.DEAD,
        "Only consumers are dead broker/market_data_manager.py + broker/symbol_manager.py.",
        "Marked legacy (transitively dead).",
    ),
    ObsoleteEntry(
        "broker/symbol_manager.py",
        ObsoleteCategory.DEAD,
        "Only consumer is dead broker/market_data_manager.py.",
        "Marked legacy (transitively dead).",
    ),
    ObsoleteEntry(
        "broker/data_validator.py",
        ObsoleteCategory.DEAD,
        "Broker-side validator; only consumer is dead broker/market_data_manager.py. (data/validator.py is the live one.)",
        "Marked legacy (transitively dead).",
    ),
    ObsoleteEntry(
        "broker/position_manager.py",
        ObsoleteCategory.DEAD,
        "523 LOC of active trade-management logic; zero importers. Also has latent add_lesson() bug.",
        "Marked legacy. Future: wire into hybrid/flow_controller.py if reviving.",
    ),
    ObsoleteEntry(
        "broker/safety_guard.py",
        ObsoleteCategory.SMOKE_ONLY,
        "Only imported by tests/test_pipeline.py. Production safety gate is in core/trader.py (TradePermission + CorrelationFilter).",
        "Kept for tests. Marked smoke-only.",
    ),
    ObsoleteEntry(
        "broker/spread_monitor.py",
        ObsoleteCategory.SMOKE_ONLY,
        "Only imported by tests/test_pipeline.py.",
        "Kept for tests. Marked smoke-only.",
    ),
    ObsoleteEntry(
        "broker/health_monitor.py",
        ObsoleteCategory.SMOKE_ONLY,
        "Constructed by execution_router but check_once()/run_loop() never called. Canonical replacement is core/health_monitor.py.",
        "Kept; MT5-mode callbacks still wired. Marked smoke-only.",
    ),

    # ── risk/ ────────────────────────────────────────────────────────
    ObsoleteEntry(
        "risk/risk_simulator.py",
        ObsoleteCategory.DEAD,
        "RiskScenarioSimulator never imported anywhere.",
        "Marked legacy. Functionality overlaps with risk/monte_carlo.py.",
    ),
    ObsoleteEntry(
        "risk/portfolio_manager.py",
        ObsoleteCategory.SUPERSEDED,
        "Pre-Day-58 portfolio prototype; superseded by risk/capital_manager.py + risk/exposure_manager.py. Module-level singleton runs at import time.",
        "Marked legacy. Do not import.",
    ),

    # ── scanner/ ─────────────────────────────────────────────────────
    ObsoleteEntry(
        "scanner/scanner.py",
        ObsoleteCategory.DUPLICATE,
        "Byte-identical duplicate of scanner/config.py minus header. Zero importers.",
        "Marked legacy. Delete on next cleanup pass.",
    ),

    # ── fundamental/ ─────────────────────────────────────────────────
    ObsoleteEntry(
        "fundamental/fundamental_sentiment.py",
        ObsoleteCategory.DEAD,
        "FundamentalSentimentScore never imported. DB methods (get_currency_fundamental_bias) exist for its benefit only.",
        "Marked legacy. Wire via AnalysisAgent if reviving fundamental scoring.",
    ),

    # ── memory/ ──────────────────────────────────────────────────────
    ObsoleteEntry(
        "memory/trade_context.py",
        ObsoleteCategory.LEGACY_STUB,
        "0-byte placeholder.",
        "Kept as marker; populate if memory needs a typed trade-context dataclass.",
    ),
    ObsoleteEntry(
        "memory/confidence_calibrator.py",
        ObsoleteCategory.SUPERSEDED,
        "Superseded by hybrid/confidence_calibrator.py (also currently dead). Class-name collision.",
        "Marked legacy. Pick one canonical calibrator on next cleanup.",
    ),

    # ── learning/ ────────────────────────────────────────────────────
    ObsoleteEntry(
        "learning/weekly_review.py",
        ObsoleteCategory.DEAD,
        "run_weekly_review() never invoked.",
        "Wired via core/runtime.py boot_learning() — invoked on Sundays by DailyRoutineManager.",
    ),
    ObsoleteEntry(
        "learning/memory_integration.py",
        ObsoleteCategory.DEAD,
        "MemoryIntegration never instantiated.",
        "Wired via core/runtime.py boot_learning() and exposed to AITrader through registry.",
    ),

    # ── automation/ — entire folder dead, now wired via runtime ─────
    ObsoleteEntry(
        "automation/error_handler.py",
        ObsoleteCategory.DEAD,
        "ErrorHandler never instantiated. Canonical replacement: core/event_bus + core/runtime_metrics.record_error.",
        "Wired via core/runtime.py boot_automation().",
    ),
    ObsoleteEntry(
        "automation/runtime_metrics.py",
        ObsoleteCategory.SUPERSEDED,
        "Superseded by core/runtime_metrics.py (canonical).",
        "Kept for backward compat; core/runtime_metrics is the live one.",
    ),
    ObsoleteEntry(
        "automation/daily_review.py",
        ObsoleteCategory.DEAD,
        "DailyReview never invoked.",
        "Wired via core/runtime.py boot_automation() + DailyRoutineManager.",
    ),
    ObsoleteEntry(
        "automation/system_health.py",
        ObsoleteCategory.SUPERSEDED,
        "Superseded by core/health_monitor.py (canonical).",
        "Kept for backward compat; core/health_monitor is the live one.",
    ),

    # ── orchestrator/ — broken + dead cluster ────────────────────────
    ObsoleteEntry(
        "orchestrator/trading_orchestrator.py",
        ObsoleteCategory.BROKEN,
        "Imports 4 missing sub-modules: safety_controller, self_healing, mode_manager, decision_journal.",
        "Patched: 4 stub modules created. TradingOrchestrator now importable and wired via core/runtime.py boot_orchestrator().",
    ),
    ObsoleteEntry(
        "orchestrator/safety_controller.py",
        ObsoleteCategory.LEGACY_STUB,
        "Created as minimal stub to unblock trading_orchestrator import.",
        "Live stub — extends SafetyController if logic is added.",
    ),
    ObsoleteEntry(
        "orchestrator/self_healing.py",
        ObsoleteCategory.LEGACY_STUB,
        "Created as minimal stub to unblock trading_orchestrator import.",
        "Live stub — extends SelfHealingSystem if logic is added.",
    ),
    ObsoleteEntry(
        "orchestrator/mode_manager.py",
        ObsoleteCategory.LEGACY_STUB,
        "Created as minimal stub to unblock trading_orchestrator import.",
        "Live stub — extends ModeManager if logic is added.",
    ),
    ObsoleteEntry(
        "orchestrator/decision_journal.py",
        ObsoleteCategory.LEGACY_STUB,
        "Created as minimal stub to unblock trading_orchestrator import.",
        "Live stub — extends DecisionJournal if logic is added.",
    ),

    # ── hybrid/ — entire folder dead ─────────────────────────────────
    ObsoleteEntry(
        "hybrid/flow_controller.py",
        ObsoleteCategory.DEAD,
        "FlowController never instantiated. Day-49 quant+vision pipeline.",
        "Wired via core/runtime.py boot_hybrid() (constructed, not actively driven).",
    ),
    ObsoleteEntry(
        "hybrid/decision_validator.py",
        ObsoleteCategory.DEAD,
        "Only consumer is dead flow_controller.py.",
        "Marked legacy (transitively dead via flow_controller).",
    ),
    ObsoleteEntry(
        "hybrid/execution_router.py",
        ObsoleteCategory.DUPLICATE,
        "Parallel reimplementation of execution/execution_router.py. Class-name collision.",
        "Marked legacy. Canonical router is execution/execution_router.py.",
    ),
    ObsoleteEntry(
        "hybrid/confidence_calibrator.py",
        ObsoleteCategory.DUPLICATE,
        "Parallel reimplementation of memory/confidence_calibrator.py. Class-name collision.",
        "Marked legacy. Canonical calibrator TBD on next cleanup.",
    ),

    # ── analytics/ ───────────────────────────────────────────────────
    ObsoleteEntry(
        "analytics/performance_report.py",
        ObsoleteCategory.DEAD,
        "PerformanceReport class never instantiated. OptimizationSuggester not even re-exported.",
        "Wired via core/runtime.py boot_analytics(). Invoked by weekly review.",
    ),

    # ── core/ ────────────────────────────────────────────────────────
    ObsoleteEntry(
        "core/monitoring_system.py",
        ObsoleteCategory.SUPERSEDED,
        "Never imported. Canonical replacement: core/health_monitor.py.",
        "Kept for backward compat; core/health_monitor is the live one.",
    ),

    # ── computer_use/ — broken imports ───────────────────────────────
    ObsoleteEntry(
        "computer_use/browser_controller.py",
        ObsoleteCategory.BROKEN,
        "Referenced by tradingview_agent.py and computer_agent.py but file does not exist (the actual class BrowserController lives in browser_control.py).",
        "Documented as broken. computer_agent + tradingview_agent + run_day46_demo are excluded from runtime wiring.",
    ),
    ObsoleteEntry(
        "computer_use/tradingview_agent.py",
        ObsoleteCategory.BROKEN,
        "Imports missing browser_controller module.",
        "Excluded from runtime. Fix on dedicated computer_use revival pass.",
    ),
    ObsoleteEntry(
        "computer_use/computer_agent.py",
        ObsoleteCategory.BROKEN,
        "Imports missing browser_controller module AND missing BrowserAgent class.",
        "Excluded from runtime. Fix on dedicated computer_use revival pass.",
    ),
    ObsoleteEntry(
        "computer_use/run_day46_demo.py",
        ObsoleteCategory.BROKEN,
        "Transitively broken via tradingview_agent.",
        "Excluded from runtime. Demo script only.",
    ),

    # ── data/ ────────────────────────────────────────────────────────
    ObsoleteEntry(
        "data/verify_data_coverage.py",
        ObsoleteCategory.SMOKE_ONLY,
        "CLI-only verification script with stale hardcoded 2026-06-21 target date.",
        "Kept as a CLI utility. Not part of runtime.",
    ),

    # ── duplicate folder ─────────────────────────────────────────────
    ObsoleteEntry(
        "risk - Copy/",
        ObsoleteCategory.DUPLICATE,
        "Byte-for-byte duplicate of risk/ folder. Its autonomous_risk.py even imports from the real risk/ package, confirming it's stale shadow code.",
        "Do not import. Delete on next cleanup pass.",
    ),
]


def obsolete_index() -> Dict[str, ObsoleteEntry]:
    """Return a {path: entry} map for quick lookup."""
    return {e.path: e for e in OBSOLETE_MODULES}


def obsolete_summary() -> Dict[str, int]:
    """Counts per category — useful for the final report."""
    counts: Dict[str, int] = {}
    for entry in OBSOLETE_MODULES:
        counts[entry.category.value] = counts.get(entry.category.value, 0) + 1
    counts["total"] = len(OBSOLETE_MODULES)
    return counts


def is_obsolete(path: str) -> bool:
    return path in obsolete_index()
