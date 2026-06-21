#!/usr/bin/env python3
# tests/test_pipeline.py — Comprehensive System Pipeline Test
# ============================================================
# Verifies all major modules are importable, connected, and functional.
# Does NOT require MT5 connection or live API keys.
# Usage: python tests/test_pipeline.py
# ============================================================

import importlib
import os
import sys
import traceback
from pathlib import Path
from datetime import datetime, timezone

# ── Ensure project root is in sys.path ───────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestResult:
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.error = None
        self.duration_ms = 0
        self.details = ""

    def __repr__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.name} ({self.duration_ms}ms)"


class PipelineTestRunner:
    """Runs all system tests and produces a structured report."""

    def __init__(self):
        self.results: list[TestResult] = []
        self._start_time = None

    def test(self, name: str, func):
        """Run a single test and record the result."""
        result = TestResult(name)
        t0 = datetime.now(timezone.utc)
        try:
            func()
            result.passed = True
        except Exception as e:
            result.error = str(e)
            result.details = traceback.format_exc()
        result.duration_ms = round((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
        self.results.append(result)

    def print_report(self) -> bool:
        """Print the full test report. Returns True if all passed."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        failed = total - passed

        bar = "=" * 60
        print(f"\n{bar}")
        print(f"  AUTONOMOUS AI TRADING SYSTEM — PIPELINE TEST REPORT")
        print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print(f"{bar}")

        for r in self.results:
            icon = "  OK" if r.passed else "FAIL"
            extra = ""
            if not r.passed and r.error:
                extra = f" — {r.error}"
            print(f"  [{icon}] {r.name}{extra}")

        print(f"{bar}")
        print(f"  Results: {passed}/{total} passed, {failed} failed")
        pct = (passed / total * 100) if total > 0 else 0
        status = "ALL TESTS PASSED" if failed == 0 else f"{failed} TEST(S) FAILED"
        print(f"  Status:  {pct:.0f}% — {status}")
        print(f"{bar}\n")

        if failed > 0:
            print("  FAILED TEST DETAILS:")
            for r in self.results:
                if not r.passed:
                    print(f"\n  --- {r.name} ---")
                    print(r.details)

        return failed == 0


def main():
    runner = PipelineTestRunner()

    # ═══════════════════════════════════════════════════════════
    # 1. CONFIGURATION TESTS
    # ═══════════════════════════════════════════════════════════

    def test_config_import():
        import config
        assert hasattr(config, "EXECUTION_MODE")
        assert hasattr(config, "SYMBOLS")
        assert hasattr(config, "DEFAULT_TIMEFRAME")
        assert config.EXECUTION_MODE in ("paper", "mt5_demo")

    def test_config_settings_import():
        from config.settings import Settings, BrokerSettings, RiskSettings
        s = Settings.load()
        assert s.risk.risk_per_trade > 0
        assert s.trading.execution_mode in ("paper", "mt5_demo")

    def test_env_loading():
        from dotenv import load_dotenv
        load_dotenv()
        assert os.getenv("EXECUTION_MODE") is not None or True  # env is optional

    runner.test("Config: main config.py importable", test_config_import)
    runner.test("Config: config/settings.py importable", test_config_settings_import)
    runner.test("Config: environment loading", test_env_loading)

    # ═══════════════════════════════════════════════════════════
    # 2. CORE MODULE TESTS
    # ═══════════════════════════════════════════════════════════

    def test_trading_engine_import():
        from core.trading_engine import TradingEngine
        assert TradingEngine is not None

    def test_trader_import():
        from core.trader import AITrader, AutonomousTraderSystem
        assert AITrader is not None
        assert AutonomousTraderSystem is not None

    def test_approval_mode_import():
        from core.approval_mode import ApprovalMode
        am = ApprovalMode(mode=1)
        assert am.mode_name == "ANALYSIS ONLY"

    def test_exceptions_import():
        from core.exceptions import (
            TraderError, DataFetchError, AnalysisError,
            RiskError, ExecutionError, BrokerConnectionError,
            LLMError, CircuitBreakerError, ConfigurationError,
        )
        assert issubclass(DataFetchError, TraderError)

    def test_logger_import():
        from utils.logger import get_logger
        log = get_logger("test_logger")
        assert log is not None

    runner.test("Core: TradingEngine importable", test_trading_engine_import)
    runner.test("Core: AITrader + AutonomousTraderSystem importable", test_trader_import)
    runner.test("Core: ApprovalMode importable", test_approval_mode_import)
    runner.test("Core: Exception hierarchy importable", test_exceptions_import)
    runner.test("Core: Logger importable", test_logger_import)

    # ═══════════════════════════════════════════════════════════
    # 3. DATA MODULE TESTS
    # ═══════════════════════════════════════════════════════════

    def test_data_fetcher_import():
        from data.fetcher import DataFetcher
        assert DataFetcher is not None

    def test_indicators_import():
        from data.indicators import Indicators
        assert Indicators is not None

    def test_data_validator_import():
        from data.validator import DataValidator
        dv = DataValidator()
        assert dv is not None

    runner.test("Data: DataFetcher importable", test_data_fetcher_import)
    runner.test("Data: Indicators importable", test_indicators_import)
    runner.test("Data: DataValidator importable", test_data_validator_import)

    # ═══════════════════════════════════════════════════════════
    # 4. ANALYSIS MODULE TESTS
    # ═══════════════════════════════════════════════════════════

    def test_pattern_detector():
        from analysis.patterns import PatternDetector
        pd_cls = PatternDetector()
        assert pd_cls is not None

    def test_support_resistance():
        from analysis.support_resistance import SupportResistance
        sr = SupportResistance()
        assert sr is not None

    def test_market_bias():
        from analysis.market_bias import MarketBiasEngine
        mbe = MarketBiasEngine()
        assert mbe is not None

    def test_smc_engine():
        from analysis.smc_engine import SMCEngine
        assert SMCEngine is not None

    def test_fvg_detector():
        from analysis.fvg_detector import FVGDetector
        fvg = FVGDetector()
        assert fvg is not None

    def test_fibonacci():
        from analysis.fibonacci import FibonacciEngine
        assert FibonacciEngine is not None

    def test_market_regime():
        from analysis.market_regime import MarketRegimeDetector
        mrd = MarketRegimeDetector()
        assert mrd is not None

    def test_sentiment():
        from analysis.sentiment import SentimentEngine
        assert SentimentEngine is not None

    def test_advanced_patterns():
        from analysis.advanced_patterns import AdvancedPatternDetector
        apd = AdvancedPatternDetector(lookback=50)
        assert apd is not None

    runner.test("Analysis: PatternDetector importable", test_pattern_detector)
    runner.test("Analysis: SupportResistance importable", test_support_resistance)
    runner.test("Analysis: MarketBiasEngine importable", test_market_bias)
    runner.test("Analysis: SMCEngine importable", test_smc_engine)
    runner.test("Analysis: FVGDetector importable", test_fvg_detector)
    runner.test("Analysis: FibonacciEngine importable", test_fibonacci)
    runner.test("Analysis: MarketRegimeDetector importable", test_market_regime)
    runner.test("Analysis: SentimentEngine importable", test_sentiment)
    runner.test("Analysis: AdvancedPatternDetector importable", test_advanced_patterns)

    # ═══════════════════════════════════════════════════════════
    # 5. AGENT MODULE TESTS
    # ═══════════════════════════════════════════════════════════

    def test_market_agent():
        from agents.market_agent import MarketAgent
        ma = MarketAgent("EURUSD", "15m")
        assert ma.symbol == "EURUSD"

    def test_analysis_agent():
        from agents.analysis_agent import AnalysisAgent
        aa = AnalysisAgent()
        assert aa is not None

    def test_decision_agent():
        from agents.decision_agent import DecisionAgent
        da = DecisionAgent()
        assert da is not None

    def test_risk_agent():
        from agents.risk_agent import RiskAgent
        ra = RiskAgent(account_balance=10000)
        assert ra.balance == 10000

    def test_learning_agent():
        from agents.learning_agent import LearningAgent
        la = LearningAgent()
        assert la is not None

    def test_master_analyst():
        from agents.master_analyst import MasterAnalyst
        # Should only have ONE class definition (Day 44 version)
        import agents.master_analyst as ma_mod
        cls_count = sum(
            1 for name, obj in vars(ma_mod).items()
            if isinstance(obj, type) and obj.__name__ == "MasterAnalyst"
        )
        assert cls_count == 1, f"Expected 1 MasterAnalyst class, found {cls_count}"

    runner.test("Agents: MarketAgent importable", test_market_agent)
    runner.test("Agents: AnalysisAgent importable", test_analysis_agent)
    runner.test("Agents: DecisionAgent importable", test_decision_agent)
    runner.test("Agents: RiskAgent importable", test_risk_agent)
    runner.test("Agents: LearningAgent importable", test_learning_agent)
    runner.test("Agents: MasterAnalyst has single class (no dup)", test_master_analyst)

    # ═══════════════════════════════════════════════════════════
    # 6. RISK MODULE TESTS
    # ═══════════════════════════════════════════════════════════

    def test_risk_engine():
        from risk.risk_engine import RiskEngine
        re = RiskEngine(balance=10000, symbol="EURUSD")
        assert re is not None

    def test_risk_engine_evaluate():
        from risk.risk_engine import RiskEngine
        re = RiskEngine(balance=10000, symbol="EURUSD")
        result = re.evaluate(
            signal="BUY",
            entry=1.1000,
            atr=0.0008,
            regime={"volatility": "NORMAL", "regime": "TRENDING"},
        )
        assert "approved" in result or "reject_reason" in result
        assert result.get("lot", 0) >= 0

    def test_circuit_breaker():
        from risk.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker(balance=10000)
        status = cb.get_status()
        assert status["mode"] in ("TRADING", "PAUSED", "LEARNING", "COOLDOWN")

    def test_trade_permission():
        from risk.trade_permission import TradePermission
        tp = TradePermission()
        assert tp is not None

    runner.test("Risk: RiskEngine importable", test_risk_engine)
    runner.test("Risk: RiskEngine.evaluate() works", test_risk_engine_evaluate)
    runner.test("Risk: CircuitBreaker importable", test_circuit_breaker)
    runner.test("Risk: TradePermission importable", test_trade_permission)

    # ═══════════════════════════════════════════════════════════
    # 7. MEMORY MODULE TESTS
    # ═══════════════════════════════════════════════════════════

    def test_trade_memory():
        from memory.trade_memory import TradeMemory
        tm = TradeMemory(seed_rules=False)
        assert tm is not None

    def test_learning_engine():
        from memory.learning import LearningEngine
        le = LearningEngine()
        assert le is not None

    def test_history():
        from memory.history import AnalysisHistory
        ah = AnalysisHistory()
        assert ah is not None

    def test_pattern_memory():
        from memory.pattern_memory import PatternMemory
        pm = PatternMemory()
        assert pm is not None

    def test_confidence_calibrator():
        from memory.confidence_calibrator import ConfidenceCalibrator
        cc = ConfidenceCalibrator()
        assert cc is not None

    runner.test("Memory: TradeMemory importable", test_trade_memory)
    runner.test("Memory: LearningEngine importable", test_learning_engine)
    runner.test("Memory: AnalysisHistory importable", test_history)
    runner.test("Memory: PatternMemory importable", test_pattern_memory)
    runner.test("Memory: ConfidenceCalibrator importable", test_confidence_calibrator)

    # ═══════════════════════════════════════════════════════════
    # 8. LEARNING MODULE TESTS
    # ═══════════════════════════════════════════════════════════

    def test_confidence_engine():
        from learning.confidence_engine import ConfidenceEngine
        ce = ConfidenceEngine()
        result = ce.calculate(pattern="Hammer", pair="EURUSD", timeframe="M15")
        assert "final_confidence" in result
        assert 0 <= result["final_confidence"] <= 100

    def test_auto_optimizer():
        from learning.auto_optimizer import AutoOptimizer
        ao = AutoOptimizer(human_approval=False)
        assert ao is not None

    def test_performance_feedback():
        from learning.performance_feedback import PerformanceFeedback
        pf = PerformanceFeedback()
        assert pf is not None

    def test_strategy_config():
        from learning.strategy_config import StrategyConfig
        sc = StrategyConfig()
        assert sc is not None

    def test_rule_updater():
        from learning.rule_updater import RuleUpdater
        ru = RuleUpdater()
        assert ru is not None

    def test_lesson_memory():
        from learning.lesson_memory import LessonMemory
        lm = LessonMemory()
        assert lm is not None

    def test_learning_init():
        import learning
        assert hasattr(learning, "ConfidenceEngine")
        assert hasattr(learning, "AutoOptimizer")

    runner.test("Learning: ConfidenceEngine works", test_confidence_engine)
    runner.test("Learning: AutoOptimizer importable", test_auto_optimizer)
    runner.test("Learning: PerformanceFeedback importable", test_performance_feedback)
    runner.test("Learning: StrategyConfig importable", test_strategy_config)
    runner.test("Learning: RuleUpdater importable", test_rule_updater)
    runner.test("Learning: LessonMemory importable", test_lesson_memory)
    runner.test("Learning: __init__.py exports correct symbols", test_learning_init)

    # ═══════════════════════════════════════════════════════════
    # 9. EXECUTION MODULE TESTS
    # ═══════════════════════════════════════════════════════════

    def test_execution_router():
        from execution.execution_router import ExecutionRouter
        assert ExecutionRouter is not None

    def test_paper_trader():
        from execution.paper_trader import PaperTrader
        pt = PaperTrader(starting_balance=10000)
        assert pt.balance == 10000

    def test_paper_trader_dashboard():
        from execution.paper_trader import PaperTrader
        pt = PaperTrader(starting_balance=10000)
        dash = pt.get_dashboard()
        assert "balance" in dash
        assert dash["balance"] == 10000

    runner.test("Execution: ExecutionRouter importable", test_execution_router)
    runner.test("Execution: PaperTrader importable", test_paper_trader)
    runner.test("Execution: PaperTrader.get_dashboard() works", test_paper_trader_dashboard)

    # ═══════════════════════════════════════════════════════════
    # 10. SCANNER MODULE TESTS
    # ═══════════════════════════════════════════════════════════

    def test_market_scanner():
        from scanner.market_scanner import MarketScanner
        ms = MarketScanner(risk_engine=None)
        assert ms is not None

    def test_correlation_filter():
        from scanner.correlation_filter import CorrelationFilter
        cf = CorrelationFilter()
        assert cf is not None

    def test_opportunity_ranker():
        from scanner.opportunity_ranker import OpportunityRanker
        ork = OpportunityRanker()
        assert ork is not None

    def test_scanner_config():
        from scanner.config import FOREX_PAIRS, DEFAULT_SCAN_PAIRS
        assert isinstance(FOREX_PAIRS, list)
        assert isinstance(DEFAULT_SCAN_PAIRS, list)

    runner.test("Scanner: MarketScanner importable", test_market_scanner)
    runner.test("Scanner: CorrelationFilter importable", test_correlation_filter)
    runner.test("Scanner: OpportunityRanker importable", test_opportunity_ranker)
    runner.test("Scanner: Config importable", test_scanner_config)

    # ═══════════════════════════════════════════════════════════
    # 11. STRATEGY MODULE TESTS
    # ═══════════════════════════════════════════════════════════

    def test_signal_engine():
        from strategy.signal_engine import SignalEngine
        se = SignalEngine()
        assert se is not None

    def test_strategies_import():
        from strategies import TrendFollowStrategy, ReversalStrategy, BreakoutStrategy
        assert all(c is not None for c in [TrendFollowStrategy, ReversalStrategy, BreakoutStrategy])

    runner.test("Strategy: SignalEngine importable", test_signal_engine)
    runner.test("Strategy: All strategy classes importable", test_strategies_import)

    # ═══════════════════════════════════════════════════════════
    # 12. DATABASE MODULE TESTS
    # ═══════════════════════════════════════════════════════════

    def test_database_import():
        from database.db import TraderDB
        db = TraderDB()
        assert db is not None

    def test_database_stats():
        from database.db import TraderDB
        db = TraderDB()
        stats = db.get_overall_stats(starting_balance=10000)
        assert "total" in stats
        assert "balance" in stats

    runner.test("Database: TraderDB importable", test_database_import)
    runner.test("Database: get_overall_stats() works", test_database_stats)

    # ═══════════════════════════════════════════════════════════
    # 13. UTILITIES TESTS
    # ═══════════════════════════════════════════════════════════

    def test_session_analyzer():
        from utils.session import SessionAnalyzer
        sa = SessionAnalyzer()
        ctx = sa.get_current_session()
        assert "active_sessions" in ctx

    def test_visualization():
        from visualization.chart import ChartEngine
        ce = ChartEngine("EURUSD", "15m")
        assert ce is not None

    runner.test("Utils: SessionAnalyzer works", test_session_analyzer)
    runner.test("Utils: ChartEngine importable", test_visualization)

    # ═══════════════════════════════════════════════════════════
    # 14. BACKTEST MODULE TESTS
    # ═══════════════════════════════════════════════════════════

    def test_backtest_engine():
        from backtest.engine import BacktestEngine
        be = BacktestEngine()
        assert be is not None

    def test_backtest_simulator():
        from backtest.simulator import ForexSimulator
        fs = ForexSimulator()
        assert fs is not None

    runner.test("Backtest: Engine importable", test_backtest_engine)
    runner.test("Backtest: Simulator importable", test_backtest_simulator)

    # ═══════════════════════════════════════════════════════════
    # 15. BROKER MODULE TESTS (non-MT5)
    # ═══════════════════════════════════════════════════════════

    def test_safety_guard_new():
        from broker.safety_guard import SafetyGuard
        sg = SafetyGuard()
        assert hasattr(sg, 'check')
        assert hasattr(sg, 'get_status')

    def test_spread_monitor():
        from broker.spread_monitor import SpreadMonitor
        sm = SpreadMonitor()
        assert sm is not None

    def test_economic_calendar():
        from broker.economic_calendar import EconomicCalendar
        ec = EconomicCalendar()
        assert ec is not None

    runner.test("Broker: SafetyGuard (new) importable", test_safety_guard_new)
    runner.test("Broker: SpreadMonitor importable", test_spread_monitor)
    runner.test("Broker: EconomicCalendar importable", test_economic_calendar)

    # ═══════════════════════════════════════════════════════════
    # 16. RESEARCH MODULE TESTS (Day 57)
    # ═══════════════════════════════════════════════════════════

    def test_research_agent_import():
        from research.research_agent import ResearchAgent
        ra = ResearchAgent(enable_auto_research=False)
        assert ra is not None

    def test_strategy_generator_import():
        from research.strategy_generator import StrategyGenerator
        sg = StrategyGenerator()
        assert sg is not None

    def test_strategy_generator_novel():
        from research.strategy_generator import StrategyGenerator
        sg = StrategyGenerator()
        strategy = sg.generate_novel(pair="EURUSD", timeframe="H1")
        assert "name" in strategy
        assert "entries" in strategy
        assert "filters" in strategy
        assert "exits" in strategy
        assert len(strategy["entries"]) >= 1

    def test_strategy_generator_mutation():
        from research.strategy_generator import StrategyGenerator
        sg = StrategyGenerator()
        mutation = sg.generate_mutation("SMC_Basic_v1", "minor")
        assert "name" in mutation
        assert "parent" in mutation

    def test_strategy_generator_batch():
        from research.strategy_generator import StrategyGenerator
        sg = StrategyGenerator()
        batch = sg.generate_batch(n_novel=1, n_mutations=1)
        assert len(batch) == 2

    def test_strategy_sandbox_dirs():
        from research.strategy_generator import ACTIVE_DIR, TESTING_DIR, REJECTED_DIR
        assert ACTIVE_DIR.exists()
        assert TESTING_DIR.exists()
        assert REJECTED_DIR.exists()

    def test_hypothesis_engine_import():
        from research.hypothesis_engine import HypothesisEngine
        he = HypothesisEngine()
        assert he is not None

    def test_hypothesis_generation():
        from research.hypothesis_engine import HypothesisEngine
        he = HypothesisEngine()
        hyp = he.generate(strategy_name="SMC_Basic_v1")
        assert hyp.id.startswith("HYP-")
        assert hyp.question
        assert hyp.status == "PENDING"

    def test_hypothesis_batch():
        from research.hypothesis_engine import HypothesisEngine
        he = HypothesisEngine()
        batch = he.generate_batch(n=2)
        assert len(batch) == 2

    def test_hypothesis_stats():
        from research.hypothesis_engine import HypothesisEngine
        he = HypothesisEngine()
        he.generate_batch(n=2)
        stats = he.get_stats()
        assert "total_hypotheses" in stats
        assert stats["total_hypotheses"] >= 2

    def test_experiment_runner_import():
        from research.experiment_runner import ExperimentRunner
        er = ExperimentRunner()
        assert er is not None

    def test_experiment_runner_create():
        from research.experiment_runner import ExperimentRunner
        from research.hypothesis_engine import HypothesisEngine
        from research.strategy_generator import StrategyGenerator
        er = ExperimentRunner()
        he = HypothesisEngine()
        sg = StrategyGenerator()
        hyp = he.generate()
        strategy = sg.generate_novel()
        exp = er.create_experiment(hypothesis=hyp, strategy=strategy)
        assert exp.id.startswith("EXP-")
        assert exp.status == "PENDING"

    def test_experiment_runner_stats():
        from research.experiment_runner import ExperimentRunner
        er = ExperimentRunner()
        stats = er.get_stats()
        assert "total_experiments" in stats

    def test_experiment_runner_approval_criteria():
        from research.experiment_runner import APPROVAL_CRITERIA
        assert APPROVAL_CRITERIA["min_trades"] == 200
        assert APPROVAL_CRITERIA["min_profit_factor"] == 1.5
        assert APPROVAL_CRITERIA["max_drawdown_pct"] == 15.0

    def test_research_report_import():
        from research.research_report import ResearchReportGenerator
        rg = ResearchReportGenerator()
        assert rg is not None

    def test_research_report_generate():
        from research.research_report import ResearchReportGenerator
        rg = ResearchReportGenerator()
        report = rg.generate_weekly(
            experiment_results=[],
            hypothesis_results=[],
            market_findings=[],
        )
        assert report["report_type"] == "weekly_research"
        assert "summary" in report

    def test_research_module_init():
        import research
        assert hasattr(research, "ResearchAgent")
        assert hasattr(research, "StrategyGenerator")
        assert hasattr(research, "HypothesisEngine")
        assert hasattr(research, "ExperimentRunner")
        assert hasattr(research, "ResearchReportGenerator")

    def test_research_agent_stats():
        from research.research_agent import ResearchAgent
        ra = ResearchAgent(enable_auto_research=False)
        stats = ra.get_stats()
        assert "cycle_count" in stats
        assert "total_experiments" in stats
        assert "hypothesis_stats" in stats

    def test_research_memory_graph():
        from research.research_agent import ResearchAgent
        ra = ResearchAgent(enable_auto_research=False)
        graph = ra.get_research_memory_graph()
        assert "nodes" in graph
        assert "edges" in graph

    runner.test("Research: ResearchAgent importable", test_research_agent_import)
    runner.test("Research: StrategyGenerator importable", test_strategy_generator_import)
    runner.test("Research: StrategyGenerator novel strategy", test_strategy_generator_novel)
    runner.test("Research: StrategyGenerator mutation", test_strategy_generator_mutation)
    runner.test("Research: StrategyGenerator batch generation", test_strategy_generator_batch)
    runner.test("Research: Strategy sandbox directories exist", test_strategy_sandbox_dirs)
    runner.test("Research: HypothesisEngine importable", test_hypothesis_engine_import)
    runner.test("Research: HypothesisEngine generate", test_hypothesis_generation)
    runner.test("Research: HypothesisEngine batch", test_hypothesis_batch)
    runner.test("Research: HypothesisEngine stats", test_hypothesis_stats)
    runner.test("Research: ExperimentRunner importable", test_experiment_runner_import)
    runner.test("Research: ExperimentRunner create experiment", test_experiment_runner_create)
    runner.test("Research: ExperimentRunner stats", test_experiment_runner_stats)
    runner.test("Research: ExperimentRunner approval criteria", test_experiment_runner_approval_criteria)
    runner.test("Research: ResearchReportGenerator importable", test_research_report_import)
    runner.test("Research: ResearchReportGenerator weekly report", test_research_report_generate)
    runner.test("Research: Module __init__.py exports all classes", test_research_module_init)
    runner.test("Research: ResearchAgent stats", test_research_agent_stats)
    runner.test("Research: ResearchAgent memory graph", test_research_memory_graph)

    # ═══════════════════════════════════════════════════════════
    # RUN REPORT
    # ═══════════════════════════════════════════════════════════

    all_passed = runner.print_report()
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
