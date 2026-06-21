# agents/analysis_agent.py  (Day 47 Vision Update)
# ============================================================
# Day 44 pipeline-এর সাথে Day 47 Vision Layer যোগ হয়েছে।
#
# নতুন:
#   Step 12: ChartReader (Vision AI)
#   Step 13: Vision + Quant Fusion
#
# Vision inject হয় MasterAnalyst-এর আগে,
# তাই Master সব context পায় — visual + quant।
# ============================================================

from analysis.patterns import PatternDetector
from analysis.support_resistance import SupportResistance
from analysis.market_bias import MarketBiasEngine
from analysis.advanced_patterns import AdvancedPatternDetector
from analysis.fibonacci import FibonacciEngine
from analysis.sentiment import SentimentEngine
from analysis.smc_engine import SMCEngine
from analysis.sentiment_data import SentimentDataProvider
from fundamental.news_filter import NewsFilter
from ai.ai_analyst import AIAnalyst
from agents.master_analyst import MasterAnalyst
from strategy.signal_engine import SignalEngine
from utils.logger import get_logger

log = get_logger("analysis_agent")


class AnalysisAgent:
    """
    Day 47 Unified Pipeline:
      Patterns -> S/R -> Advanced Patterns -> Fibonacci -> Bias -> Signal
      -> Sentiment -> SMC -> News -> Classic LLM -> Vision AI -> MasterAnalyst
    """

    def __init__(self, chart_reader=None):
        """
        chart_reader: ChartReader instance (Day 47 vision)
        None দিলে vision skip হবে (backward compatible)।
        """
        self.chart_reader = chart_reader

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
            f"[AnalysisAgent] Running Day 47 pipeline for {symbol} ({timeframe}) — "
            "Technical + Advanced + Fib + Sentiment + SMC + News + Vision + MasterAnalyst"
        )

        # ── 1. Candlestick Patterns ───────────────────────────
        detector = PatternDetector()
        df       = detector.run_full_detection(df)
        detector.get_latest_patterns(df, lookback=5)
        pat_ctx  = detector.get_ai_pattern_context(df)

        # ── 2. Support & Resistance ───────────────────────────
        sr      = SupportResistance()
        sr_res  = sr.analyze(df)
        sr.get_summary(sr_res)
        sr_ctx  = sr.get_ai_context(sr_res)

        # ── 3. Advanced Patterns ─────────────────────────────
        advanced_pat_ctx = {}
        adv_patterns     = {}
        try:
            adv_detector = AdvancedPatternDetector(lookback=100)
            adv_patterns = adv_detector.detect_all(df)
            adv_patterns = adv_detector.boost_confidence(
                adv_patterns,
                ind_ctx    = ind_ctx,
                sr_ctx     = sr_ctx,
                regime_ctx = regime,
                pat_ctx    = pat_ctx,
            )
            adv_patterns = adv_detector.filter_false_patterns(
                adv_patterns,
                regime_ctx = regime,
                ind_ctx    = ind_ctx,
            )
            adv_detector.print_summary(adv_patterns)
            advanced_pat_ctx = adv_detector.get_ai_context(
                df,
                ind_ctx    = ind_ctx,
                sr_ctx     = sr_ctx,
                regime_ctx = regime,
                pat_ctx    = pat_ctx,
            )
        except Exception as e:
            log.warning(f"[AnalysisAgent] Advanced Patterns error: {e}")

        # ── 4. Fibonacci Engine ──────────────────────────────
        fib_ctx    = {}
        fib_result = {}
        try:
            fib_engine = FibonacciEngine(timeframe=timeframe)
            fib_result = fib_engine.analyze(df, sr_ctx=sr_ctx, ind_ctx=ind_ctx)
            fib_engine.print_summary(fib_result)
            fib_ctx    = fib_engine.get_ai_context(fib_result)
        except Exception as e:
            log.warning(f"[AnalysisAgent] Fibonacci Engine error: {e}")

        # ── 5. Market Bias ────────────────────────────────────
        bias_engine = MarketBiasEngine()
        bias_result = bias_engine.analyze(ind_ctx, pat_ctx, sr_ctx, mtf_bias)
        bias_engine.print_summary(bias_result)
        bias_ctx    = bias_engine.get_ai_context(bias_result)

        # ── 6. Rule-based Signal ──────────────────────────────
        signal_engine = SignalEngine()
        signal_result = signal_engine.generate(
            ind_ctx          = ind_ctx,
            pat_ctx          = pat_ctx,
            sr_ctx           = sr_ctx,
            regime           = regime,
            mtf_bias         = mtf_bias,
            advanced_pat_ctx = advanced_pat_ctx,
            fib_ctx          = fib_ctx,
        )
        signal_engine.print_summary(signal_result)
        signal_ctx = signal_engine.get_ai_context(signal_result)

        # ── 7. Sentiment Engine ─────────────────────────────
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
            log.warning(f"[AnalysisAgent] Sentiment error: {e}")

        # ── 8. SMC Engine ───────────────────────────────────
        smc_result = {}
        smc_ctx    = {}
        try:
            smc        = SMCEngine(symbol)
            smc_result = smc.analyze()
            smc.print_summary(smc_result)
            smc_ctx    = smc.get_ai_context(smc_result)
        except Exception as e:
            log.warning(f"[AnalysisAgent] SMC Engine error: {e}")

        # ── 9. News Filter ───────────────────────────────────
        news_filter = NewsFilter()
        news_result = news_filter.check(symbol)
        news_filter.print_summary(news_result)
        news_ctx    = news_filter.get_ai_context(news_result)

        # ── 10. Classic LLM Analyst ──────────────────────────
        _llm = AIAnalyst()
        llm_result = _llm.analyze(
            ind_ctx          = ind_ctx,
            pat_ctx          = pat_ctx,
            sr_ctx           = sr_ctx,
            regime           = regime,
            signal           = signal_result,
            mtf_bias         = mtf_bias,
            advanced_pat_ctx = advanced_pat_ctx,
            fib_ctx          = fib_ctx,
            symbol           = symbol,
        )
        _llm.print_summary(llm_result)
        llm_ctx = _llm.get_ai_context(llm_result)

        # ── 11. VISION AI (Day 47) ────────────────────────────
        vision_result = {}
        vision_ctx    = {}
        fusion_result = {}
        try:
            if self.chart_reader:
                log.info(f"[AnalysisAgent] 👁️ Running Vision AI for {symbol} {timeframe}")
                vision_result = self.chart_reader.capture_and_analyze(
                    symbol=symbol,
                    timeframe=timeframe,
                    quant_ctx=ind_ctx,
                )
                vision_ctx = vision_result.get("vision_ctx", {})

                # Vision + Quant Fusion
                fusion_result = self.chart_reader.fuse_with_quant(
                    vision_result=vision_result,
                    analysis_output={
                        "final_signal": signal_result.get("signal", "NO TRADE"),
                        "signal":       signal_result,
                        "ind_ctx":      ind_ctx,
                    }
                )
                log.info(
                    f"[AnalysisAgent] Vision fusion: {fusion_result.get('final_signal')} "
                    f"conf={fusion_result.get('adjusted_conf')}% "
                    f"conflict={fusion_result.get('has_conflict')}"
                )
            else:
                log.info("[AnalysisAgent] Vision skipped (no ChartReader)")
        except Exception as e:
            log.warning(f"[AnalysisAgent] Vision AI error (non-critical): {e}")

        # ── 12. MASTER ANALYST BRAIN ─────────────────────────
        master_result = {}
        master_ctx    = {}
        try:
            master = MasterAnalyst()
            master_result = master.analyze(
                symbol           = symbol,
                timeframe        = timeframe,
                ind_ctx          = ind_ctx,
                pat_ctx          = pat_ctx,
                sr_ctx           = sr_ctx,
                regime           = regime,
                mtf_bias         = mtf_bias,
                signal           = signal_result,
                sentiment_ctx    = sentiment_ctx,
                news_ctx         = news_ctx,
                memory_ctx       = memory_ctx or {},
                bias_ctx         = bias_ctx,
                smc_ctx          = smc_ctx,
                fib_ctx          = fib_ctx,
                advanced_pat_ctx = advanced_pat_ctx,
                # Day 47: vision context inject
                vision_ctx       = vision_ctx,
            )
            master.print_summary(master_result)
            master_ctx = master.get_ai_context(master_result)
        except Exception as e:
            log.warning(f"[AnalysisAgent] MasterAnalyst error: {e}")

        # ── Final Signal Resolution ───────────────────────────
        # Priority: News block > Sentiment conflict > Vision conflict > MasterAnalyst > Rule
        final_signal = signal_result["signal"]

        if not news_result.get("trade_allowed", True):
            final_signal = "NO TRADE"
            log.info("[AnalysisAgent] -> NO TRADE (news block override)")

        elif conflict_result.get("has_conflict") and sentiment_result.get("confidence", 0) >= 70:
            final_signal = "NO TRADE"
            log.info("[AnalysisAgent] -> NO TRADE (high-confidence sentiment conflict)")

        # Day 47: Vision conflict → NO TRADE
        elif fusion_result.get("has_conflict") and fusion_result.get("adjusted_conf", 100) < 45:
            final_signal = "NO TRADE"
            log.info("[AnalysisAgent] -> NO TRADE (vision/quant conflict — low confidence)")

        elif master_ctx.get("master_signal") in ("BUY", "SELL", "WAIT"):
            ma_signal    = master_ctx["master_signal"]
            final_signal = "NO TRADE" if ma_signal == "WAIT" else ma_signal
            log.info(f"[AnalysisAgent] -> {final_signal} (MasterAnalyst override)")

        log.info(
            f"[AnalysisAgent] Complete — "
            f"Rule: {signal_result['signal']} | "
            f"LLM: {llm_result.get('signal')} | "
            f"Vision: {vision_ctx.get('vision_trend', 'N/A')} ({vision_ctx.get('vision_confidence', 0)}%) | "
            f"Fusion: {fusion_result.get('final_signal', 'N/A')} ({fusion_result.get('adjusted_conf', 0)}%) | "
            f"Master: {master_ctx.get('master_signal', 'N/A')} | "
            f"Final: {final_signal}"
        )

        return {
            "df":                df,
            "pat_ctx":           pat_ctx,
            "advanced_patterns": adv_patterns,
            "advanced_pat_ctx":  advanced_pat_ctx,
            "sr_result":         sr_res,
            "sr_ctx":            sr_ctx,
            "fib_result":        fib_result,
            "fib_ctx":           fib_ctx,
            "bias_result":       bias_result,
            "bias_ctx":          bias_ctx,
            "signal":            signal_result,
            "signal_ctx":        signal_ctx,
            "llm":               llm_result,
            "llm_ctx":           llm_ctx,
            "news":              news_result,
            "news_ctx":          news_ctx,
            "sentiment":         sentiment_result,
            "sentiment_ctx":     sentiment_ctx,
            "conflict":          conflict_result,
            "smc":               smc_result,
            "smc_ctx":           smc_ctx,
            # Day 47 new
            "vision":            vision_result,
            "vision_ctx":        vision_ctx,
            "vision_fusion":     fusion_result,
            # Master
            "master":            master_result,
            "master_ctx":        master_ctx,
            "final_signal":      final_signal,
        }
        # ============================================================
# Day 62 — AnalysisAgent integration patch
# ============================================================
# Apply to agents/analysis_agent.py. Adds a new pipeline step that
# runs LiquidityEngine right after SMC (step 8) and before News (step 9),
# then threads liquidity_ctx through to MasterAnalyst (step 12) and
# into the final return dict.
# ============================================================


# ── 1. New import ──────────────────────────────────────────────
"""
from analysis.liquidity_engine import LiquidityEngine
"""


# ── 2. New pipeline step — insert AFTER "8. SMC Engine" block,
#      BEFORE "9. News Filter" block ────────────────────────────
"""
        # ── 8.5. LIQUIDITY ENGINE (Day 62) ───────────────────
        liquidity_result = {}
        liquidity_ctx    = {}
        try:
            liquidity_engine = LiquidityEngine()
            liquidity_result = liquidity_engine.analyze(df, smc_ctx=smc_ctx)
            liquidity_engine.print_summary(liquidity_result)
            liquidity_ctx    = liquidity_engine.get_ai_context(liquidity_result)
        except Exception as e:
            log.warning(f"[AnalysisAgent] Liquidity Engine error: {e}")
"""


# ── 3. MasterAnalyst call — add liquidity_ctx kwarg ─────────────
# In step "12. MASTER ANALYST BRAIN", inside master.analyze(...) call,
# add this line alongside the existing smc_ctx= line:
"""
            master_result = master.analyze(
                symbol           = symbol,
                timeframe        = timeframe,
                ind_ctx          = ind_ctx,
                pat_ctx          = pat_ctx,
                sr_ctx           = sr_ctx,
                regime           = regime,
                mtf_bias         = mtf_bias,
                signal           = signal_result,
                sentiment_ctx    = sentiment_ctx,
                news_ctx         = news_ctx,
                memory_ctx       = memory_ctx or {},
                bias_ctx         = bias_ctx,
                smc_ctx          = smc_ctx,
                fib_ctx          = fib_ctx,
                advanced_pat_ctx = advanced_pat_ctx,
                vision_ctx       = vision_ctx,
                liquidity_ctx    = liquidity_ctx,   # ⭐ Day 62
            )
"""


# ── 4. Optional extra safety gate in Final Signal Resolution ────
# Insert this check among the elif-chain in "Final Signal Resolution"
# (after the Vision conflict check, before MasterAnalyst override),
# to prevent the AI from chasing a breakout that liquidity intelligence
# flags as a sweep about to reverse against the rule-engine signal:
"""
        # Day 62: Liquidity sweep contradicts rule signal at high grade → NO TRADE
        elif (
            liquidity_ctx.get("liquidity_stop_hunt")
            and liquidity_ctx.get("liquidity_grade") in ("A+", "A")
            and (
                (signal_result["signal"] == "SELL" and liquidity_ctx.get("liquidity_direction") == "BULLISH_REVERSAL")
                or (signal_result["signal"] == "BUY" and liquidity_ctx.get("liquidity_direction") == "BEARISH_REVERSAL")
            )
        ):
            final_signal = "NO TRADE"
            log.info(
                "[AnalysisAgent] -> NO TRADE (Day 62: high-grade liquidity sweep "
                "contradicts rule signal — likely stop-hunt reversal)"
            )
"""


# ── 5. Return dict — add liquidity outputs ───────────────────────
# Add these two keys to the final `return {...}` dict, alongside the
# existing "smc": smc_result / "smc_ctx": smc_ctx lines:
"""
            "liquidity":         liquidity_result,   # ⭐ Day 62
            "liquidity_ctx":     liquidity_ctx,       # ⭐ Day 62
"""


# ── 6. Final log line — optionally extend the summary log ───────
"""
        log.info(
            f"[AnalysisAgent] Complete — "
            f"Rule: {signal_result['signal']} | "
            f"LLM: {llm_result.get('signal')} | "
            f"Vision: {vision_ctx.get('vision_trend', 'N/A')} ({vision_ctx.get('vision_confidence', 0)}%) | "
            f"Fusion: {fusion_result.get('final_signal', 'N/A')} ({fusion_result.get('adjusted_conf', 0)}%) | "
            f"Liquidity: {liquidity_ctx.get('liquidity_bias', 'N/A')} ({liquidity_ctx.get('liquidity_grade', 'N/A')}) | "
            f"Master: {master_ctx.get('master_signal', 'N/A')} | "
            f"Final: {final_signal}"
        )
"""