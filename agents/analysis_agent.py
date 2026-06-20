# agents/analysis_agent.py  —  Day 42 | Technical + Sentiment + Master Analyst

from analysis.patterns import PatternDetector
from analysis.support_resistance import SupportResistance
from analysis.market_bias import MarketBiasEngine
from analysis.sentiment import SentimentEngine
from data.sentiment_data import SentimentDataProvider
from fundamental.news_filter import NewsFilter
from ai.ai_analyst import AIAnalyst
from agents.master_analyst import MasterAnalyst
from strategy.signal_engine import SignalEngine
from utils.logger import get_logger

log = get_logger("analysis_agent")


class AnalysisAgent:
    """
    Day 42: All intelligence modules → MasterAnalyst LLM brain.

    Pipeline:
        Patterns → S/R → Bias → Signal → Sentiment → News → LLM → MasterAnalyst
    """

    def run(self, market_output: dict, memory_ctx: dict = None) -> dict:
        if "error" in market_output:
            return {"error": market_output["error"]}

        df        = market_output["df"]
        ind_ctx   = market_output["ind_ctx"]
        regime    = market_output["regime"]
        mtf_bias  = market_output["mtf_bias"]
        symbol    = market_output["symbol"]
        timeframe = market_output.get("timeframe", "15m")

        log.info(
            f"[AnalysisAgent] Running full pipeline for {symbol} — "
            "Patterns + S/R + Bias + Signal + Sentiment + News + LLM + MasterAnalyst"
        )

        # ── Patterns ──────────────────────────────────────────
        detector = PatternDetector()
        df       = detector.run_full_detection(df)
        detector.get_latest_patterns(df, lookback=5)
        pat_ctx  = detector.get_ai_pattern_context(df)

        # ── S/R ───────────────────────────────────────────────
        sr      = SupportResistance()
        sr_res  = sr.analyze(df)
        sr.get_summary(sr_res)
        sr_ctx  = sr.get_ai_context(sr_res)

        # ── Market Bias ───────────────────────────────────────
        bias_engine = MarketBiasEngine()
        bias_result = bias_engine.analyze(ind_ctx, pat_ctx, sr_ctx, mtf_bias)
        bias_engine.print_summary(bias_result)
        bias_ctx    = bias_engine.get_ai_context(bias_result)

        # ── Rule-based Signal ─────────────────────────────────
        signal_engine = SignalEngine()
        signal_result = signal_engine.generate(
            ind_ctx  = ind_ctx,
            pat_ctx  = pat_ctx,
            sr_ctx   = sr_ctx,
            regime   = regime,
            mtf_bias = mtf_bias,
        )
        signal_engine.print_summary(signal_result)
        signal_ctx = signal_engine.get_ai_context(signal_result)

        # ── Sentiment Engine (Day 41) ─────────────────────────
        sentiment_ctx    = {}
        sentiment_result = {}
        conflict_result  = {}
        try:
            sent_provider    = SentimentDataProvider()
            sent_data        = sent_provider.get_all(symbol)
            sent_provider.print_summary(sent_data)

            sent_engine      = SentimentEngine()
            sentiment_result = sent_engine.final_sentiment_score(
                pair               = sent_data["pair"],
                retail_long_pct    = sent_data["retail_long_pct"],
                fg_index           = sent_data["fg_index"],
                currency_strengths = sent_data["currency_strengths"],
                dxy_trend          = sent_data["dxy_trend"],
                dxy_change_pct     = sent_data["dxy_change_pct"],
            )
            sent_engine.print_summary(sentiment_result)
            sentiment_ctx = sent_engine.get_ai_context(sentiment_result)

            conflict_result = sent_engine.detect_conflict(
                technical_signal = signal_result.get("signal", "NO TRADE"),
                sentiment_result = sentiment_result,
            )
        except Exception as e:
            log.warning(f"[AnalysisAgent] Sentiment error (non-critical): {e}")

        # ── News Filter ───────────────────────────────────────
        news_filter = NewsFilter()
        news_result = news_filter.check(symbol)
        news_filter.print_summary(news_result)
        news_ctx    = news_filter.get_ai_context(news_result)

        # ── Classic LLM Analyst ───────────────────────────────
        llm_result = AIAnalyst().analyze(
            ind_ctx  = ind_ctx,
            pat_ctx  = pat_ctx,
            sr_ctx   = sr_ctx,
            regime   = regime,
            signal   = signal_result,
            mtf_bias = mtf_bias,
            symbol   = symbol,
        )
        AIAnalyst().print_summary(llm_result)
        llm_ctx = AIAnalyst().get_ai_context(llm_result)

        # ── MASTER ANALYST (Day 42) ───────────────────────────
        master_result = {}
        master_ctx    = {}
        try:
            master = MasterAnalyst()
            master_result = master.analyze(
                symbol        = symbol,
                timeframe     = timeframe,
                ind_ctx       = ind_ctx,
                pat_ctx       = pat_ctx,
                sr_ctx        = sr_ctx,
                regime        = regime,
                mtf_bias      = mtf_bias,
                signal        = signal_result,
                sentiment_ctx = sentiment_ctx,
                news_ctx      = news_ctx,
                memory_ctx    = memory_ctx or {},
                bias_ctx      = bias_ctx,
            )
            master.print_summary(master_result)
            master_ctx = master.get_ai_context(master_result)
        except Exception as e:
            log.warning(f"[AnalysisAgent] MasterAnalyst error (non-critical): {e}")

        # ── Final Signal Resolution ───────────────────────────
        # Priority: News block > Sentiment conflict > MasterAnalyst > Rule engine
        final_signal = signal_result["signal"]

        if not news_result["trade_allowed"]:
            final_signal = "NO TRADE"
            log.info("[AnalysisAgent] -> NO TRADE (news block)")

        elif conflict_result.get("has_conflict") and \
                sentiment_result.get("confidence", 0) >= 70:
            final_signal = "NO TRADE"
            log.info("[AnalysisAgent] -> NO TRADE (high-confidence sentiment conflict)")

        elif master_ctx.get("master_signal") in ("BUY", "SELL", "WAIT"):
            ma_signal    = master_ctx["master_signal"]
            final_signal = "NO TRADE" if ma_signal == "WAIT" else ma_signal
            log.info(f"[AnalysisAgent] -> {final_signal} (MasterAnalyst decision)")

        log.info(
            f"[AnalysisAgent] Complete — "
            f"Rule: {signal_result['signal']} | "
            f"LLM: {llm_result.get('signal')} | "
            f"Master: {master_ctx.get('master_signal', 'N/A')} | "
            f"Sentiment: {sentiment_result.get('bias', 'N/A')} | "
            f"Final: {final_signal}"
        )

        return {
            "df":            df,
            "pat_ctx":       pat_ctx,
            "sr_result":     sr_res,
            "sr_ctx":        sr_ctx,
            "bias_result":   bias_result,
            "bias_ctx":      bias_ctx,
            "signal":        signal_result,
            "signal_ctx":    signal_ctx,
            "llm":           llm_result,
            "llm_ctx":       llm_ctx,
            "news":          news_result,
            "news_ctx":      news_ctx,
            "sentiment":     sentiment_result,
            "sentiment_ctx": sentiment_ctx,
            "conflict":      conflict_result,
            "master":        master_result,
            "master_ctx":    master_ctx,
            "final_signal":  final_signal,
        }