# agents/analysis_agent.py  —  Day 12 | Technical + Fundamental Agent

from analysis.patterns import PatternDetector
from analysis.support_resistance import SupportResistance
from analysis.market_bias import MarketBiasEngine
from fundamental.news_filter import NewsFilter
from ai.ai_analyst import AIAnalyst
from strategy.signal_engine import SignalEngine
from utils.logger import get_logger

log = get_logger("analysis_agent")


class AnalysisAgent:
    """
    Technical analysis + fundamental filter + LLM opinion।
    MarketAgent output নিয়ে signal তৈরি করে।
    """

    def run(self, market_output: dict) -> dict:
        if "error" in market_output:
            return {"error": market_output["error"]}

        df       = market_output["df"]
        ind_ctx  = market_output["ind_ctx"]
        regime   = market_output["regime"]
        mtf_bias = market_output["mtf_bias"]
        symbol   = market_output["symbol"]

        log.info("[AnalysisAgent] Running patterns + S/R + bias + signal + news + LLM")

        # Patterns
        detector = PatternDetector()
        df       = detector.run_full_detection(df)
        detector.get_latest_patterns(df, lookback=5)
        pat_ctx  = detector.get_ai_pattern_context(df)

        # S/R
        sr       = SupportResistance()
        sr_res   = sr.analyze(df)
        sr.get_summary(sr_res)
        sr_ctx   = sr.get_ai_context(sr_res)

        # Bias engine
        bias_engine = MarketBiasEngine()
        bias_result = bias_engine.analyze(ind_ctx, pat_ctx, sr_ctx, mtf_bias)
        bias_engine.print_summary(bias_result)
        bias_ctx    = bias_engine.get_ai_context(bias_result)

        # Rule-based signal
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

        # LLM analyst
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

        # News filter
        news_filter  = NewsFilter()
        news_result  = news_filter.check(symbol)
        news_filter.print_summary(news_result)
        news_ctx     = news_filter.get_ai_context(news_result)

        # News override
        final_signal = signal_result["signal"]
        if not news_result["trade_allowed"]:
            final_signal = "NO TRADE"
            log.info(f"[AnalysisAgent] Signal → NO TRADE (news block)")

        log.info(
            f"[AnalysisAgent] Done — "
            f"Rule: {signal_result['signal']} | "
            f"LLM: {llm_result.get('signal')} | "
            f"Final: {final_signal}"
        )

        return {
            "df":           df,
            "pat_ctx":      pat_ctx,
            "sr_result":    sr_res,
            "sr_ctx":       sr_ctx,
            "bias_result":  bias_result,
            "bias_ctx":     bias_ctx,
            "signal":       signal_result,
            "signal_ctx":   signal_ctx,
            "llm":          llm_result,
            "llm_ctx":      llm_ctx,
            "news":         news_result,
            "news_ctx":     news_ctx,
            "final_signal": final_signal,
        }