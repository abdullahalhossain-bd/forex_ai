#!/usr/bin/env python3
# main.py — Autonomous AI Trading System Entry Point
# ============================================================
# Day 60 — Trading Orchestrator (Central Nervous System)
#
# This is the production entry point for the AI Trading System.
# Run: python main.py
#
# The TradingOrchestrator coordinates ALL modules:
#   Market Intelligence → Research Intelligence → Decision Intelligence
#   → Risk Intelligence → Execution Intelligence → Memory Intelligence
#   → Learning Intelligence → Research Loop
#
# Systems initialized:
#   1. Agent Communication Bus (decoupled messaging)
#   2. System State Manager (global state tracking)
#   3. Safety Controller (emergency stop / circuit breaker)
#   4. Self-Healing System (auto-recovery from failures)
#   5. Human Override System (STOP ALL / CLOSE ALL / PAUSE / RESUME)
#   6. Mode Manager (Research / Paper / Demo / Live)
#   7. Decision Journal (every decision saved for AI learning)
#   8. Audit Trail (complete compliance trail)
#   9. Task Scheduler (morning/evening/sunday routines)
#   10. Market Agent, Analysis Agent, Decision Agent, Risk Agent
#   11. Learning Agent, Paper Trader, Research Agent, Risk Manager
# ============================================================

import os
import sys
from pathlib import Path
from datetime import datetime, timezone

# ── Ensure project root is in sys.path ───────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() == "true"


def main():
    """Main entry point — launches the Day 60 Trading Orchestrator."""

    # ── Load Configuration ────────────────────────────────────
    from config import (
        BACKUP_INTERVAL_MIN,
        DEFAULT_TIMEFRAME,
        EXECUTION_MODE,
        LOOP_INTERVAL_SEC,
        PAPER_BALANCE,
        RECOVERY_COOLDOWN_MIN,
        SYMBOLS,
    )

    execution_mode = EXECUTION_MODE
    enable_telegram = os.getenv("ENABLE_TELEGRAM", "true").lower() != "false"
    enable_research = _env_bool("ENABLE_RESEARCH", True)
    enable_risk_manager = _env_bool("ENABLE_RISK_MANAGER", True)
    use_scanner = _env_bool("USE_SCANNER", execution_mode == "mt5_demo")
    approval_mode = _env_int("APPROVAL_MODE", 3)
    max_cycles = None  # None = run forever

    # ── Create and Start Orchestrator ─────────────────────────
    from orchestrator.trading_orchestrator import TradingOrchestrator

    orchestrator = TradingOrchestrator(
        symbols=SYMBOLS,
        timeframe=DEFAULT_TIMEFRAME,
        balance=_env_float("PAPER_BALANCE", PAPER_BALANCE),
        poll_seconds=_env_int("LOOP_INTERVAL_SEC", LOOP_INTERVAL_SEC),
        execution_mode=execution_mode,
        approval_mode=approval_mode,
        enable_telegram=enable_telegram,
        enable_research=enable_research,
        enable_risk_manager=enable_risk_manager,
        use_scanner=use_scanner,
    )

    # ── Run ────────────────────────────────────────────────────
    try:
        report = orchestrator.run(max_cycles=max_cycles)

        # ── Final Report ──────────────────────────────────────
        print()
        bar = "=" * 55
        print(f"  {bar}")
        print("  AI TRADING SYSTEM v5.0 — FINAL REPORT")
        print("  Day 60 — Trading Orchestrator")
        print(f"  {bar}")

        summary = report.get("summary", {})
        state = orchestrator.state_mgr.state

        print(f"  Mode           : {report.get('mode', '?').upper()}")
        print(f"  Pairs          : {report.get('pairs', [])}")
        print(f"  Cycles         : {summary.get('cycles', 0)}")
        print(f"  Trades         : {summary.get('trades', 0)}")
        print(f"  Wins / Losses  : {summary.get('wins', 0)} / {summary.get('losses', 0)}")
        print(f"  Win Rate       : {summary.get('win_rate', 0):.1f}%")
        print(f"  Balance        : ${summary.get('balance', 0):,.2f}")
        print(f"  Risk Mode      : {state.risk_mode}")
        print(f"  System Health  : {state.system_health}")

        # Orchestrator-specific stats
        bus_stats = orchestrator.bus.get_stats()
        journal_stats = orchestrator.journal.get_stats()
        audit_stats = orchestrator.audit.get_stats()
        safety_status = orchestrator.safety.get_status()

        print(f"  Bus Messages   : {bus_stats['total_messages']}")
        print(f"  Decisions Logged: {journal_stats['total_entries']}")
        print(f"  Audit Events   : {audit_stats['total_events']}")
        print(f"  Safety Trips   : {len(safety_status['tripwires_tripped'])}")
        print(f"  Self-Heals     : {orchestrator.self_healing._total_heals}")
        print(f"  Scheduler Tasks: {orchestrator.scheduler.get_stats()['total_executions']}")
        print(f"  Journal Win Rate: {journal_stats.get('win_rate', 0)}%")

        print(f"  {bar}")
        print()

        # ── Research Report (if enabled) ───────────────────────
        if orchestrator._research_agent:
            print("  [Research] Running final research cycle...")
            try:
                research_report = orchestrator._research_agent.run_research_cycle(n_experiments=2)
                print(f"  [Research] Cycle complete:")
                print(f"    Experiments: {len(research_report.get('experiments', []))}")
                print(f"    Approved: {len(research_report.get('strategies_approved', []))}")
                print(f"    Rejected: {len(research_report.get('strategies_rejected', []))}")
            except Exception as re_err:
                print(f"  [Research] Cycle failed: {re_err}")

        # ── Capital Report (Day 58) ───────────────────────────
        if orchestrator._risk_manager:
            print()
            print("  [Risk Manager] Generating Capital Report...")
            try:
                capital_report = orchestrator._risk_manager.generate_capital_report()
                orchestrator._risk_manager.print_status()

                # Monte Carlo simulation
                print("  [Risk Manager] Running Monte Carlo Simulation...")
                mc_result = orchestrator._risk_manager.run_risk_simulation(
                    n_simulations=5000, n_trades=100
                )
                from risk.monte_carlo import MonteCarloEngine
                mc = MonteCarloEngine()
                mc.print_simulation_result(mc_result)

            except Exception as rm_err:
                print(f"  [Risk Manager] Report failed: {rm_err}")

        print()

    except KeyboardInterrupt:
        print("\n\n  System stopped by user (Ctrl+C).")
        print("  All state has been backed up automatically.")
        print()

    except Exception as e:
        print(f"\n\n  FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
