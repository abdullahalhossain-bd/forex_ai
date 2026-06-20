# core/trader.py  —  Day 37 | Full Integration (Week 3 + Day 31 + Day 36 wired in)
#
# Changes vs the Day 21 version:
#   - AITrader now routes every order through ExecutionRouter (paper / mt5_demo)
#     instead of calling PaperTrader directly, so EXECUTION_MODE in .env
#     actually switches backends without touching this file again.
#   - CircuitBreaker (kill switch) and ApprovalMode (Mode 1/2/3 human approval)
#     are real gates in run_cycle() now, not just standalone unused modules.
#   - CorrelationFilter is folded into the Safety Guard step alongside the
#     existing TradePermission checks (news/confidence/session/duplicate).
#   - AutonomousTraderSystem can pull its per-cycle pair list from
#     MarketScanner instead of a fixed SYMBOLS list (falls back safely if
#     the MT5 market-data adapter isn't wired yet).
#   - CircuitBreaker + ApprovalMode are created ONCE in AutonomousTraderSystem
#     and shared across every symbol's AITrader — both persist to a single
#     global state file (memory/circuit_breaker_state.json,
#     memory/pending_approvals.json), so per-symbol instances would silently
#     stomp on each other's state. Standalone AITrader usage still works:
#     if you don't pass one in, it creates its own.

import asyncio
import json
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agents.analysis_agent import AnalysisAgent
from agents.decision_agent import DecisionAgent
from agents.learning_agent import LearningAgent
from agents.market_agent import MarketAgent
from config import EXECUTION_MODE
from core.approval_mode import ApprovalMode
from database.db import TraderDB
from execution.execution_router import ExecutionRouter
from execution.paper_trader import PaperTrader
from memory.history import AnalysisHistory
from memory.learning import LearningEngine
from memory.trade_memory import TradeMemory
from risk.circuit_breaker import CircuitBreaker
from risk.risk_engine import RiskEngine
from risk.trade_permission import TradePermission
from scanner.correlation_filter import CorrelationFilter
from utils.logger import get_logger
from utils.session import SessionAnalyzer
from visualization.chart import ChartEngine

try:
    import alerts.telegram_bot as telegram_module
    from alerts.telegram_bot import TelegramNotifier, start_telegram_bot_polling
except Exception:
    telegram_module = None
    TelegramNotifier = None
    start_telegram_bot_polling = None

try:
    from learning.mistake_analyzer import AdvancedMistakeAnalyzer
except Exception:
    AdvancedMistakeAnalyzer = None

try:
    from scanner.market_scanner import MarketScanner
except Exception:
    MarketScanner = None

log = get_logger("ai_trader")


class AITrader:

    VERSION = "Week3-Day21"

    def __init__(
        self,
        balance: float = 10000.0,
        symbol: str = "EURUSD",
        timeframe: str = "15m",
        seed_rules: bool = True,
        paper_balance: float = 10000.0,
        notifier=None,
        execution_mode: str = None,
        approval_mode: int = 3,
        circuit_breaker: CircuitBreaker = None,
        approval: ApprovalMode = None,
    ):
        self.balance = balance
        self.symbol = self._clean_symbol(symbol)
        self.timeframe = timeframe
        self.notifier = notifier
        self.execution_mode = (execution_mode or EXECUTION_MODE).lower()
        self._last_decision_candle = None

        self._market = MarketAgent(self.symbol, timeframe)
        self._analysis = AnalysisAgent()
        self._decision = DecisionAgent()
        self._risk = RiskEngine(balance=balance, symbol=self.symbol)
        self._perm = TradePermission()
        self._learn = LearningAgent()
        self._memory = TradeMemory(seed_rules=seed_rules)
        self._learning = LearningEngine()
        self._db = TraderDB()
        self._paper = PaperTrader(starting_balance=paper_balance, db=self._db)
        self._mistake_analyzer = AdvancedMistakeAnalyzer() if AdvancedMistakeAnalyzer else None

        # Day 37 wiring — execution router shares THIS instance's PaperTrader
        # so paper-mode balance never drifts between router and trader.
        self._router = ExecutionRouter(
            mode=self.execution_mode, db=self._db, paper_trader=self._paper
        )
        # Circuit breaker / approval mode are global state (single JSON file
        # each) — accept a shared instance from AutonomousTraderSystem, or
        # make a private one if this AITrader is used standalone.
        self._circuit_breaker = circuit_breaker or CircuitBreaker(balance=balance)
        self._approval = approval or ApprovalMode(mode=approval_mode)
        self._corr_filter = CorrelationFilter()

        log.info(
            f"AITrader {self.VERSION} | {self.symbol} {timeframe} | "
            f"Mode: {self.execution_mode.upper()} | Approval: {self._approval.mode_name} | "
            f"Risk Balance: ${balance} | Paper Balance: ${self._paper.balance}"
        )

    def get_signal(self, show_chart: bool = False, auto_paper_trade: bool = True) -> dict:
        return self.run_cycle(show_chart=show_chart, auto_paper_trade=auto_paper_trade)

    def run_cycle(self, show_chart: bool = False, auto_paper_trade: bool = True) -> dict:
        log.info("━" * 52)
        log.info(f"  AITrader {self.VERSION} — {self.symbol} {self.timeframe}")
        log.info("━" * 52)
        t0 = time.time()

        session_ctx = SessionAnalyzer().get_current_session()
        latest_price = None

        log.info("[1/9] Market Agent...")
        market_out = self._market.run()
        if "error" in market_out:
            return self._error_result(f"Market Agent: {market_out['error']}")

        ind = market_out.get("ind_ctx", {})
        latest_price = ind.get("close")
        candle_time = self._extract_candle_time(market_out)
        closed_now = []

        if auto_paper_trade and latest_price:
            closed_now = self._paper.update_price(self.symbol, latest_price)
        closed_processed = self._process_closed_trades(closed_now)

        # [2/9] Circuit Breaker Gate — existing positions above still get
        # monitored (SL/TP/timeout) even while tripped; only NEW entries block.
        log.info("[2/9] Circuit Breaker Gate...")
        self._circuit_breaker.reset_daily()
        cb_check = self._circuit_breaker.allow_trade()
        if not cb_check["allowed"]:
            log.warning(f"[CircuitBreaker] {cb_check['mode']} — {cb_check['reason']}")
            result = self._monitor_only_result(
                price=latest_price,
                candle_time=candle_time,
                session_ctx=session_ctx,
                elapsed=round(time.time() - t0, 1),
                closed_trades=closed_processed,
            )
            result["reject_reason"] = f"Circuit breaker [{cb_check['mode']}]: {cb_check['reason']}"
            self._print_final(result)
            return result

        if candle_time and candle_time == self._last_decision_candle:
            result = self._monitor_only_result(
                price=latest_price,
                candle_time=candle_time,
                session_ctx=session_ctx,
                elapsed=round(time.time() - t0, 1),
                closed_trades=closed_processed,
            )
            self._print_final(result)
            return result

        self._last_decision_candle = candle_time

        log.info("[3/9] Analysis Agent...")
        analysis_out = self._analysis.run(market_out)
        if "error" in analysis_out:
            return self._error_result(f"Analysis Agent: {analysis_out['error']}")

        memory_ctx = self._memory.get_context_for_ai(self.symbol)
        pattern = self._extract_pattern(market_out)
        regime_str = market_out.get("regime", {}).get("regime", "")
        pat_ctx = self._memory.get_pattern_context(self.symbol, regime_str, pattern)

        if memory_ctx["total_trades"] > 0:
            log.info(
                f"[Memory] Trades: {memory_ctx['total_trades']} | "
                f"WR: {memory_ctx['overall_win_rate']}% | "
                f"Pattern wins: {pat_ctx.get('similar_wins', 0)} | "
                f"losses: {pat_ctx.get('similar_losses', 0)}"
            )
            if pat_ctx.get("warning"):
                log.info("[Memory] Warning: similar setups produced more losses than wins")

        vec_ctx = self._memory.get_vector_context(
            {
                "pair": self.symbol,
                "trend": ind.get("trend"),
                "rsi": ind.get("rsi"),
                "pattern": pattern,
                "regime": regime_str,
            }
        )

        log.info("[4/9] Decision Agent...")
        entry = analysis_out["signal"].get("entry") or ind.get("close", 0)
        placeholder_risk = {
            "approved": analysis_out["final_signal"] in ("BUY", "SELL"),
            "lot": 0,
            "sl_pips": 0,
            "tp_pips": 0,
            "rr_ratio": 0,
            "reject_reason": None,
        }
        dec_out = self._decision.decide(market_out, analysis_out, placeholder_risk)
        self._decision.print_summary(dec_out)

        log.info("[5/9] Risk Engine...")
        risk_out = self._risk.evaluate(
            signal=dec_out["decision"],
            entry=entry,
            atr=ind.get("atr", 0.0005),
            regime=market_out["regime"],
        )
        self._risk.print_summary(risk_out)

        daily = self._risk.get_daily_summary()
        log.info(
            f"Daily PnL — Net: ${daily['net_usd']} | "
            f"Loss: {daily['daily_loss_pc']}% | "
            f"Limit left: {daily['limit_remaining_pc']}%"
        )

        log.info("[6/9] Safety Guard (Permission + Correlation)...")
        perm_out = self._perm.check(
            decision_out=dec_out,
            risk_out=risk_out,
            news_ctx=analysis_out.get("news_ctx", {}),
            session_ctx=self._session_permission_context(session_ctx),
        )

        if self._paper.has_open_position(self.symbol, perm_out.get("final_action")):
            perm_out["allowed"] = False
            perm_out["final_action"] = "NO TRADE"
            perm_out["checks"].append(
                {
                    "check": "Duplicate trade",
                    "passed": False,
                    "detail": f"{self.symbol} {dec_out.get('decision')} already open",
                }
            )

        # Correlation check — same underlying-risk group already has an open
        # position (e.g. EURUSD BUY blocks a fresh GBPUSD BUY). Lot size, SL
        # distance, and daily loss are already enforced inside RiskEngine
        # above; news/confidence/session/duplicate are TradePermission above;
        # this is the last piece of the Day 37 "Safety Guard" checklist.
        if perm_out["allowed"]:
            open_pairs = [t.get("pair") for t in self._paper.get_open_positions()]
            self._corr_filter.sync_open(open_pairs)
            still_allowed = self._corr_filter.allow(
                [{"symbol": self.symbol, "signal": perm_out["final_action"]}]
            )
            if not still_allowed:
                perm_out["allowed"] = False
                perm_out["final_action"] = "NO TRADE"
                perm_out["checks"].append(
                    {
                        "check": "Correlation filter",
                        "passed": False,
                        "detail": "Correlated pair group already has an open position",
                    }
                )

        self._perm.print_summary(perm_out)

        log.info("[7/9] Learning Agent...")
        self._learn.save_decision(dec_out, analysis_out, market_out)
        stats = self._learn.get_performance_stats()

        self._save_all(market_out, analysis_out, risk_out, dec_out, perm_out)

        elapsed = round(time.time() - t0, 1)
        result = self._build_result(
            market_out,
            analysis_out,
            dec_out,
            risk_out,
            perm_out,
            stats,
            elapsed,
            session_ctx=session_ctx,
            candle_time=candle_time,
            closed_trades=closed_processed,
        )

        trade_id = self._memory.on_signal_generated(result, market_out, analysis_out)
        if trade_id:
            result["trade_id"] = trade_id
            log.info(f"[Memory] Trade #{trade_id} saved")

        result["memory_context"] = vec_ctx
        result["pattern_context"] = pat_ctx
        result["approval_mode"] = self._approval.mode_name

        log.info("[8/9] Approval Gate...")
        approved_to_execute = False
        if auto_paper_trade and result["trade_allowed"]:
            approval_out = self._approval.process(
                {
                    "symbol": self.symbol,
                    "final_action": result["final_action"],
                    "confidence": result["confidence"],
                    "entry": result["entry"],
                    "sl": result["sl"],
                    "tp": result["tp"],
                    "lot": result["lot"],
                    "rr": result["rr"],
                    "llm_analysis": result.get("llm_analysis", ""),
                }
            )
            approved_to_execute = approval_out["proceed"]

            if approval_out["action"] == "WAIT_APPROVAL":
                result["pending_approval_id"] = approval_out.get("pending_id")
                # ApprovalMode.process() builds the human-readable summary but
                # can't safely send it itself (its telegram_bot.send_message()
                # call would be an un-awaited coroutine) — send it the same
                # async-safe way every other Telegram alert goes out below.
                if self.notifier:
                    self._run_async(self.notifier.send_message(approval_out["message"]))

            if not approved_to_execute:
                result["reject_reason"] = approval_out.get("message", result.get("reject_reason"))

        log.info("[9/9] Execution + Alerts...")
        if approved_to_execute:
            trade = self._router.execute(
                {
                    "decision": result["final_action"],
                    "symbol": self.symbol,
                    "entry": result["entry"],
                    "sl": result["sl"],
                    "tp": result["tp"],
                    "lot": result["lot"],
                    "confidence": result["confidence"],
                    "rr": result["rr"],
                    "timeframe": self.timeframe,
                }
            )
            if trade:
                result["paper_trade_id"] = trade.get("id")
                result["paper_balance"] = self._paper.balance
                self._risk.record_trade_open(self.symbol)
                self._notify_trade_open(trade, result, dec_out)

        if show_chart:
            ChartEngine(self.symbol, self.timeframe).create_full_chart(
                df=market_out["df"],
                support_zones=analysis_out["sr_result"]["support_zones"],
                resistance_zones=analysis_out["sr_result"]["resistance_zones"],
                patterns_df=market_out["df"],
                show=True,
                save_html="data/chart.html",
            )

        self._print_final(result)
        return result

    def monitor_open_trades(self, price: float = None) -> list[dict]:
        if price is None:
            market_out = self._market.run()
            price = market_out.get("ind_ctx", {}).get("close")
            if price is None:
                log.warning("[PaperTrader] No price available to check open trades")
                return []
        closed_now = self._paper.update_price(self.symbol, price)
        return self._process_closed_trades(closed_now)

    def check_open_paper_trades(self, price: float = None) -> list[dict]:
        return self.monitor_open_trades(price=price)

    def close_trade(self, trade_id: int, result: str, pnl: float):
        self._memory.on_trade_closed(trade_id, result, pnl)
        self._risk.record_trade_close(self.symbol, pnl)
        self._circuit_breaker.record_result(result, pnl)
        log.info(f"Trade #{trade_id} closed: {result} | PnL: ${pnl}")

    def get_paper_dashboard(self) -> dict:
        return self._paper.get_dashboard()

    def print_paper_dashboard(self) -> None:
        self._paper.print_dashboard()

    def get_learning_report(self):
        self._learning.print_report()

    def get_memory_stats(self):
        self._memory.print_stats()

    def sync_risk_with_open_positions(self) -> None:
        open_pairs = [trade.get("pair") for trade in self._paper.get_open_positions()]
        self._risk.sync_open_positions(open_pairs)

    def _process_closed_trades(self, closed_now: list[dict]) -> list[dict]:
        processed = []
        for trade in closed_now:
            context = trade.get("context") or {}
            memory_trade_id = context.get("memory_trade_id")
            rr_ratio = context.get("rr_ratio") or trade.get("rr_ratio", 0)
            trade["rr_ratio"] = rr_ratio

            self._risk.record_trade_close(trade["pair"], trade["pnl"])
            self._circuit_breaker.record_result(trade["result"], trade["pnl"])

            if memory_trade_id:
                try:
                    self._memory.on_trade_closed(memory_trade_id, trade["result"], trade["pnl"])
                    if self._mistake_analyzer:
                        self._mistake_analyzer.analyze_closed_trade(memory_trade_id)
                except Exception as e:
                    log.warning(f"[Learning] Close sync failed for memory trade #{memory_trade_id}: {e}")

            self._notify_trade_close(trade)
            processed.append(trade)

        return processed

    def _monitor_only_result(
        self,
        price: float,
        candle_time: str | None,
        session_ctx: dict,
        elapsed: float,
        closed_trades: list[dict],
    ) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "version": self.VERSION,
            "elapsed_sec": elapsed,
            "price": price,
            "trend": None,
            "rsi": None,
            "regime": None,
            "volatility": None,
            "mtf_bias": None,
            "rule_signal": None,
            "rule_conf": 0,
            "llm_signal": None,
            "llm_conf": 0,
            "llm_analysis": "",
            "llm_risk": "",
            "news_safe": True,
            "news_reason": "",
            "decision": "WAIT",
            "confidence": 0,
            "trade_allowed": False,
            "final_action": "WAIT",
            "entry": None,
            "sl": None,
            "tp": None,
            "sl_pips": 0,
            "tp_pips": 0,
            "lot": 0,
            "rr": 0,
            "risk_usd": 0,
            "reject_reason": "One decision already taken for this candle",
            "total_decisions": 0,
            "win_rate": "N/A",
            "session": self._format_session_label(session_ctx),
            "decision_candle": candle_time,
            "closed_trades": closed_trades,
            "monitor_only": True,
            "approval_mode": self._approval.mode_name,
        }

    def _build_result(
        self,
        market_out,
        analysis_out,
        dec_out,
        risk_out,
        perm_out,
        stats,
        elapsed,
        session_ctx: dict | None = None,
        candle_time: str | None = None,
        closed_trades: list[dict] | None = None,
    ):
        ind = market_out["ind_ctx"]
        regime = market_out["regime"]
        signal = analysis_out.get("signal", {})
        llm = analysis_out.get("llm", {})
        news = analysis_out.get("news", {})

        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "version": self.VERSION,
            "elapsed_sec": elapsed,
            "price": ind.get("close"),
            "trend": ind.get("trend"),
            "rsi": ind.get("rsi"),
            "regime": regime.get("regime"),
            "volatility": regime.get("volatility"),
            "mtf_bias": market_out.get("mtf_bias"),
            "rule_signal": signal.get("signal"),
            "rule_conf": signal.get("confidence"),
            "llm_signal": llm.get("signal"),
            "llm_conf": llm.get("confidence"),
            "llm_analysis": llm.get("analysis", ""),
            "llm_risk": llm.get("key_risk", ""),
            "news_safe": news.get("trade_allowed", True),
            "news_reason": news.get("reason", ""),
            "decision": dec_out.get("decision"),
            "confidence": dec_out.get("confidence"),
            "trade_allowed": perm_out["allowed"],
            "final_action": perm_out["final_action"],
            "entry": risk_out.get("entry"),
            "sl": risk_out.get("sl_price"),
            "tp": risk_out.get("tp_price"),
            "sl_pips": risk_out.get("sl_pips", 0),
            "tp_pips": risk_out.get("tp_pips", 0),
            "lot": risk_out.get("lot", 0),
            "rr": risk_out.get("rr_ratio", 0),
            "risk_usd": risk_out.get("risk_usd", 0),
            "reject_reason": risk_out.get("reject_reason")
            or (
                None
                if perm_out["allowed"]
                else next((c["detail"] for c in perm_out["checks"] if not c["passed"]), None)
            ),
            "total_decisions": stats.get("total_decisions", 0),
            "win_rate": stats.get("win_rate", "N/A"),
            "session": self._format_session_label(session_ctx),
            "decision_candle": candle_time,
            "closed_trades": closed_trades or [],
        }

    def _print_final(self, r: dict) -> None:
        icons = {"BUY": "🟢", "SELL": "🔴", "WAIT": "🟡", "NO TRADE": "⚪"}
        icon = icons.get(r["final_action"], "⚪")
        bar = "═" * 52

        log.info(bar)
        log.info(f"  {icon}  AI TRADER FINAL REPORT — {r['symbol']}")
        log.info(bar)
        log.info(f"  Engine       : {self.execution_mode.upper()} | Approval: {r.get('approval_mode', 'N/A')}")
        log.info(f"  Price        : {r['price']}  |  Session: {r.get('session')}")
        if r.get("decision_candle"):
            log.info(f"  Candle       : {r['decision_candle']}")
        if r.get("monitor_only"):
            log.info(f"  Monitor only : {r['reject_reason']}")
        else:
            log.info(f"  Trend        : {r['trend']}  |  Regime: {r['regime']}")
            log.info(f"  RSI          : {r['rsi']}  |  Volatility: {r['volatility']}")
            log.info(f"  Rule signal  : {r['rule_signal']} ({r['rule_conf']}%)")
            log.info(f"  LLM signal   : {r['llm_signal']} ({r['llm_conf']}%)")
            log.info(f"  DECISION     : {r['decision']} ({r['confidence']}%)")
            log.info("  ──")

            if r.get("paper_trade_id"):
                log.info(f"  FINAL ACTION : {r['final_action']}")
                log.info(f"  Entry: {r['entry']} | SL: {r['sl']} | TP: {r['tp']}")
                log.info(f"  Lot: {r['lot']} | R:R 1:{r['rr']} | Risk: ${r['risk_usd']}")
                if r.get("trade_id"):
                    log.info(f"  Trade ID     : #{r['trade_id']}")
                log.info(
                    f"  Paper Trade  : #{r['paper_trade_id']}  |  "
                    f"Paper Balance: ${r.get('paper_balance')}"
                )
            elif r["trade_allowed"]:
                log.info(f"  FINAL ACTION : {r['final_action']} (not executed — {r.get('reject_reason', 'pending approval')})")
            else:
                log.info(f"  FINAL ACTION : NO TRADE — {r['reject_reason']}")

        if r.get("closed_trades"):
            log.info(f"  Closed now   : {len(r['closed_trades'])} trade(s) updated")
        log.info(f"  Memory       : {r['total_decisions']} decisions | WR: {r['win_rate']}%")
        log.info(f"  Completed in : {r['elapsed_sec']}s")
        log.info(bar)

    def _save_all(self, market_out, analysis_out, risk_out, dec_out, perm_out):
        try:
            ind_ctx = market_out["ind_ctx"]
            combined = {
                **ind_ctx,
                **market_out.get("regime_ctx", {}),
                **analysis_out.get("pat_ctx", {}),
                **analysis_out.get("sr_ctx", {}),
                **analysis_out.get("bias_ctx", {}),
                **analysis_out.get("signal_ctx", {}),
                **analysis_out.get("llm_ctx", {}),
                **analysis_out.get("news_ctx", {}),
                **self._risk.get_ai_context(risk_out),
                **self._decision.get_ai_context(dec_out),
                "trade_allowed": perm_out["allowed"],
                "final_action": perm_out["final_action"],
            }
            db = self._db
            df = market_out["df"]
            db.save_candles(df, self.symbol, self.timeframe)
            db.save_indicators(df, self.symbol, self.timeframe)
            db.save_patterns(df, self.symbol, self.timeframe)
            db.save_analysis(
                self.symbol,
                self.timeframe,
                analysis_out["bias_result"]["net_score"],
                analysis_out["bias_result"]["bias"],
                combined,
            )
            AnalysisHistory().save(
                self.symbol,
                self.timeframe,
                analysis_out["bias_ctx"],
                ind_ctx,
            )
        except Exception as e:
            log.warning(f"DB save error (non-critical): {e}")

    def _extract_candle_time(self, market_out: dict) -> str | None:
        df = market_out.get("df")
        if df is None or len(df.index) == 0:
            return None
        latest = df.index[-1]
        try:
            return latest.to_pydatetime().isoformat()
        except Exception:
            return str(latest)

    def _extract_pattern(self, market_out: dict) -> str:
        df = market_out.get("df")
        if df is None:
            return "none"
        for key in ("pattern_name", "pattern", "engulfing", "star_pattern"):
            if key in df.columns:
                value = df.iloc[-1].get(key, "none")
                if value and value != "none":
                    return value
        return "none"

    def _format_session_label(self, session_ctx: dict | None) -> str | None:
        if not session_ctx:
            return None
        if session_ctx.get("overlap"):
            return session_ctx["overlap"]
        active = session_ctx.get("active_sessions") or []
        if active:
            return "/".join(s.replace("_", " ").title() for s in active)
        return "Closed"

    def _session_permission_context(self, session_ctx: dict | None) -> dict | None:
        if not session_ctx:
            return None
        trade_quality = (session_ctx.get("trade_quality") or "").upper()
        if "BEST" in trade_quality or "GOOD" in trade_quality:
            quality = "HIGH"
        elif "CAUTION" in trade_quality:
            quality = "MEDIUM"
        else:
            quality = "LOW"
        return {"quality": quality}

    def _notify_trade_open(self, trade: dict, result: dict, dec_out: dict) -> None:
        """Builds the Telegram payload from `result`, not `trade` — `trade`'s
        shape differs between paper mode (full PaperTrader record) and MT5
        demo mode (still a `PENDING_EXECUTOR` stub), but `result` always has
        symbol/final_action/entry/sl/tp/lot regardless of backend."""
        if not self.notifier:
            return
        payload = {
            "pair": result.get("symbol"),
            "signal": result.get("final_action"),
            "entry": result.get("entry"),
            "sl": result.get("sl"),
            "tp": result.get("tp"),
            "lot": result.get("lot"),
        }
        self._run_async(
            self.notifier.notify_trade_open(
                payload,
                result.get("confidence", 0),
                dec_out.get("reasons", []),
            )
        )

    def _notify_trade_close(self, trade: dict) -> None:
        if not self.notifier:
            return
        self._run_async(self.notifier.notify_trade_close(trade))

    def _run_async(self, coro) -> None:
        try:
            asyncio.run(coro)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(coro)
            finally:
                loop.close()
        except Exception as e:
            log.warning(f"Telegram notify failed: {e}")

    def _clean_symbol(self, symbol: str) -> str:
        return str(symbol).upper().replace("/", "").replace("=X", "").replace("USDT", "USD").strip()

    def _error_result(self, reason: str) -> dict:
        log.error(f"Pipeline failed: {reason}")
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "version": self.VERSION,
            "final_action": "NO TRADE",
            "trade_allowed": False,
            "error": reason,
        }


class AutonomousTraderSystem:

    def __init__(
        self,
        symbols: list[str] | None = None,
        timeframe: str = "15m",
        balance: float = 10000.0,
        poll_seconds: int = 60,
        backup_interval_minutes: int = 30,
        cooldown_minutes: int = 5,
        max_cycles: int | None = None,
        enable_telegram: bool = True,
        use_scanner: bool = False,
        execution_mode: str = None,
        approval_mode: int = 3,
    ):
        self.symbols = [self._clean_symbol(s) for s in (symbols or ["EURUSD", "GBPUSD", "USDJPY"])]
        self.timeframe = timeframe
        self.balance = balance
        self.poll_seconds = max(5, poll_seconds)
        self.backup_interval_minutes = max(5, backup_interval_minutes)
        self.cooldown_minutes = max(1, cooldown_minutes)
        self.max_cycles = max_cycles
        self.use_scanner = use_scanner
        self.execution_mode = (execution_mode or EXECUTION_MODE).lower()
        self.approval_mode = approval_mode
        self._stop_requested = False
        self._pause_until = None
        self._consecutive_error_cycles = 0
        self._bot_thread = None
        self._last_backup = None
        self._last_results: list[dict] = []

        # Day 36/37 — Market Scanner picks the day's Top-N tradeable pairs
        # each cycle instead of always scanning a fixed list. It needs a
        # market_data_manager (MT5 tick/candle bundle) to actually rank
        # pairs; that adapter isn't built yet, so until it is,
        # _select_cycle_symbols() below safely falls back to self.symbols.
        self.scanner = MarketScanner(risk_engine=None) if (use_scanner and MarketScanner) else None

        # Circuit breaker + approval mode are global state (one shared JSON
        # file each) — created ONCE here and handed to every symbol's
        # AITrader so they don't overwrite each other's state.
        self.circuit_breaker = CircuitBreaker(balance=balance)
        self.approval = ApprovalMode(mode=approval_mode)

        self.notifier = TelegramNotifier() if enable_telegram and TelegramNotifier else None
        self.traders: dict[str, AITrader] = {
            symbol: self._build_trader(symbol) for symbol in self.symbols
        }
        self._sync_risk_state()

    def _build_trader(self, symbol: str) -> AITrader:
        return AITrader(
            balance=self.balance,
            symbol=symbol,
            timeframe=self.timeframe,
            paper_balance=self.balance,
            notifier=self.notifier,
            execution_mode=self.execution_mode,
            approval_mode=self.approval_mode,
            circuit_breaker=self.circuit_breaker,
            approval=self.approval,
        )

    def run(self) -> dict:
        self._start_telegram_commands()
        self.backup_state(force=True)
        cycles = 0

        log.info(
            f"[System] Starting autonomous loop | Pairs={self.symbols} | "
            f"Timeframe={self.timeframe} | Mode={self.execution_mode.upper()} | "
            f"Scanner={'ON' if self.use_scanner else 'OFF'} | Balance=${self.balance}"
        )

        try:
            while not self._stop_requested:
                cycle_started = time.time()
                if self.max_cycles is not None and cycles >= self.max_cycles:
                    break

                if self._is_paused():
                    self._sleep_remaining(cycle_started)
                    cycles += 1
                    continue

                cycle_results = []
                cycle_errors = []
                active_symbols = self._select_cycle_symbols()

                for symbol in active_symbols:
                    trader = self.traders.get(symbol) or self._spawn_trader(symbol)
                    try:
                        if self._manual_pause_active():
                            closed = trader.monitor_open_trades()
                            cycle_results.append(
                                {
                                    "symbol": symbol,
                                    "final_action": "WAIT",
                                    "trade_allowed": False,
                                    "closed_trades": closed,
                                    "reject_reason": "Trading paused from Telegram",
                                }
                            )
                            continue

                        result = trader.run_cycle(auto_paper_trade=True)
                        cycle_results.append(result)
                        if result.get("error"):
                            cycle_errors.append(f"{symbol}: {result['error']}")
                    except Exception as e:
                        msg = f"{symbol}: {e}"
                        cycle_errors.append(msg)
                        log.exception(f"[System] Symbol cycle failed — {msg}")

                self._last_results = cycle_results
                self._write_runtime_report()

                if cycle_errors:
                    self._handle_cycle_errors(cycle_errors)
                else:
                    self._consecutive_error_cycles = 0

                self.backup_state()
                self._sleep_remaining(cycle_started)
                cycles += 1

        except KeyboardInterrupt:
            log.info("[System] Stop requested by user")

        report = self._build_system_report()
        self._write_runtime_report(report)
        return report

    def stop(self) -> None:
        self._stop_requested = True

    def _select_cycle_symbols(self) -> list[str]:
        """Scanner-driven Top-N pairs when enabled and wired up; the static
        symbol list otherwise (or on any scanner failure)."""
        if not self.use_scanner or not self.scanner:
            return self.symbols
        try:
            ranked = self.scanner.scan()
            top = self.scanner.get_top_opportunities(ranked)
            scanned = [opp["symbol"] for opp in top]
            return scanned or self.symbols
        except Exception as e:
            log.warning(f"[System] Scanner failed, falling back to static symbols: {e}")
            return self.symbols

    def _spawn_trader(self, symbol: str) -> AITrader:
        symbol = self._clean_symbol(symbol)
        trader = self._build_trader(symbol)
        self.traders[symbol] = trader
        return trader

    def backup_state(self, force: bool = False) -> Path | None:
        now = datetime.now(timezone.utc)
        if not force and self._last_backup:
            due_at = self._last_backup + timedelta(minutes=self.backup_interval_minutes)
            if now < due_at:
                return None

        timestamp = now.strftime("%Y%m%d_%H%M%S")
        backup_dir = Path("backups") / timestamp
        backup_dir.mkdir(parents=True, exist_ok=True)

        for relative_path in [
            "database/trader.db",
            "memory/trader.db",
            "memory/trade_memory.json",
            "memory/daily_risk.json",
            "memory/analysis_history.json",
            "memory/circuit_breaker_state.json",
            "memory/pending_approvals.json",
        ]:
            src = Path(relative_path)
            if src.exists():
                shutil.copy2(src, backup_dir / src.name)

        self._last_backup = now
        log.info(f"[System] Backup created: {backup_dir}")
        return backup_dir

    def _handle_cycle_errors(self, errors: list[str]) -> None:
        self._consecutive_error_cycles += 1
        self._pause_until = datetime.now(timezone.utc) + timedelta(minutes=self.cooldown_minutes)
        reason = "; ".join(errors[:3])
        log.error(f"[Recovery] Pausing trading after errors: {reason}")

        if self.notifier:
            self._notify_warning(
                f"System warning: trading paused for recovery. {reason}",
                f"{self.cooldown_minutes} minutes",
            )

    def _sync_risk_state(self) -> None:
        open_pairs = []
        for trader in self.traders.values():
            open_pairs.extend([trade.get("pair") for trade in trader._paper.get_open_positions()])
        for trader in self.traders.values():
            trader._risk.sync_open_positions(open_pairs)

    def _start_telegram_commands(self) -> None:
        if not self.notifier or not start_telegram_bot_polling or self._bot_thread:
            return
        self._bot_thread = threading.Thread(
            target=start_telegram_bot_polling,
            name="telegram-polling",
            daemon=True,
        )
        self._bot_thread.start()
        log.info("[System] Telegram command polling thread started")

    def _notify_warning(self, event_name: str, time_remaining: str) -> None:
        if not self.notifier:
            return
        try:
            asyncio.run(self.notifier.notify_news_warning(event_name, time_remaining))
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self.notifier.notify_news_warning(event_name, time_remaining))
            finally:
                loop.close()
        except Exception as e:
            log.warning(f"[System] Warning notify failed: {e}")

    def _manual_pause_active(self) -> bool:
        return bool(telegram_module and getattr(telegram_module, "IS_TRADING_PAUSED", False))

    def _is_paused(self) -> bool:
        if not self._pause_until:
            return False
        if datetime.now(timezone.utc) >= self._pause_until:
            log.info("[Recovery] Cooldown completed. Resuming trading loop safely.")
            self._pause_until = None
            return False
        return True

    def _sleep_remaining(self, cycle_started: float) -> None:
        elapsed = time.time() - cycle_started
        remaining = max(0, self.poll_seconds - elapsed)
        if remaining:
            time.sleep(remaining)

    def _write_runtime_report(self, report: dict | None = None) -> Path:
        report = report or self._build_system_report()
        report_dir = Path("reports")
        report_dir.mkdir(parents=True, exist_ok=True)
        path = report_dir / "latest_report.json"
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return path

    def _build_system_report(self) -> dict:
        sample_trader = next(iter(self.traders.values()))
        stats = sample_trader._db.get_overall_stats(starting_balance=self.balance)
        recent = sample_trader._db.get_trade_history(limit=20)

        best_setup = "N/A"
        biggest_mistake = "N/A"
        if not recent.empty and "pattern" in recent.columns:
            wins = recent[recent["result"] == "WIN"]
            losses = recent[recent["result"] == "LOSS"]
            if not wins.empty:
                best_setup = str(wins["pattern"].fillna("unknown").mode().iloc[0])
            if not losses.empty:
                biggest_mistake = str(losses["pattern"].fillna("unknown").mode().iloc[0])

        avg_rr = 0
        closed_count = len(recent.index)
        if closed_count and {"entry", "sl", "tp"}.issubset(set(recent.columns)):
            rr_values = []
            for _, row in recent.iterrows():
                try:
                    risk = abs(float(row["entry"]) - float(row["sl"]))
                    reward = abs(float(row["tp"]) - float(row["entry"]))
                    rr_values.append(round(reward / risk, 2) if risk else 0)
                except Exception:
                    continue
            if rr_values:
                avg_rr = round(sum(rr_values) / len(rr_values), 2)

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "mode": self.execution_mode.upper(),
            "scanner": "ON" if self.use_scanner else "OFF",
            "pairs": self.symbols,
            "active_pairs": list(self.traders.keys()),
            "timeframe": self.timeframe,
            "balance": self.balance,
            "system_state": "PAUSED" if self._manual_pause_active() or self._is_paused() else "RUNNING",
            "circuit_breaker": self.circuit_breaker.get_status(),
            "summary": {
                "trades": stats.get("total", 0),
                "wins": stats.get("wins", 0),
                "losses": stats.get("losses", 0),
                "win_rate": stats.get("win_rate", 0),
                "profit": stats.get("total_pnl", 0),
                "balance": stats.get("balance", self.balance),
                "open_positions": stats.get("open_trades", 0),
                "average_rr": avg_rr,
                "best_setup": best_setup,
                "biggest_mistake": biggest_mistake,
            },
            "last_results": self._last_results[-len(self.symbols):],
        }

    def _clean_symbol(self, symbol: str) -> str:
        return str(symbol).upper().replace("/", "").replace("=X", "").replace("USDT", "USD").strip()