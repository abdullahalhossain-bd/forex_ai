# orchestrator/trading_orchestrator.py — Day 60 | Central Nervous System
# ============================================================
# AI Trader-এর Brain Coordinator.
#
# This is the TOP-LEVEL controller that orchestrates ALL modules
# in the autonomous trading loop. It coordinates:
#
#   Market Intelligence → Research Intelligence → Decision Intelligence
#   → Risk Intelligence → Execution Intelligence → Memory Intelligence
#   → Learning Intelligence → Research Loop
#
# Architecture:
#   All agents communicate through AgentMessageBus (no direct calls).
#   SystemState tracks global state. SafetyController provides emergency stops.
#   SelfHealingSystem recovers from failures. HumanOverride allows manual control.
#
# File: orchestrator/trading_orchestrator.py
# ============================================================

import json
import time
import traceback
from datetime import datetime, timezone
from typing import Optional

from utils.logger import get_logger

log = get_logger("orchestrator")

from orchestrator.communication_bus import AgentMessageBus, AgentMessage
from orchestrator.system_state import SystemStateManager, SystemState
from orchestrator.safety_controller import SafetyController
from orchestrator.self_healing import SelfHealingSystem
from orchestrator.human_override import HumanOverrideSystem
from orchestrator.mode_manager import ModeManager
from orchestrator.decision_journal import DecisionJournal
from orchestrator.audit_trail import AuditTrail
from orchestrator.scheduler import TaskScheduler
from orchestrator.daily_routine import DailyRoutineManager


class TradingOrchestrator:
    """
    Central Nervous System of the AI Trading Operating System.
    
    Coordinates all agents through the message bus and manages
    the autonomous trading loop lifecycle.
    
    Usage:
        orchestrator = TradingOrchestrator(symbols=["EURUSD", "GBPUSD"])
        orchestrator.start_system()
        # System runs autonomously...
        orchestrator.shutdown()
    """

    def __init__(
        self,
        symbols: list = None,
        timeframe: str = "15m",
        balance: float = 10000.0,
        poll_seconds: int = 60,
        execution_mode: str = "paper",
        approval_mode: int = 3,
        enable_telegram: bool = True,
        enable_research: bool = True,
        enable_risk_manager: bool = True,
        use_scanner: bool = False,
    ):
        # ── Core Configuration ───────────────────────────
        self.symbols = symbols or ["EURUSD", "GBPUSD", "USDJPY"]
        self.timeframe = timeframe
        self.balance = balance
        self.poll_seconds = poll_seconds
        self.execution_mode = execution_mode
        self.approval_mode = approval_mode
        self.enable_telegram = enable_telegram
        self.enable_research = enable_research
        self.enable_risk_manager = enable_risk_manager
        self.use_scanner = use_scanner

        # ── Orchestrator Sub-Systems ────────────────────
        self.bus: AgentMessageBus = AgentMessageBus()
        self.state_mgr: SystemStateManager = SystemStateManager()
        self.safety: SafetyController = SafetyController(self.state_mgr)
        self.self_healing: SelfHealingSystem = SelfHealingSystem(self.bus, self.state_mgr)
        self.human_override: HumanOverrideSystem = HumanOverrideSystem(self.state_mgr, self.bus)
        self.mode_manager: ModeManager = ModeManager(self.state_mgr)
        self.journal: DecisionJournal = DecisionJournal()
        self.audit: AuditTrail = AuditTrail()
        self.scheduler: TaskScheduler = TaskScheduler()
        self.daily_routine: DailyRoutineManager = DailyRoutineManager(self)

        # ── Agent Instances (initialized on start) ──────
        self._market_agent = None
        self._analysis_agent = None
        self._decision_agent = None
        self._risk_agent = None
        self._learning_agent = None
        self._paper_trader = None
        self._research_agent = None
        self._risk_manager = None

        # ── Trading State ──────────────────────────────
        self._running = False
        self._cycle_count = 0
        self._current_cycle_id = None
        self._total_trades = 0
        self._total_wins = 0
        self._total_losses = 0
        self._errors = []

        log.info("[Orchestrator] TradingOrchestrator initialized")

    # ──────────────────────────────────────────────────
    # SYSTEM LIFECYCLE
    # ──────────────────────────────────────────────────

    def start_system(self) -> dict:
        """
        Full system startup sequence.
        Initializes all agents, connects to brokers, starts subsystems.
        Returns startup report.
        """
        self._print_startup_banner()
        startup_report = {"steps": [], "warnings": [], "errors": []}

        # Step 1: Mode initialization
        self._init_mode(startup_report)
        
        # Step 2: Communication bus
        self._init_communication_bus(startup_report)
        
        # Step 3: Agent initialization
        self._init_agents(startup_report)
        
        # Step 4: Broker connection
        self._init_broker(startup_report)
        
        # Step 5: Safety systems
        self._init_safety_systems(startup_report)
        
        # Step 6: Self-healing
        self._init_self_healing(startup_report)
        
        # Step 7: Daily routine
        self._init_daily_routine(startup_report)
        
        # Step 8: Market status check
        self._init_market_status(startup_report)

        # Set system health
        if startup_report["errors"]:
            self.state_mgr.update(system_health="DEGRADED", current_task="READY_WITH_ERRORS")
        else:
            self.state_mgr.update(system_health="HEALTHY", current_task="READY")

        self._running = True
        self._print_startup_summary(startup_report)
        return startup_report

    def run_cycle(self) -> dict:
        """
        Execute one complete trading cycle for all symbols.
        This is the MAIN LOOP body called repeatedly.
        
        Pipeline:
            Market Analysis → Research Check → Decision → Risk Validation
            → Execution → Learning → Memory
        """
        if not self._running:
            return {"status": "stopped"}

        self._cycle_count += 1
        self._current_cycle_id = f"cycle_{int(time.time())}_{self._cycle_count}"
        cycle_start = time.time()
        cycle_results = {
            "cycle_id": self._current_cycle_id,
            "cycle_number": self._cycle_count,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "trades": [],
            "errors": [],
        }

        self.audit.log_event("cycle_start", {"cycle_id": self._current_cycle_id, "cycle": self._cycle_count})

        # ── Pre-Cycle Checks ──────────────────────────
        if not self._pre_cycle_checks(cycle_results):
            return cycle_results

        # ── Process Each Symbol ─────────────────────
        for symbol in self.symbols:
            try:
                result = self._run_symbol_cycle(symbol)
                cycle_results["trades"].append(result)
            except Exception as e:
                self._handle_cycle_error(symbol, e, cycle_results)

        # ── Post-Cycle Tasks ────────────────────────
        self._post_cycle_tasks(cycle_results)

        cycle_results["duration_seconds"] = round(time.time() - cycle_start, 2)
        self.audit.log_event("cycle_end", {
            "cycle_id": self._current_cycle_id,
            "duration": cycle_results["duration_seconds"],
        })

        return cycle_results

    def shutdown(self) -> dict:
        """
        Safe system shutdown. Closes positions, saves state, stops all systems.
        """
        log.info("[Orchestrator] Initiating safe shutdown...")
        self._running = False

        shutdown_report = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "cycles_completed": self._cycle_count,
            "total_trades": self._total_trades,
            "total_wins": self._total_wins,
            "total_losses": self._total_losses,
        }

        # Save all state
        self.bus.save_history()
        self.journal.save()
        self.audit.save()
        self.state_mgr.update(
            current_task="SHUTDOWN",
            system_health="DOWN",
        )

        # Stop scheduler
        self.scheduler.stop_all()

        log.info(f"[Orchestrator] Shutdown complete. Cycles: {self._cycle_count}")
        self._print_shutdown_summary(shutdown_report)
        return shutdown_report

    def run(self, max_cycles: int = None) -> dict:
        """
        Run the autonomous trading loop until stopped or max_cycles reached.
        This is the main entry point for continuous operation.
        """
        self.start_system()

        summary = {
            "mode": self.execution_mode,
            "scanner": self.use_scanner,
            "pairs": self.symbols,
            "summary": {},
        }

        try:
            while self._running:
                # Check max cycles
                if max_cycles and self._cycle_count >= max_cycles:
                    log.info(f"[Orchestrator] Max cycles ({max_cycles}) reached")
                    break

                # Run one cycle
                cycle_result = self.run_cycle()

                # Update state
                self.state_mgr.update(
                    cycle_count=self._cycle_count,
                    current_cycle_id=self._current_cycle_id,
                    last_cycle_time=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                )

                # Sleep between cycles
                if self._running:
                    time.sleep(self.poll_seconds)

        except KeyboardInterrupt:
            log.info("[Orchestrator] Interrupted by user (Ctrl+C)")
        except Exception as e:
            log.error(f"[Orchestrator] Fatal error: {e}", exc_info=True)
            self.state_mgr.update(system_health="DOWN", current_task=f"FATAL: {e}")

        # Build summary
        summary["summary"] = {
            "trades": self._total_trades,
            "wins": self._total_wins,
            "losses": self._total_losses,
            "win_rate": round(self._total_wins / max(1, self._total_trades) * 100, 1),
            "cycles": self._cycle_count,
            "balance": self.balance,
        }

        self.shutdown()
        return summary

    # ──────────────────────────────────────────────────
    # INITIALIZATION METHODS
    # ──────────────────────────────────────────────────

    def _init_mode(self, report: dict):
        """Step 1: Initialize operating mode."""
        mode_name = self.mode_manager.set_mode(self.execution_mode)
        report["steps"].append({"name": "Mode", "status": "OK", "detail": mode_name})
        log.info(f"[Orchestrator] Mode: {mode_name}")

    def _init_communication_bus(self, report: dict):
        """Step 2: Start communication bus and wire subscribers."""
        self._wire_bus_subscribers()
        report["steps"].append({"name": "Communication Bus", "status": "OK"})
        log.info("[Orchestrator] Communication bus active")

    def _init_agents(self, report: dict):
        """Step 3: Initialize all trading agents."""
        agents_to_init = [
            ("Market Agent", self._init_market_agent),
            ("Analysis Agent", self._init_analysis_agent),
            ("Decision Agent", self._init_decision_agent),
            ("Risk Agent", self._init_risk_agent),
            ("Learning Agent", self._init_learning_agent),
            ("Paper Trader", self._init_paper_trader),
            ("Research Agent", self._init_research_agent),
            ("Autonomous Risk Mgr", self._init_autonomous_risk),
        ]

        for name, init_func in agents_to_init:
            try:
                init_func()
                report["steps"].append({"name": name, "status": "OK"})
            except Exception as e:
                report["steps"].append({"name": name, "status": "FAIL", "detail": str(e)})
                report["warnings"].append(f"{name}: {e}")
                log.warning(f"[Orchestrator] {name} init failed (non-critical): {e}")

    def _init_broker(self, report: dict):
        """Step 4: Connect to broker (MT5 or Paper)."""
        if self.execution_mode == "mt5_demo":
            try:
                from broker.mt5_connection import MT5_AVAILABLE
                if MT5_AVAILABLE:
                    self.state_mgr.update(mt5_connected=True)
                    report["steps"].append({"name": "MT5 Broker", "status": "OK", "detail": "Package available"})
                else:
                    report["steps"].append({"name": "MT5 Broker", "status": "FAIL", "detail": "Package not installed"})
                    report["warnings"].append("MT5: Package not installed")
            except Exception as e:
                report["steps"].append({"name": "MT5 Broker", "status": "FAIL", "detail": str(e)})
        else:
            self.state_mgr.update(paper_trader_active=True)
            report["steps"].append({"name": "Paper Trader", "status": "OK", "detail": "Active"})

    def _init_safety_systems(self, report: dict):
        """Step 5: Initialize safety controller and human override."""
        self.safety.start()
        self.human_override.start()
        report["steps"].append({"name": "Safety Controller", "status": "OK"})
        report["steps"].append({"name": "Human Override", "status": "OK"})

    def _init_self_healing(self, report: dict):
        """Step 6: Initialize self-healing system."""
        self.self_healing.register_healers()
        report["steps"].append({"name": "Self-Healing", "status": "OK"})

    def _init_daily_routine(self, report: dict):
        """Step 7: Initialize daily routine manager."""
        self.daily_routine.setup()
        report["steps"].append({"name": "Daily Routine", "status": "OK"})

    def _init_market_status(self, report: dict):
        """Step 8: Check and set market status."""
        status = self.state_mgr.update_market_status()
        report["steps"].append({"name": "Market Status", "status": "OK", "detail": status})

    # ──────────────────────────────────────────────────
    # AGENT INITIALIZERS
    # ──────────────────────────────────────────────────

    def _init_market_agent(self):
        from agents.market_agent import MarketAgent
        self._market_agent = MarketAgent

    def _init_analysis_agent(self):
        from agents.analysis_agent import AnalysisAgent
        self._analysis_agent = AnalysisAgent()

    def _init_decision_agent(self):
        from agents.decision_agent import DecisionAgent
        self._decision_agent = DecisionAgent()

    def _init_risk_agent(self):
        from agents.risk_agent import RiskAgent
        self._risk_agent = RiskAgent(account_balance=self.balance)

    def _init_learning_agent(self):
        from agents.learning_agent import LearningAgent
        self._learning_agent = LearningAgent()

    def _init_paper_trader(self):
        from execution.paper_trader import PaperTrader
        self._paper_trader = PaperTrader(starting_balance=self.balance)

    def _init_research_agent(self):
        if self.enable_research:
            from research.research_agent import ResearchAgent
            self._research_agent = ResearchAgent(enable_auto_research=True)
            self.state_mgr.update(research_active=True)

    def _init_autonomous_risk(self):
        if self.enable_risk_manager:
            from risk.autonomous_risk import AutonomousRiskManager
            self._risk_manager = AutonomousRiskManager(balance=self.balance)
            self.state_mgr.update(risk_manager_active=True)

    # ──────────────────────────────────────────────────
    # BUS WIRING
    # ──────────────────────────────────────────────────

    def _wire_bus_subscribers(self):
        """Wire all cross-agent communication through the message bus."""
        
        # Audit trail subscribes to ALL messages
        self.bus.subscribe_all(lambda msg: self.audit.log_message(msg))

        # Safety controller subscribes to errors
        self.bus.subscribe("error", lambda msg: self.safety.handle_error(msg))
        self.bus.subscribe("warning", lambda msg: self.safety.handle_warning(msg))

        # Self-healing subscribes to errors
        self.bus.subscribe("error", lambda msg: self.self_healing.on_error(msg))

        # State updates on execution events
        self.bus.subscribe("execution", self._on_execution_message)
        self.bus.subscribe("decision", self._on_decision_message)

    def _on_execution_message(self, msg: AgentMessage):
        """Handle execution messages — update state."""
        data = msg.data
        if data.get("action") == "TRADE_OPENED":
            self.state_mgr.update(
                active_trades=self.state_mgr.state.active_trades + 1,
                current_task="Monitoring Position",
            )
        elif data.get("action") == "TRADE_CLOSED":
            active = max(0, self.state_mgr.state.active_trades - 1)
            self.state_mgr.update(active_trades=active, current_task="Scanning Market")

    def _on_decision_message(self, msg: AgentMessage):
        """Handle decision messages — save to journal."""
        data = msg.data
        self.journal.record(data)

    # ──────────────────────────────────────────────────
    # TRADING CYCLE
    # ──────────────────────────────────────────────────

    def _pre_cycle_checks(self, cycle_results: dict) -> bool:
        """Run pre-cycle safety and market checks. Returns False if cycle should skip."""
        state = self.state_mgr.state

        # Human override check
        if state.human_override in ("PAUSED", "STOPPED"):
            log.info(f"[Orchestrator] Cycle skipped — Human Override: {state.human_override}")
            return False

        # Market closed check
        state = self.state_mgr.update_market_status()
        if state.market_status == "WEEKEND":
            log.info("[Orchestrator] Cycle skipped — Market Weekend")
            self.state_mgr.update(current_task="WEEKEND_WAIT")
            return False

        if state.market_status == "CLOSED":
            log.info("[Orchestrator] Cycle skipped — Market Closed")
            self.state_mgr.update(current_task="MARKET_CLOSED_WAIT")
            return False

        # Safety check
        safety_status = self.safety.check()
        if not safety_status["allowed"]:
            log.warning(f"[Orchestrator] Cycle blocked by safety: {safety_status['reason']}")
            cycle_results["errors"].append(f"Safety block: {safety_status['reason']}")
            return False

        # Daily routine tasks
        self.daily_routine.execute_scheduled_tasks()

        return True

    def _run_symbol_cycle(self, symbol: str) -> dict:
        """
        Run the full pipeline for a single symbol.
        
        Pipeline stages:
            1. Market Analysis
            2. Technical Analysis + SMC
            3. Decision
            4. Risk Validation
            5. Execution
            6. Learning
        """
        result = {
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "stages": {},
        }

        self.state_mgr.update(current_task=f"Analyzing {symbol}", current_pair=symbol)

        # Publish cycle start on bus
        self.bus.publish(AgentMessage(
            source="orchestrator",
            msg_type="system_event",
            data={"event": "symbol_cycle_start", "symbol": symbol, "cycle": self._cycle_count},
            cycle_id=self._current_cycle_id,
        ))

        # ── Stage 1: Market Analysis ────────────────
        try:
            market_out = self._stage_market_analysis(symbol)
            result["stages"]["market"] = "OK"
            self.bus.publish(AgentMessage(
                source="market_agent",
                msg_type="market_analysis",
                data={k: v for k, v in market_out.items() if k != "df"},
                cycle_id=self._current_cycle_id,
            ))
        except Exception as e:
            log.error(f"[Orchestrator] Market analysis failed for {symbol}: {e}")
            result["stages"]["market"] = f"FAIL: {e}"
            self.bus.publish(AgentMessage(
                source="orchestrator",
                msg_type="error",
                data={"stage": "market", "symbol": symbol, "error": str(e)},
                priority="high",
                cycle_id=self._current_cycle_id,
            ))
            return result

        # ── Stage 2: Analysis ──────────────────────
        try:
            analysis_out = self._stage_analysis(market_out)
            result["stages"]["analysis"] = "OK"
        except Exception as e:
            log.error(f"[Orchestrator] Analysis failed for {symbol}: {e}")
            result["stages"]["analysis"] = f"FAIL: {e}"
            self.bus.publish(AgentMessage(
                source="orchestrator",
                msg_type="error",
                data={"stage": "analysis", "symbol": symbol, "error": str(e)},
                priority="high",
                cycle_id=self._current_cycle_id,
            ))
            return result

        # ── Stage 3: Decision ───────────────────────
        try:
            decision_out = self._stage_decision(market_out, analysis_out)
            result["stages"]["decision"] = "OK"
            result["decision"] = decision_out["decision"]
            result["confidence"] = decision_out["confidence"]

            self.bus.publish(AgentMessage(
                source="decision_agent",
                msg_type="decision",
                data={
                    "symbol": symbol,
                    "decision": decision_out["decision"],
                    "confidence": decision_out["confidence"],
                    "reasons": decision_out.get("reasons", []),
                },
                cycle_id=self._current_cycle_id,
            ))

            # Update state
            self.state_mgr.update(current_decision=decision_out["decision"])
        except Exception as e:
            log.error(f"[Orchestrator] Decision failed for {symbol}: {e}")
            result["stages"]["decision"] = f"FAIL: {e}"
            return result

        # ── Stage 4: Risk Validation ────────────────
        if decision_out["decision"] in ("BUY", "SELL"):
            try:
                risk_out = self._stage_risk_validation(market_out, analysis_out, decision_out)
                result["stages"]["risk"] = "OK"
                
                self.bus.publish(AgentMessage(
                    source="risk_agent",
                    msg_type="risk_check",
                    data={
                        "symbol": symbol,
                        "approved": risk_out.get("approved"),
                        "lot": risk_out.get("lot_size"),
                        "rr": risk_out.get("rr_ratio"),
                    },
                    cycle_id=self._current_cycle_id,
                ))
            except Exception as e:
                log.error(f"[Orchestrator] Risk validation failed: {e}")
                result["stages"]["risk"] = f"FAIL: {e}"
                return result

            # ── Stage 5: Execution ───────────────────
            if risk_out.get("approved"):
                try:
                    exec_result = self._stage_execution(symbol, decision_out, risk_out)
                    result["stages"]["execution"] = "OK"
                    result["executed"] = True
                    self._total_trades += 1
                except Exception as e:
                    log.error(f"[Orchestrator] Execution failed: {e}")
                    result["stages"]["execution"] = f"FAIL: {e}"
            else:
                result["stages"]["execution"] = "SKIPPED (risk rejected)"
                log.info(f"[Orchestrator] Trade rejected by risk: {risk_out.get('reject_reason')}")

        # ── Stage 6: Learning ───────────────────────
        try:
            self._stage_learning(market_out, analysis_out, decision_out)
            result["stages"]["learning"] = "OK"
        except Exception as e:
            log.warning(f"[Orchestrator] Learning stage error (non-critical): {e}")
            result["stages"]["learning"] = f"WARN: {e}"

        return result

    def _post_cycle_tasks(self, cycle_results: dict):
        """Tasks after processing all symbols in a cycle."""
        # Update balance from paper trader
        if self._paper_trader:
            self.balance = self._paper_trader.balance
            self.state_mgr.update(balance=self.balance)

        # Count wins/losses
        if self._paper_trader:
            stats = self._paper_trader.get_dashboard()
            self._total_wins = stats.get("wins", 0)
            self._total_losses = stats.get("losses", 0)
            daily_pnl_pct = stats.get("total_pnl_pct", 0)
            self.state_mgr.update(
                daily_pnl_pct=daily_pnl_pct,
                daily_pnl_usd=stats.get("total_pnl", 0),
            )

        # Save bus history periodically
        if self._cycle_count % 10 == 0:
            self.bus.save_history()
            self.journal.save()
            self.audit.save()

    # ──────────────────────────────────────────────────
    # PIPELINE STAGE METHODS
    # ──────────────────────────────────────────────────

    def _stage_market_analysis(self, symbol: str) -> dict:
        """Stage 1: Fetch and analyze market data."""
        agent = self._market_agent(symbol=symbol, timeframe=self.timeframe)
        return agent.run()

    def _stage_analysis(self, market_out: dict) -> dict:
        """Stage 2: Technical analysis + SMC + LLM."""
        memory_ctx = {}
        try:
            from memory.trade_memory import TradeMemory
            tm = TradeMemory(seed_rules=False)
            memory_ctx = tm.get_context_for_ai(market_out.get("symbol", "EURUSD"))
        except Exception:
            pass  # Non-critical
        return self._analysis_agent.run(market_out, memory_ctx=memory_ctx)

    def _stage_decision(self, market_out: dict, analysis_out: dict) -> dict:
        """Stage 3: Make BUY/SELL/WAIT decision."""
        risk_prelim = self._risk_agent.calculate(
            signal=analysis_out.get("final_signal", "NO TRADE"),
            entry=analysis_out.get("signal", {}).get("entry", market_out.get("ind_ctx", {}).get("close", 0)),
            ind_ctx=market_out.get("ind_ctx", {}),
            regime=market_out.get("regime", {}),
            symbol=market_out.get("symbol", "EURUSD"),
        )
        return self._decision_agent.decide(market_out, analysis_out, risk_prelim)

    def _stage_risk_validation(self, market_out: dict, analysis_out: dict, decision_out: dict) -> dict:
        """Stage 4: Final risk validation using Autonomous Risk Manager."""
        # Use basic risk agent for quick validation
        return self._risk_agent.calculate(
            signal=decision_out["decision"],
            entry=decision_out.get("entry", market_out.get("ind_ctx", {}).get("close", 0)),
            ind_ctx=market_out.get("ind_ctx", {}),
            regime=market_out.get("regime", {}),
            symbol=market_out.get("symbol", "EURUSD"),
        )

    def _stage_execution(self, symbol: str, decision_out: dict, risk_out: dict) -> dict:
        """Stage 5: Execute trade through appropriate channel."""
        signal_result = {
            "symbol": symbol,
            "final_action": decision_out["decision"],
            "entry": decision_out.get("entry"),
            "sl": decision_out.get("sl"),
            "tp": decision_out.get("tp"),
            "lot": decision_out.get("lot"),
            "confidence": decision_out.get("confidence"),
            "pattern": decision_out.get("pattern"),
            "regime": decision_out.get("regime"),
            "trend": decision_out.get("trend"),
            "rr": decision_out.get("rr"),
            "timeframe": self.timeframe,
        }

        if self.execution_mode == "paper" and self._paper_trader:
            trade = self._paper_trader.open_trade_from_signal(signal_result)
            self.bus.publish(AgentMessage(
                source="execution",
                msg_type="execution",
                data={
                    "action": "TRADE_OPENED" if trade else "TRADE_REJECTED",
                    "symbol": symbol,
                    "trade": trade,
                },
                priority="high",
                cycle_id=self._current_cycle_id,
            ))
            self.audit.log_event("trade_opened", {
                "symbol": symbol,
                "decision": decision_out["decision"],
                "entry": decision_out.get("entry"),
                "lot": decision_out.get("lot"),
                "confidence": decision_out.get("confidence"),
            })
            return {"executed": True, "trade": trade}

        return {"executed": False, "reason": f"Mode {self.execution_mode} execution not available"}

    def _stage_learning(self, market_out: dict, analysis_out: dict, decision_out: dict):
        """Stage 6: Save decision to learning system."""
        if self._learning_agent:
            self._learning_agent.save_decision(decision_out, analysis_out, market_out)

        # Update confidence engine if trade was executed
        if decision_out.get("decision") in ("BUY", "SELL") and decision_out.get("confidence_engine"):
            try:
                from learning.confidence_engine import ConfidenceEngine
                ce = ConfidenceEngine()
                ce.record_decision(
                    pattern=decision_out.get("pattern", "Unknown"),
                    pair=decision_out.get("pair", "EURUSD"),
                    timeframe=decision_out.get("timeframe", "M15"),
                    regime=decision_out.get("regime", "UNKNOWN"),
                    signal=decision_out["decision"],
                    confidence=decision_out.get("confidence", 0),
                    approved=True,
                )
            except Exception:
                pass

    # ──────────────────────────────────────────────────
    # ERROR HANDLING
    # ──────────────────────────────────────────────────

    def _handle_cycle_error(self, symbol: str, error: Exception, cycle_results: dict):
        """Handle errors during symbol cycle processing."""
        error_detail = f"{symbol}: {str(error)}"
        cycle_results["errors"].append(error_detail)
        self._errors.append({
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "symbol": symbol,
            "error": str(error),
            "traceback": traceback.format_exc(),
        })

        self.bus.publish(AgentMessage(
            source="orchestrator",
            msg_type="error",
            data={
                "stage": "cycle",
                "symbol": symbol,
                "error": str(error),
                "cycle": self._cycle_count,
            },
            priority="high",
            cycle_id=self._current_cycle_id,
        ))

        log.error(f"[Orchestrator] Cycle error for {symbol}: {error}", exc_info=True)

        # Try self-healing
        self.self_healing.heal(error)

    # ──────────────────────────────────────────────────
    # DISPLAY METHODS
    # ──────────────────────────────────────────────────

    def _print_startup_banner(self) -> None:
        bar = "=" * 55
        print()
        print(f"  {bar}")
        print("    AUTONOMOUS AI TRADING SYSTEM  v5.0")
        print("    Day 60 — Trading Orchestrator (Central Nervous System)")
        print(f"  {bar}")
        print(f"    Started : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print(f"    Symbols : {', '.join(self.symbols)}")
        print(f"    Mode    : {self.execution_mode.upper()}")
        print(f"    Timeframe: {self.timeframe}")
        print()

    def _print_startup_summary(self, report: dict) -> None:
        print(f"  {('=' * 55)}")
        for step in report["steps"]:
            icon = "OK" if step["status"] == "OK" else "FAIL"
            detail = f" — {step['detail']}" if step.get("detail") else ""
            print(f"    [{icon}] {step['name']:<35}{detail}")

        if report["warnings"]:
            print(f"\n  WARNING: {len(report['warnings'])} issue(s):")
            for w in report["warnings"]:
                print(f"    - {w}")

        print()
        print(f"  AI Trader Status: AUTONOMOUS MODE ACTIVE")
        print(f"  {'=' * 55}")
        print()

    def _print_shutdown_summary(self, report: dict) -> None:
        bar = "=" * 55
        print(f"\n  {bar}")
        print("  AI TRADING SYSTEM v5.0 — SHUTDOWN COMPLETE")
        print(bar)
        print(f"  Cycles Completed : {report['cycles_completed']}")
        print(f"  Total Trades     : {report['total_trades']}")
        print(f"  Wins / Losses    : {report['total_wins']} / {report['total_losses']}")
        if report['total_trades'] > 0:
            wr = report['total_wins'] / report['total_trades'] * 100
            print(f"  Win Rate         : {wr:.1f}%")
        print(bar)

    def get_system_status(self) -> dict:
        """Get comprehensive system status for dashboard."""
        state = self.state_mgr.state
        return {
            "running": self._running,
            "cycle_count": self._cycle_count,
            "total_trades": self._total_trades,
            "total_wins": self._total_wins,
            "total_losses": self._total_losses,
            "balance": self.balance,
            "bus_stats": self.bus.get_stats(),
            "safety_status": self.safety.get_status(),
            "state": state.to_dict(),
            "journal_stats": self.journal.get_stats(),
            "audit_stats": self.audit.get_stats(),
        }

    def print_status(self) -> None:
        """Print full system status."""
        self.state_mgr.print_dashboard()
        self.bus.print_summary()
        self.safety.print_status()
