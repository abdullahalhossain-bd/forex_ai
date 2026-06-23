#!/usr/bin/env python3
"""
=====================================================
FOREX AI AUTONOMOUS TRADING SYSTEM
=====================================================
Main Entry Point — Central Controller (Day 37+ Runtime-Unified version)

This version of main.py replaces the ad-hoc ForexAISystem class with a
composition root that drives the new LifecycleManager + ServiceRegistry
infrastructure in core/runtime.py. Every runtime module is now brought up
in a strict phase order through a single boot path, and torn down in
reverse on shutdown.

Pipeline (single source of truth — see core/runtime.py:register_default_phases):

    System Bootstrap (config, paths, event bus, metrics, health monitor)
    → Persistence (DB, TradeMemory, LearningEngine, KnowledgeStore)
    → Data (Fetcher, Validator, Indicators, AutomatedUpdater)
    → Market (Scanner, CorrelationFilter, OpportunityRanker, MT5Connection)
    → Research (ResearchAgent, HypothesisEngine, ExperimentRunner, Reports)
    → Fundamental (NewsFilter, FundamentalSentimentScore)
    → Analysis (IntermarketEngine, SessionAnalyzer)
    → AI (AIAnalyst, MasterAnalyst, ModelVersionManager)
    → Agents (Market/Analysis/Decision/Learning/Risk agent classes)
    → Strategy (SignalEngine, strategies package)
    → Hybrid (FlowController — constructed, not actively driven)
    → Risk (RiskEngine, CircuitBreaker, TradePermission, Drawdown, AutonomousRisk)
    → Safety (SafetyGuard, SpreadMonitor)
    → Execution (PaperTrader, ExecutionRouter)
    → Broker (AccountManager, OrderManager, JournalBridge, EconomicCalendar)
    → Analytics (PerformanceAnalyzer, StrategyTracker, RankingEngine, PerformanceReport)
    → Reports (BacktestReport)
    → Learning (ConfidenceEngine, AutoOptimizer, LessonMemory, MemoryIntegration, MistakeAnalyzer)
    → Dashboard (Streamlit path + bus subscriptions)
    → Alerts (TelegramNotifier + bus subscribers for risk/broker/error events)
    → Automation (ErrorHandler, DailyReview, SystemHealth legacy)
    → Webhook (SignalPipeline, Flask app)
    → Orchestrator (TradingOrchestrator, DailyRoutine, Scheduler, AuditTrail, HumanOverride, MessageBus, SystemState)
    → Runtime (AutonomousTraderSystem / TradingEngine — the trader itself)

Usage:
    python main.py                      # Start autonomous trading (full boot)
    python main.py --mode init          # Initialize + verify, don't start loop
    python main.py --mode status        # Show system status (boot, then print)
    python main.py --mode backtest      # Run backtest
    python main.py --mode health        # Boot + print health snapshot
    python main.py --mode obsolete      # Print obsolete-module registry
    python main.py --pairs EURUSD,GBPUSD  # Override pairs
    python main.py --timeframe 1h       # Override timeframe
    python main.py --paper              # Force paper mode
    python main.py --no-telegram        # Disable Telegram
=====================================================
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure UTF-8 stdout/stderr (Windows console quirks)
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import (
    EXECUTION_MODE,
    INITIAL_BALANCE,
    ENABLE_TELEGRAM, SYMBOLS, DEFAULT_TIMEFRAME,
)
from core.constants import clean_symbol, LOGS_DIR
from core.lifecycle import Phase
from core.runtime import boot_runtime, get_runtime


# ──────────────────────────────────────────────────────────────
# SYSTEM BANNER
# ──────────────────────────────────────────────────────────────

BANNER = r"""
=================================
  ____  _____ ___ _   _ ____
 |  _ \| ____|_ _| \ | |  _ \
 | | | |  _|  | ||  \| | | | |
 | |_| | |___ | || |\  | |_| |
 |____/|_____|___|_| \_|____/
                     _    _ _____
                    / \  | | ___|
                   / _ \ | |___ \
                  / ___ \| |___) |
                 /_/   \_\_|____/

  AUTONOMOUS TRADING SYSTEM
  Day 37+ Runtime-Unified
=================================
"""


# ──────────────────────────────────────────────────────────────
# LOGGING SETUP
# ──────────────────────────────────────────────────────────────

def setup_logging():
    """Configure comprehensive logging."""
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    log_level = logging.INFO

    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[
            logging.FileHandler(LOGS_DIR / "forex_ai.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

    # Reduce verbosity of noisy libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("matplotlib").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("sentence_transformers").setLevel(logging.WARNING)


# ──────────────────────────────────────────────────────────────
# MAIN SYSTEM CLASS (composition root)
# ──────────────────────────────────────────────────────────────

class ForexAISystem:
    """
    Central controller for the FOREX AI Autonomous Trading System.

    Day 37+ runtime-unified version: this class is now a thin wrapper around
    core.runtime.Runtime, which owns the ServiceRegistry + LifecycleManager +
    EventBus + HealthMonitor + RuntimeMetrics. The previous version wired
    ~9 of the ~24 required services inline; this version wires ALL of them
    through a single phase-ordered boot path.
    """

    def __init__(self, args=None):
        self.args = args or argparse.Namespace()
        self.runtime = get_runtime()
        self.status = SystemStatus()
        self.running = False
        self.start_time = None
        self._stop_requested = False

        # Resolve execution mode (MT5 demo only - paper trading removed)
        self.execution_mode = EXECUTION_MODE  # Always mt5_demo
        self.enable_telegram = ENABLE_TELEGRAM and not getattr(
            self.args, "no_telegram", False
        )
        self.symbols = self._resolve_symbols()
        self.timeframe = getattr(self.args, "timeframe", None) or DEFAULT_TIMEFRAME
        self.balance = INITIAL_BALANCE

        # The trader is constructed by the runtime's RUNTIME phase and
        # registered in the ServiceRegistry under "trader" / "trading_engine".
        # We resolve it after boot.
        self.trading_engine = None

    def _resolve_symbols(self) -> list[str]:
        pairs_arg = getattr(self.args, "pairs", None)
        if pairs_arg:
            return [clean_symbol(p.strip()) for p in pairs_arg.split(",")]
        return [clean_symbol(s) for s in SYMBOLS]

    # ─────────────────────────────────────────────
    # INITIALIZATION
    # ─────────────────────────────────────────────

    def initialize(self) -> bool:
        """Boot the entire runtime through the LifecycleManager. Returns True
        if every critical phase succeeded."""
        print(BANNER)
        print("  Booting runtime (24 phases)...\n")

        # Override config-driven settings if CLI args were supplied.
        self._apply_cli_overrides()

        # Register a phase-complete callback so we get a live progress print.
        def _on_phase(result):
            icon = "OK" if result.ok else "!!"
            if result.skipped:
                icon = "--"
            svcs = ", ".join(result.services_registered) if result.services_registered else "(no services)"
            err = f"  ERR: {result.error}" if result.error else ""
            print(f"  [{icon}] {result.phase.value:<14} ({result.duration_sec}s) — {svcs}{err}")

        self.runtime.lifecycle.on_phase_complete(_on_phase)

        # Boot every phase in order.
        self.runtime.boot()

        # Resolve the trading engine from the registry.
        self.trading_engine = self.runtime.registry.try_resolve("trading_engine")
        if self.trading_engine is None:
            # Fallback: try the trader directly.
            self.trading_engine = self.runtime.registry.try_resolve("trader")

        print()
        self._print_boot_summary()

        # Critical phases: BOOTSTRAP and PERSISTENCE must succeed.
        for critical in (Phase.BOOTSTRAP, Phase.PERSISTENCE):
            r = self.runtime.lifecycle.last_result(critical)
            if r is None or not r.ok:
                return False
        return True

    def _apply_cli_overrides(self) -> None:
        """If CLI args override config values, push them into the registry."""
        # CLI pairs override
        if hasattr(self.args, "pairs") and self.args.pairs:
            self.runtime.registry.register_instance("symbols", self.symbols)
        if self.execution_mode != EXECUTION_MODE:
            # Re-register execution_mode so boot_runtime_phase picks up the
            # CLI override instead of the .env value.
            self.runtime.registry.register_instance("execution_mode", self.execution_mode)

    def _print_boot_summary(self) -> None:
        """Print final boot summary."""
        report = self.runtime.lifecycle.report()
        phases = report["phases"]
        ok = sum(1 for p in phases if p["ok"] and not p["skipped"])
        failed = sum(1 for p in phases if not p["ok"])
        skipped = sum(1 for p in phases if p["skipped"])
        print("=" * 60)
        print(f"  Boot complete: {ok} phases OK, {failed} failed, {skipped} skipped")
        if failed:
            print(f"  FAILED phases:")
            for p in phases:
                if not p["ok"]:
                    print(f"    - {p['phase']}: {p.get('error', 'unknown')}")
        print(f"  Trader wired: {'yes' if self.trading_engine else 'NO'}")
        print(f"  Registry services: {len(self.runtime.registry.health())}")
        print("=" * 60)

    # ─────────────────────────────────────────────
    # MAIN TRADING LOOP
    # ─────────────────────────────────────────────

    def start_trading(self):
        """Start the autonomous trading loop.

        Day 37+ fix: This method now wraps the trader's run() in an
        auto-restart loop. If the trader exits for ANY reason (crash,
        unexpected exception, or graceful return), main.py waits 10
        seconds and relaunches it. The agent NEVER turns off unless the
        user presses Ctrl+C twice or sends /stop via Telegram.
        """
        if not self.trading_engine:
            logging.error("Trading engine not initialized — cannot start")
            return

        self.running = True
        self.start_time = datetime.now(timezone.utc)
        logging.info(
            f"[System] Trading started | Mode: {self.execution_mode.upper()} | "
            f"Pairs: {self.symbols} | Balance: ${self.balance} | "
            f"Auto-restart: ON"
        )

        # Send startup notification
        notifier = self.runtime.registry.try_resolve("telegram_notifier")
        if notifier:
            self._notify_startup(notifier)

        restart_count = 0
        try:
            while not self._stop_requested:
                try:
                    report = self.trading_engine.run()
                    self._write_final_report(report)
                    if self._stop_requested:
                        break
                    # Trader returned without being asked to stop — this is
                    # unexpected (the run() loop should run forever). Log +
                    # restart.
                    restart_count += 1
                    logging.warning(
                        f"[System] Trader exited unexpectedly (restart #{restart_count}). "
                        f"Relaunching in 10s..."
                    )
                    self._notify_restart(restart_count, reason="unexpected exit")
                    time.sleep(10)
                except KeyboardInterrupt:
                    logging.info("[System] Stop requested by user (Ctrl+C)")
                    self._stop_requested = True
                    break
                except Exception as e:
                    restart_count += 1
                    logging.error(
                        f"[System] Fatal error in trading loop (restart #{restart_count}): {e}",
                        exc_info=True,
                    )
                    # Publish system.error so bus subscribers (alerts) pick it up.
                    try:
                        from core.event_bus import get_bus
                        get_bus().publish("system.error", {
                            "channel": "fatal",
                            "reason": str(e),
                            "restart_count": restart_count,
                        }, source="main")
                    except Exception:
                        pass
                    self._notify_restart(restart_count, reason=str(e)[:200])
                    if self._stop_requested:
                        break
                    logging.info(f"[System] Relaunching trader in 30s...")
                    time.sleep(30)
        finally:
            self.running = False
            self._shutdown()

    def stop_trading(self):
        """Request the trading loop to stop."""
        self._stop_requested = True
        if self.trading_engine:
            self.trading_engine.stop()
        logging.info("[System] Stop requested — shutting down gracefully")

    # ─────────────────────────────────────────────
    # SYSTEM STATUS
    # ─────────────────────────────────────────────

    def get_system_status(self) -> dict:
        """Get comprehensive system status."""
        uptime = (
            str(datetime.now(timezone.utc) - self.start_time)
            if self.start_time and self.running
            else None
        )
        return {
            "running": self.running,
            "uptime": uptime,
            "mode": self.execution_mode.upper(),
            "pairs": self.symbols,
            "timeframe": self.timeframe,
            "balance": self.balance,
            "boot_phases": self.runtime.lifecycle.report()["phases"],
            "registry_health": self.runtime.registry.health(),
            "trader_health": (
                self.trading_engine.health_status()
                if self.trading_engine and hasattr(self.trading_engine, "health_status")
                else None
            ),
            "runtime_metrics": self.runtime.metrics.build_report(),
        }

    def get_health_snapshot(self) -> dict:
        """Force a one-shot health check and return the snapshot."""
        return self.runtime.health.run_once().to_dict()

    # ─────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────

    def _notify_startup(self, notifier):
        """Send startup notification via Telegram."""
        try:
            import asyncio

            msg = (
                f"🤖 FOREX AI System Started\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"Mode: {self.execution_mode.upper()}\n"
                f"Pairs: {len(self.symbols)} ({', '.join(self.symbols[:5])}...)\n"
                f"Timeframe: {self.timeframe}\n"
                f"Balance: ${self.balance}\n"
                f"Max Open: 5 | Max Daily Loss: 3%\n"
                f"Auto-restart: ON\n"
                f"━━━━━━━━━━━━━━━━━━━━━"
            )
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(notifier.send_message(msg))
                else:
                    loop.run_until_complete(notifier.send_message(msg))
            except RuntimeError:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(notifier.send_message(msg))
                loop.close()
        except Exception as e:
            logging.warning(f"[System] Telegram startup notification failed: {e}")

    def _notify_restart(self, restart_count: int, reason: str = ""):
        """Send auto-restart notification via Telegram."""
        notifier = self.runtime.registry.try_resolve("telegram_notifier")
        if not notifier:
            return
        try:
            import asyncio
            msg = (
                f"🔄 AUTO-RESTART #{restart_count}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"Reason: {reason[:200] if reason else 'unexpected exit'}\n"
                f"Relaunching in 10-30s...\n"
                f"━━━━━━━━━━━━━━━━━━━━━"
            )
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(notifier.send_message(msg))
                else:
                    loop.run_until_complete(notifier.send_message(msg))
            except RuntimeError:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(notifier.send_message(msg))
                loop.close()
        except Exception as e:
            logging.warning(f"[System] Telegram restart notification failed: {e}")

    def _write_final_report(self, report: dict):
        """Save final system report."""
        report_dir = PROJECT_ROOT / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        path = report_dir / "latest_report.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)

    def _shutdown(self):
        """Graceful shutdown sequence."""
        logging.info("[System] Shutting down...")
        notifier = self.runtime.registry.try_resolve("telegram_notifier")
        if notifier:
            try:
                import asyncio

                msg = "FOREX AI System Stopped"
                try:
                    loop = asyncio.get_event_loop()
                    if not loop.is_running():
                        loop.run_until_complete(notifier.send_message(msg))
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(notifier.send_message(msg))
                    loop.close()
            except Exception:
                pass

        # Tear down the runtime (stops health monitor, runs shutdown hooks).
        try:
            self.runtime.shutdown()
        except Exception as e:
            logging.error(f"[System] Runtime shutdown error: {e}", exc_info=True)

        logging.info("[System] Shutdown complete")


# ──────────────────────────────────────────────────────────────
# SYSTEM STATUS TRACKER (kept for backward compat with old code paths)
# ──────────────────────────────────────────────────────────────

class SystemStatus:
    """Tracks initialization status of all components."""

    def __init__(self):
        self.checks = {}
        self.errors = []

    def ok(self, component: str, detail: str = ""):
        self.checks[component] = {"status": "OK", "detail": detail}

    def fail(self, component: str, reason: str):
        self.checks[component] = {"status": "FAILED", "detail": reason}
        self.errors.append(f"{component}: {reason}")

    def warn(self, component: str, detail: str):
        self.checks[component] = {"status": "WARNING", "detail": detail}

    @property
    def all_ok(self) -> bool:
        return not self.errors


# ──────────────────────────────────────────────────────────────
# CLI ENTRY POINT
# ──────────────────────────────────────────────────────────────

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="FOREX AI — Autonomous Trading System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                          # Start autonomous trading
  python main.py --mode init              # Initialize system only
  python main.py --mode status            # Show system status
  python main.py --mode health            # Show health snapshot
  python main.py --mode obsolete          # Show obsolete module registry
  python main.py --paper                  # Force paper trading mode
  python main.py --pairs EURUSD,GBPUSD    # Trade specific pairs
  python main.py --timeframe 1h           # Use 1-hour timeframe
  python main.py --no-telegram            # Disable Telegram alerts
        """,
    )
    parser.add_argument(
        "--mode",
        choices=["init", "start", "status", "stop", "backtest", "health", "obsolete"],
        default="start",
        help="System mode",
    )
    parser.add_argument("--pairs", help="Comma-separated currency pairs (e.g., EURUSD,GBPUSD)")
    parser.add_argument("--timeframe", help="Trading timeframe (e.g., 15m, 1h, 4h)")
    parser.add_argument("--paper", action="store_true", help="Force paper trading mode")
    parser.add_argument("--no-telegram", action="store_true", help="Disable Telegram notifications")
    parser.add_argument("--balance", type=float, help="Starting balance override")
    parser.add_argument("--max-cycles", type=int, help="Max trading cycles (for testing)")

    args = parser.parse_args()

    setup_logging()
    logger = logging.getLogger("main")

    # Special modes that don't require a full boot
    if args.mode == "obsolete":
        _print_obsolete_registry()
        return

    if args.mode == "backtest":
        _run_backtest(args)
        return

    # All other modes boot the runtime.
    system = ForexAISystem(args)

    try:
        if args.mode == "init":
            success = system.initialize()
            sys.exit(0 if success else 1)

        elif args.mode == "start":
            if system.initialize():
                system.start_trading()
            else:
                logger.error("System initialization failed — cannot start trading")
                sys.exit(1)

        elif args.mode == "status":
            if system.initialize():
                status = system.get_system_status()
                print(json.dumps(status, indent=2, default=str))

        elif args.mode == "health":
            if system.initialize():
                health = system.get_health_snapshot()
                print(json.dumps(health, indent=2, default=str))

        elif args.mode == "stop":
            logger.info("Stop command — system must be stopped via Ctrl+C or Telegram")

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt — stopping")
        system.stop_trading()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


def _run_backtest(args):
    """Run the backtesting engine."""
    from backtest.engine import BacktestEngine

    logging.info("[Backtest] Starting backtest engine...")
    engine = BacktestEngine()
    logging.info("[Backtest] Backtest complete — check reports/")


def _print_obsolete_registry():
    """Print the obsolete module registry."""
    from core.obsolete import OBSOLETE_MODULES, obsolete_summary

    print("\n" + "=" * 70)
    print("  OBSOLETE / ORPHAN MODULE REGISTRY")
    print("=" * 70)
    summary = obsolete_summary()
    print(f"\n  Total: {summary['total']} modules")
    for cat, count in sorted(summary.items()):
        if cat == "total":
            continue
        print(f"    {cat:<14} {count}")
    print()
    for entry in OBSOLETE_MODULES:
        print(f"  [{entry.category.value.upper():<12}] {entry.path}")
        print(f"    reason: {entry.reason}")
        print(f"    action: {entry.action}")
        print()


if __name__ == "__main__":
    main()
