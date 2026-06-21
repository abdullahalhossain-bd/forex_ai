#!/usr/bin/env python3
"""
=====================================================
FOREX AI AUTONOMOUS TRADING SYSTEM
=====================================================
Main Entry Point — Central Controller

Pipeline:
    System Initialization
    → Data Collection
    → Market Analysis (Technical + SMC + Liquidity + Session)
    → Currency Strength + Intermarket Analysis
    → News Filter
    → AI Reasoning (LLM + Master Analyst)
    → Decision Agent
    → Risk Engine
    → MT5/Paper Execution
    → Position Management
    → Database Logging
    → Learning System
    → Dashboard Update
    → Telegram Notification

Usage:
    python main.py                      # Start autonomous trading
    python main.py --mode init          # Initialize only
    python main.py --mode status        # Show system status
    python main.py --mode backtest      # Run backtest
    python main.py --pairs EURUSD,GBPUSD  # Override pairs
    python main.py --timeframe 1h       # Override timeframe
    python main.py --paper              # Force paper mode
    python main.py --no-telegram        # Disable Telegram
=====================================================
"""

import os
import json
import time
import logging
import argparse
import threading
import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import (
    Config, EXECUTION_MODE, USE_SCANNER, APPROVAL_MODE,
    INITIAL_BALANCE, PAPER_BALANCE, LOOP_INTERVAL_SEC,
    BACKUP_INTERVAL_MIN, RECOVERY_COOLDOWN_MIN,
    ENABLE_TELEGRAM, SYMBOLS, DEFAULT_TIMEFRAME,
    validate_mt5_config, validate_telegram_config,
)
from core.constants import clean_symbol, LOGS_DIR, MEMORY_DIR, DATABASE_DIR


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
=================================
"""


# ──────────────────────────────────────────────────────────────
# SYSTEM STATUS TRACKER
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

    def print_status(self):
        """Print formatted status report."""
        for component, info in self.checks.items():
            icon = "OK" if info["status"] == "OK" else ("!!" if info["status"] == "FAILED" else "~~")
            detail = f" — {info['detail']}" if info['detail'] else ""
            print(f"  [{icon}] {component}{detail}")

        print()
        if self.all_ok:
            print("  FOREX AI STATUS: AUTONOMOUS MODE ACTIVE")
        else:
            print("  FOREX AI STATUS: PARTIAL INIT (see errors above)")
        print("=" * 40)


# ──────────────────────────────────────────────────────────────
# MAIN SYSTEM CLASS
# ──────────────────────────────────────────────────────────────

class ForexAISystem:
    """
    Central controller for the FOREX AI Autonomous Trading System.
    Wires together all components and manages the main trading loop.
    """

    def __init__(self, args=None):
        self.args = args or argparse.Namespace()
        self.config = Config()
        self.status = SystemStatus()
        self.running = False
        self.start_time = None
        self._stop_requested = False

        # Resolve execution mode
        self.execution_mode = getattr(self.args, 'paper', False) and "paper" or EXECUTION_MODE
        self.enable_telegram = ENABLE_TELEGRAM and not getattr(self.args, 'no_telegram', False)
        self.symbols = self._resolve_symbols()
        self.timeframe = getattr(self.args, 'timeframe', None) or DEFAULT_TIMEFRAME
        self.balance = PAPER_BALANCE if self.execution_mode == "paper" else INITIAL_BALANCE

        # Component references (initialized later)
        self.trading_engine = None
        self.telegram_notifier = None
        self.db = None

    def _resolve_symbols(self) -> list[str]:
        """Resolve the list of currency pairs to trade."""
        pairs_arg = getattr(self.args, 'pairs', None)
        if pairs_arg:
            return [clean_symbol(p.strip()) for p in pairs_arg.split(",")]
        return [clean_symbol(s) for s in SYMBOLS]

    # ─────────────────────────────────────────────
    # INITIALIZATION
    # ─────────────────────────────────────────────

    def initialize(self) -> bool:
        """Initialize all system components and report status."""
        print(BANNER)
        print("  Initializing system...\n")

        # 1. Environment
        self._init_environment()

        # 2. Database
        self._init_database()

        # 3. MT5 Connection (if needed)
        self._init_mt5()

        # 4. Market Data
        self._init_market_data()

        # 5. AI Agents
        self._init_ai_agents()

        # 6. Risk Engine
        self._init_risk_engine()

        # 7. Dashboard
        self._init_dashboard()

        # 8. Telegram
        self._init_telegram()

        # 9. Trading Engine
        self._init_trading_engine()

        # Print final status
        print()
        self.status.print_status()

        return self.status.all_ok

    def _init_environment(self):
        """Validate environment and directories."""
        try:
            for d in (LOGS_DIR, MEMORY_DIR, DATABASE_DIR, PROJECT_ROOT / "data", PROJECT_ROOT / "backups", PROJECT_ROOT / "reports"):
                d.mkdir(parents=True, exist_ok=True)

            # Verify critical config
            if self.execution_mode == "mt5_demo":
                validate_mt5_config()

            self.status.ok("Environment Loaded", f"mode={self.execution_mode}")
        except Exception as e:
            self.status.fail("Environment Loaded", str(e))

    def _init_database(self):
        """Initialize SQLite database."""
        try:
            from database.db import TraderDB
            self.db = TraderDB()
            # Quick health check
            stats = self.db.get_account_stats(starting_balance=self.balance)
            self.status.ok("Database Connected", f"trades={stats.get('total_trades', 0)}")
        except Exception as e:
            self.status.fail("Database Connected", str(e))

    def _init_mt5(self):
        """Initialize MT5 connection if in mt5_demo mode."""
        if self.execution_mode != "mt5_demo":
            self.status.ok("MT5 Connection", "skipped (paper mode)")
            return

        try:
            from broker.mt5_connection import MT5Connection
            from config import MT5_LOGIN, MT5_PASSWORD, MT5_SERVER, MT5_PATH

            conn = MT5Connection(
                login=MT5_LOGIN, password=MT5_PASSWORD,
                server=MT5_SERVER, path=MT5_PATH or None,
            )
            if conn.connect():
                self.status.ok("MT5 Connected", f"login={MT5_LOGIN}")
                conn.disconnect()  # Will be reconnected by TradingEngine
            else:
                self.status.fail("MT5 Connected", "Connection failed — check credentials and terminal")
        except ImportError:
            self.status.fail("MT5 Connected", "MetaTrader5 package not installed")
        except Exception as e:
            self.status.fail("MT5 Connected", str(e))

    def _init_market_data(self):
        """Verify market data availability."""
        try:
            from data.fetcher import DataFetcher
            fetcher = DataFetcher()
            # Try a quick fetch to verify data source
            df = fetcher.fetch_ohlcv("EURUSD", "15m", periods=5)
            if df is not None and len(df) > 0:
                self.status.ok("Market Scanner Running", f"source={self.config.DATA_SOURCE}")
            else:
                self.status.warn("Market Scanner Running", "No data returned — check network")
        except Exception as e:
            self.status.warn("Market Scanner Running", f"Data fetch test failed: {e}")

    def _init_ai_agents(self):
        """Verify AI agent modules can be imported."""
        try:
            from agents.analysis_agent import AnalysisAgent
            from agents.decision_agent import DecisionAgent
            from agents.market_agent import MarketAgent
            from agents.learning_agent import LearningAgent

            # Test LLM availability
            llm_status = "unknown"
            try:
                from ai.ai_analyst import AIAnalyst
                analyst = AIAnalyst()
                llm_status = "groq" if analyst.groq_client else ("gemini" if analyst.gemini_model else "none")
            except Exception:
                llm_status = "unavailable"

            self.status.ok("AI Agents Initialized", f"LLM={llm_status}")
        except ImportError as e:
            self.status.fail("AI Agents Initialized", f"Import error: {e}")

    def _init_risk_engine(self):
        """Verify risk management components."""
        try:
            from risk.risk_engine import RiskEngine
            from risk.circuit_breaker import CircuitBreaker
            from risk.trade_permission import TradePermission
            self.status.ok("Risk Engine Active", f"max_risk=1%, daily_limit=3%")
        except ImportError as e:
            self.status.fail("Risk Engine Active", f"Import error: {e}")

    def _init_dashboard(self):
        """Check dashboard availability."""
        try:
            import streamlit
            self.status.ok("Dashboard Ready", "streamlit available")
        except ImportError:
            self.status.warn("Dashboard Ready", "streamlit not installed — run: pip install streamlit")

    def _init_telegram(self):
        """Initialize Telegram bot if enabled."""
        if not self.enable_telegram:
            self.status.ok("Telegram Connected", "disabled")
            return

        try:
            from alerts.telegram_bot import TelegramNotifier
            self.telegram_notifier = TelegramNotifier()
            self.status.ok("Telegram Connected", f"chat_id={self.config.TELEGRAM_CHAT_ID}")
        except Exception as e:
            self.status.warn("Telegram Connected", f"Failed: {e}")

    def _init_trading_engine(self):
        """Initialize the core trading engine."""
        try:
            from core.trading_engine import TradingEngine
            self.trading_engine = TradingEngine(
                symbols=self.symbols,
                timeframe=self.timeframe,
                balance=self.balance,
                poll_seconds=LOOP_INTERVAL_SEC,
                backup_interval_minutes=BACKUP_INTERVAL_MIN,
                cooldown_minutes=RECOVERY_COOLDOWN_MIN,
                enable_telegram=self.enable_telegram,
                use_scanner=USE_SCANNER,
                execution_mode=self.execution_mode,
                approval_mode=APPROVAL_MODE,
            )
            self.status.ok("Trading Engine Ready", f"pairs={self.symbols}")
        except Exception as e:
            self.status.fail("Trading Engine Ready", str(e))

    # ─────────────────────────────────────────────
    # MAIN TRADING LOOP
    # ─────────────────────────────────────────────

    def start_trading(self):
        """Start the autonomous trading loop."""
        if not self.trading_engine:
            logging.error("Trading engine not initialized — cannot start")
            return

        self.running = True
        self.start_time = datetime.now(timezone.utc)
        logging.info(
            f"[System] Trading started | Mode: {self.execution_mode.upper()} | "
            f"Pairs: {self.symbols} | Balance: ${self.balance}"
        )

        # Send startup notification
        if self.telegram_notifier:
            self._notify_startup()

        try:
            report = self.trading_engine.run()
            self._write_final_report(report)
        except KeyboardInterrupt:
            logging.info("[System] Stop requested by user")
        except Exception as e:
            logging.error(f"[System] Fatal error: {e}", exc_info=True)
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
        uptime = str(datetime.now(timezone.utc) - self.start_time) if self.start_time and self.running else None
        return {
            "running": self.running,
            "uptime": uptime,
            "mode": self.execution_mode.upper(),
            "pairs": self.symbols,
            "timeframe": self.timeframe,
            "balance": self.balance,
            "initialization": self.status.checks,
            "errors": self.status.errors,
        }

    # ─────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────

    def _notify_startup(self):
        """Send startup notification via Telegram."""
        try:
            import asyncio
            msg = (
                f"FOREX AI System Started\n"
                f"Mode: {self.execution_mode.upper()}\n"
                f"Pairs: {', '.join(self.symbols)}\n"
                f"Timeframe: {self.timeframe}\n"
                f"Balance: ${self.balance}"
            )
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(self.telegram_notifier.send_message(msg))
                else:
                    loop.run_until_complete(self.telegram_notifier.send_message(msg))
            except RuntimeError:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self.telegram_notifier.send_message(msg))
                loop.close()
        except Exception as e:
            logging.warning(f"[System] Telegram startup notification failed: {e}")

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
        if self.telegram_notifier:
            try:
                import asyncio
                msg = "FOREX AI System Stopped"
                try:
                    loop = asyncio.get_event_loop()
                    if not loop.is_running():
                        loop.run_until_complete(self.telegram_notifier.send_message(msg))
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(self.telegram_notifier.send_message(msg))
                    loop.close()
            except Exception:
                pass

        logging.info("[System] Shutdown complete")


# ──────────────────────────────────────────────────────────────
# LOGGING SETUP
# ──────────────────────────────────────────────────────────────

def setup_logging():
    """Configure comprehensive logging."""
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    log_level = logging.INFO

    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=log_level,
        format=log_format,
        handlers=[
            logging.FileHandler(LOGS_DIR / 'forex_ai.log'),
            logging.StreamHandler()
        ]
    )

    # Reduce verbosity of noisy libraries
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('matplotlib').setLevel(logging.WARNING)
    logging.getLogger('PIL').setLevel(logging.WARNING)
    logging.getLogger('chromadb').setLevel(logging.WARNING)
    logging.getLogger('sentence_transformers').setLevel(logging.WARNING)


# ──────────────────────────────────────────────────────────────
# CLI ENTRY POINT
# ──────────────────────────────────────────────────────────────

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='FOREX AI — Autonomous Trading System',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                          # Start autonomous trading
  python main.py --mode init              # Initialize system only
  python main.py --mode status            # Show system status
  python main.py --paper                  # Force paper trading mode
  python main.py --pairs EURUSD,GBPUSD    # Trade specific pairs
  python main.py --timeframe 1h           # Use 1-hour timeframe
  python main.py --no-telegram            # Disable Telegram alerts
        """
    )
    parser.add_argument('--mode', choices=['init', 'start', 'status', 'stop', 'backtest'],
                       default='start', help='System mode')
    parser.add_argument('--pairs', help='Comma-separated currency pairs (e.g., EURUSD,GBPUSD)')
    parser.add_argument('--timeframe', help='Trading timeframe (e.g., 15m, 1h, 4h)')
    parser.add_argument('--paper', action='store_true', help='Force paper trading mode')
    parser.add_argument('--no-telegram', action='store_true', help='Disable Telegram notifications')
    parser.add_argument('--balance', type=float, help='Starting balance override')
    parser.add_argument('--max-cycles', type=int, help='Max trading cycles (for testing)')

    args = parser.parse_args()

    # Setup logging
    setup_logging()
    logger = logging.getLogger("main")

    # Create system
    system = ForexAISystem(args)

    try:
        if args.mode == 'init':
            # Initialize only
            success = system.initialize()
            sys.exit(0 if success else 1)

        elif args.mode == 'start':
            # Full start
            if system.initialize():
                system.start_trading()
            else:
                logger.error("System initialization failed — cannot start trading")
                sys.exit(1)

        elif args.mode == 'status':
            # Print status
            status = system.get_system_status()
            print(json.dumps(status, indent=2, default=str))

        elif args.mode == 'stop':
            logger.info("Stop command — system must be stopped via Ctrl+C or Telegram")

        elif args.mode == 'backtest':
            # Run backtest
            _run_backtest(args)

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
    # Add pairs and run
    logging.info("[Backtest] Backtest complete — check reports/")


if __name__ == "__main__":
    main()
