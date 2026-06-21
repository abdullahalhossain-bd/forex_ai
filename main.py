#!/usr/bin/env python3
# main.py — Autonomous AI Trading System Entry Point
# ============================================================
# This is the production entry point for the AI Trading System.
# Run: python main.py
# 
# The system will:
#   1. Load and validate configuration
#   2. Initialize database and memory systems
#   3. Connect market data sources
#   4. Initialize Autonomous Research Agent (Day 57)
#   5. Initialize Autonomous Risk Manager (Day 58)
#   6. Start the autonomous trading loop
#   7. Run analysis, risk validation, and execution pipeline
#   8. Monitor positions and save trade memory
#   9. Run research cycles (auto-discover strategies)
#  10. Run Monte Carlo simulation & capital reports
# ============================================================

import os
import sys
import time
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


def _print_banner() -> None:
    """Display the system startup banner."""
    bar = "=" * 55
    print()
    print(f"  {bar}")
    print("    AUTONOMOUS AI TRADER  v4.0")
    print("    Research Agent (Day 57) + Risk Manager (Day 58)")
    print(f"  {bar}")
    print(f"    Started : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print()


def _print_status(name: str, status: str, ok: bool = True) -> None:
    """Print a single status check line."""
    icon = "OK" if ok else "FAIL"
    print(f"    [{icon}] {name:<35} {status}")


def _health_check(config) -> list[str]:
    """Run pre-flight health checks. Returns list of warnings."""
    warnings = []
    
    # 1. Config validation
    _print_status("Configuration", "Loaded", ok=True)
    
    # 2. Database
    try:
        from database.db import TraderDB
        db = TraderDB()
        stats = db.get_overall_stats(starting_balance=10000)
        _print_status("Database", f"Connected ({stats.get('total', 0)} trades)")
    except Exception as e:
        _print_status("Database", f"Error: {e}", ok=False)
        warnings.append(f"Database: {e}")
    
    # 3. Memory system
    try:
        from memory.trade_memory import TradeMemory
        tm = TradeMemory(seed_rules=False)
        ctx = tm.get_context_for_ai("EURUSD")
        _print_status("Memory System", f"Loaded ({ctx.get('total_trades', 0)} decisions)")
    except Exception as e:
        _print_status("Memory System", f"Error: {e}", ok=False)
        warnings.append(f"Memory: {e}")
    
    # 4. Risk engine
    try:
        from risk.risk_engine import RiskEngine
        re = RiskEngine(balance=10000, symbol="EURUSD")
        _print_status("Risk Engine", "Active")
    except Exception as e:
        _print_status("Risk Engine", f"Error: {e}", ok=False)
        warnings.append(f"Risk: {e}")
    
    # 5. Circuit breaker
    try:
        from risk.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(balance=10000)
        status = cb.get_status()
        _print_status("Circuit Breaker", f"Mode: {status['mode']}")
    except Exception as e:
        _print_status("Circuit Breaker", f"Error: {e}", ok=False)
        warnings.append(f"CircuitBreaker: {e}")
    
    # 6. Analysis modules
    try:
        from agents.analysis_agent import AnalysisAgent
        aa = AnalysisAgent()
        _print_status("AI Analysis Agent", "Loaded (12-step pipeline)")
    except Exception as e:
        _print_status("AI Analysis Agent", f"Error: {e}", ok=False)
        warnings.append(f"Analysis: {e}")
    
    # 7. Decision agent
    try:
        from agents.decision_agent import DecisionAgent
        da = DecisionAgent()
        _print_status("Decision Agent", "Loaded (weighted voting)")
    except Exception as e:
        _print_status("Decision Agent", f"Error: {e}", ok=False)
        warnings.append(f"Decision: {e}")
    
    # 8. Learning system
    try:
        from learning.confidence_engine import ConfidenceEngine
        ce = ConfidenceEngine()
        _print_status("Learning Engine", "Active (confidence + optimizer)")
    except Exception as e:
        _print_status("Learning Engine", f"Error: {e}", ok=False)
        warnings.append(f"Learning: {e}")
    
    # 9. Scanner
    try:
        from scanner.market_scanner import MarketScanner
        _print_status("Market Scanner", "Available")
    except Exception as e:
        _print_status("Market Scanner", f"Unavailable: {e}", ok=False)
        warnings.append(f"Scanner: {e}")
    
    # 10. MT5 (only if mt5_demo mode)
    mode = os.getenv("EXECUTION_MODE", "paper").lower()
    if mode == "mt5_demo":
        try:
            from broker.mt5_connection import MT5_AVAILABLE
            if MT5_AVAILABLE:
                _print_status("MT5 Broker", "Package available (connect on start)")
            else:
                _print_status("MT5 Broker", "Package NOT installed", ok=False)
                warnings.append("MT5: MetaTrader5 package not installed")
        except Exception as e:
            _print_status("MT5 Broker", f"Error: {e}", ok=False)
    else:
        _print_status("MT5 Broker", "Skipped (paper mode)")
    
    # 11. Paper trader
    try:
        from execution.paper_trader import PaperTrader
        pt = PaperTrader(starting_balance=10000)
        _print_status("Paper Trader", f"Active (balance: ${pt.balance:,.2f})")
    except Exception as e:
        _print_status("Paper Trader", f"Error: {e}", ok=False)
        warnings.append(f"PaperTrader: {e}")
    
    # 12. Research Agent (Day 57)
    try:
        from research.research_agent import ResearchAgent
        ra = ResearchAgent(enable_auto_research=True)
        ra_stats = ra.get_stats()
        _print_status("Research Agent",
            f"Active (cycles: {ra_stats.get('cycle_count', 0)}, "
            f"experiments: {ra_stats.get('total_experiments', 0)})")
    except Exception as e:
        _print_status("Research Agent", f"Error: {e}", ok=False)
        warnings.append(f"ResearchAgent: {e}")
    
    # 13. Autonomous Risk Manager (Day 58)
    try:
        from risk.autonomous_risk import AutonomousRiskManager
        arm = AutonomousRiskManager(balance=10000)
        arm_stats = arm.get_stats()
        _print_status("Autonomous Risk Mgr",
            f"Active (mode: {arm_stats.get('current_mode', 'NORMAL')}, "
            f"DD: {arm_stats.get('drawdown_pct', 0):.1f}%)")
    except Exception as e:
        _print_status("Autonomous Risk Mgr", f"Error: {e}", ok=False)
        warnings.append(f"AutonomousRiskManager: {e}")
    
    return warnings


def main():
    """Main entry point for the Autonomous AI Trading System."""
    
    # ── Step 0: Banner ────────────────────────────────────────
    _print_banner()
    
    # ── Step 1: Load Configuration ────────────────────────────
    print("  [1/8] Loading configuration...")
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
    print(f"         Mode: {execution_mode.upper()}")
    print(f"         Symbols: {SYMBOLS}")
    print(f"         Timeframe: {DEFAULT_TIMEFRAME}")
    print()
    
    # ── Step 2: Health Check ──────────────────────────────────
    print("  [2/8] Running health checks...")
    warnings = _health_check(None)
    print()
    
    if warnings:
        print(f"  WARNING: {len(warnings)} issue(s) detected:")
        for w in warnings:
            print(f"    - {w}")
        print()
    
    # ── Step 3: System Status ─────────────────────────────────
    print("  [3/8] Initializing trading system...")
    
    use_scanner = _env_bool("USE_SCANNER", execution_mode == "mt5_demo")
    approval_mode = _env_int("APPROVAL_MODE", 3)
    enable_telegram = os.getenv("ENABLE_TELEGRAM", "true").lower() != "false"
    enable_research = _env_bool("ENABLE_RESEARCH", True)
    
    mode_names = {1: "Analysis Only", 2: "Supervised", 3: "Autonomous"}
    print(f"         Approval Mode: {mode_names.get(approval_mode, 'Unknown')} (Level {approval_mode})")
    print(f"         Scanner: {'ON' if use_scanner else 'OFF'}")
    print(f"         Telegram: {'ON' if enable_telegram else 'OFF'}")
    print(f"         Research: {'ON' if enable_research else 'OFF'}")
    print()
    
    # ── Step 4: Build & Start ─────────────────────────────────
    print("  [4/8] Starting autonomous trading engine...")
    
    from core.trading_engine import TradingEngine
    
    system = TradingEngine(
        symbols=SYMBOLS,
        timeframe=DEFAULT_TIMEFRAME,
        balance=_env_float("PAPER_BALANCE", PAPER_BALANCE),
        poll_seconds=_env_int("LOOP_INTERVAL_SEC", LOOP_INTERVAL_SEC),
        backup_interval_minutes=_env_int("BACKUP_INTERVAL_MIN", BACKUP_INTERVAL_MIN),
        cooldown_minutes=_env_int("RECOVERY_COOLDOWN_MIN", RECOVERY_COOLDOWN_MIN),
        max_cycles=None,
        enable_telegram=enable_telegram,
        use_scanner=use_scanner,
        execution_mode=execution_mode,
        approval_mode=approval_mode,
    )
    
    print()
    
    # ── Step 5: Initialize Research Agent (Day 57) ──────────
    print("  [5/8] Initializing Research Agent (Day 57)...")
    if enable_research:
        try:
            from research.research_agent import ResearchAgent
            research_agent = ResearchAgent(enable_auto_research=True)
            ra_stats = research_agent.get_stats()
            print(f"         Research cycles: {ra_stats.get('cycle_count', 0)}")
            print(f"         Active strategies: {ra_stats.get('active_strategies', 0)}")
            print(f"         Total experiments: {ra_stats.get('total_experiments', 0)}")
            print(f"         Hypotheses confirmed: {ra_stats.get('hypothesis_stats', {}).get('confirmed', 0)}")
        except Exception as e:
            print(f"         Research Agent: Disabled ({e})")
            research_agent = None
    else:
        research_agent = None
        print("         Research Agent: Disabled by config")
    print()
    
    # ── Step 6: Initialize Risk Manager (Day 58) ──────────
    print("  [6/8] Initializing Autonomous Risk Manager (Day 58)...")
    enable_risk_manager = _env_bool("ENABLE_RISK_MANAGER", True)
    if enable_risk_manager:
        try:
            from risk.autonomous_risk import AutonomousRiskManager
            risk_manager = AutonomousRiskManager(
                balance=_env_float("PAPER_BALANCE", PAPER_BALANCE),
            )
            rm_stats = risk_manager.get_stats()
            print(f"         Risk Mode: {rm_stats['current_mode']}")
            print(f"         Kelly Fraction: 25% (Fractional)")
            print(f"         Drawdown: {rm_stats['drawdown_pct']:.1f}%")
            print(f"         Exposure: {rm_stats['exposure_pct']:.1f}%")
        except Exception as e:
            print(f"         Risk Manager: Disabled ({e})")
            risk_manager = None
    else:
        risk_manager = None
        print("         Risk Manager: Disabled by config")
    print()
    
    # ── Step 7: Run ───────────────────────────────────────────
    print("  [7/8] Entering autonomous trading loop...")
    print("         Press Ctrl+C to stop safely.")
    print()
    
    try:
        report = system.run()
        
        # ── Run Research Cycle if enabled ──────────────────────
        if research_agent and enable_research:
            print()
            print("  [Research] Running post-trading research cycle...")
            try:
                research_report = research_agent.run_research_cycle(n_experiments=2)
                print(f"  [Research] Cycle {research_report.get('cycle_id', '?')} complete:")
                print(f"    Experiments: {len(research_report.get('experiments', []))}")
                print(f"    Approved: {len(research_report.get('strategies_approved', []))}")
                print(f"    Rejected: {len(research_report.get('strategies_rejected', []))}")
                research_agent.print_status()
            except Exception as re_err:
                print(f"  [Research] Cycle failed: {re_err}")
        
        # ── Capital Report (Day 58) ─────────────────────────────
        if risk_manager and enable_risk_manager:
            print()
            print("  [Risk Manager] Generating Capital Report...")
            try:
                capital_report = risk_manager.generate_capital_report()
                risk_manager.print_status()

                # Monte Carlo simulation
                print("  [Risk Manager] Running Monte Carlo Simulation...")
                mc_result = risk_manager.run_risk_simulation(
                    n_simulations=5000, n_trades=100
                )
                from risk.monte_carlo import MonteCarloEngine
                mc = MonteCarloEngine()
                mc.print_simulation_result(mc_result)

                # Risk scenario simulation
                print("  [Risk Manager] Running Risk Scenarios...")
                from risk.risk_simulator import RiskScenarioSimulator
                sim = RiskScenarioSimulator(
                    balance=risk_manager.balance,
                    risk_pct=1.0,
                )
                sim.print_all_scenarios()

            except Exception as rm_err:
                print(f"  [Risk Manager] Report failed: {rm_err}")
        
        # ── Final Report ──────────────────────────────────────
        print()
        print("=" * 55)
        print("  AI TRADING SYSTEM v4.0 — FINAL REPORT")
        print("  (Day 57 Research + Day 58 Risk Manager)")
        print("=" * 55)
        print(f"  Mode       : {report['mode']}")
        print(f"  Scanner    : {report['scanner']}")
        print(f"  Pairs      : {report.get('pairs', [])}")
        summary = report.get('summary', {})
        print(f"  Trades     : {summary.get('trades', 0)}")
        print(f"  Wins       : {summary.get('wins', 0)}")
        print(f"  Losses     : {summary.get('losses', 0)}")
        print(f"  Win Rate   : {summary.get('win_rate', 0):.1f}%")
        print(f"  Profit     : ${summary.get('profit', 0):,.2f}")
        print(f"  Balance    : ${summary.get('balance', 0):,.2f}")
        print(f"  Avg R:R    : 1:{summary.get('average_rr', 0)}")
        print(f"  Best Setup : {summary.get('best_setup', 'N/A')}")
        print(f"  Biggest Mistake: {summary.get('biggest_mistake', 'N/A')}")
        if risk_manager:
            rm_s = risk_manager.get_stats()
            print(f"  Risk Mode  : {rm_s['current_mode']}")
            print(f"  Drawdown   : {rm_s['drawdown_pct']:.1f}%")
        print("=" * 55)
        print()
        
    except KeyboardInterrupt:
        print("\n\n  System stopped by user (Ctrl+C).")
        print("  State has been backed up automatically.")
        print()
    except Exception as e:
        print(f"\n\n  FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
