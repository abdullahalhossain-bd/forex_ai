# agents/decision_agent.py  —  Day 42 (Master-Aware) + Day 53 (Dynamic Confidence Engine)

from learning.confidence_engine import ConfidenceEngine
from utils.logger import get_logger

log = get_logger("decision_agent")


class DecisionAgent:
    """
    Day 42: MasterAnalyst output-কে primary signal source হিসেবে ব্যবহার করে।
    Day 53: Final BUY/SELL decision নেওয়ার পর ConfidenceEngine দিয়ে
            pattern + pair + timeframe + regime ভিত্তিক dynamic confidence
            apply হয় — historical win rate, recent 10 trades, regime memory,
            Bayesian penalty, এবং pattern skip system সব মিলিয়ে।

    Vote hierarchy:
        1. MasterAnalyst (LLM synthesized brain)   — weight 3
        2. Classic LLM Analyst                     — weight 2
        3. Rule engine                             — weight 1

    Confidence pipeline:
        base_conf (Master/Rule/LLM weighted avg)
            -> sentiment boost/reduction
            -> Day 53 ConfidenceEngine.adjust_decision()
                 -> historical + recent + regime + bayesian
                 -> should_skip check (pattern disabled?)
            -> final decision + final confidence
    """

    MIN_CONSENSUS = 2

    def __init__(self):
        # Day 53 — pattern-aware dynamic confidence scorer
        self.confidence_engine = ConfidenceEngine()

    def decide(
        self,
        market_out:   dict,
        analysis_out: dict,
        risk_out:     dict,
    ) -> dict:

        final_signal  = analysis_out.get("final_signal", "NO TRADE")
        rule_signal   = analysis_out.get("signal", {}).get("signal", "NO TRADE")
        llm_signal    = analysis_out.get("llm", {}).get("signal", "WAIT")
        rule_conf     = analysis_out.get("signal", {}).get("confidence", 0)
        llm_conf      = analysis_out.get("llm", {}).get("confidence", 0)
        risk_approved = risk_out.get("approved", False)
        news_ok       = analysis_out.get("news", {}).get("trade_allowed", True)

        # Day 41 Sentiment
        sent_ctx        = analysis_out.get("sentiment_ctx", {})
        conflict_result = analysis_out.get("conflict", {})
        sentiment_bias  = sent_ctx.get("sentiment_bias", "NEUTRAL")
        sentiment_score = sent_ctx.get("sentiment_score", 0)
        has_conflict    = conflict_result.get("has_conflict", False)
        conf_adjustment = conflict_result.get("confidence_adjustment", 0)

        # Day 42 MasterAnalyst
        master_ctx      = analysis_out.get("master_ctx", {})
        master_sig      = master_ctx.get("master_signal", "WAIT")
        master_conf     = master_ctx.get("master_confidence", 0)
        master_story    = master_ctx.get("master_story", "")
        master_risks    = master_ctx.get("master_risks", [])
        master_critique = master_ctx.get("master_critique", "")

        # Day 53 — context needed for ConfidenceEngine
        pattern        = self._extract_pattern(analysis_out)
        pair           = market_out.get("symbol", "EURUSD")
        timeframe      = market_out.get("timeframe", "M15")
        regime_label   = market_out.get("regime", {}).get("regime", "UNKNOWN")

        reasons  = []
        decision = "WAIT"

        # Gates
        if not news_ok:
            return self._result("NO TRADE", 0, risk_out,
                ["News window active — trading blocked"],
                pattern=pattern, pair=pair, timeframe=timeframe, regime=regime_label)

        if not risk_approved:
            return self._result("NO TRADE", 0, risk_out,
                [f"Risk rejected: {risk_out.get('reject_reason')}"],
                pattern=pattern, pair=pair, timeframe=timeframe, regime=regime_label)

        if final_signal == "NO TRADE" and has_conflict:
            return self._result("NO TRADE", 0, risk_out, [
                f"Sentiment conflict: Technical {rule_signal} vs Sentiment {sentiment_bias}",
                conflict_result.get("recommendation", ""),
            ], pattern=pattern, pair=pair, timeframe=timeframe, regime=regime_label)

        # Weighted voting
        votes = []
        if master_sig in ("BUY", "SELL"):
            votes += [master_sig] * 3
        llm_norm = "NO TRADE" if llm_signal == "WAIT" else llm_signal
        if llm_norm in ("BUY", "SELL"):
            votes += [llm_norm] * 2
        if rule_signal in ("BUY", "SELL"):
            votes += [rule_signal]

        buy_votes  = votes.count("BUY")
        sell_votes = votes.count("SELL")

        base_conf = master_conf if master_conf > 0 else round((rule_conf + llm_conf) / 2)

        # Sentiment boost/reduction
        sentiment_boost = 0
        if sentiment_bias in ("BULLISH", "STRONG_BULLISH") and buy_votes > sell_votes:
            sentiment_boost = +8
        elif sentiment_bias in ("BEARISH", "STRONG_BEARISH") and sell_votes > buy_votes:
            sentiment_boost = +8
        elif sentiment_bias in ("BULLISH", "STRONG_BULLISH") and sell_votes > buy_votes:
            sentiment_boost = -10
        elif sentiment_bias in ("BEARISH", "STRONG_BEARISH") and buy_votes > sell_votes:
            sentiment_boost = -10

        adj_conf = max(0, min(99, base_conf + conf_adjustment + sentiment_boost))

        if buy_votes > sell_votes and buy_votes >= self.MIN_CONSENSUS:
            decision = "BUY"
            reasons = [
                f"MasterAnalyst: {master_sig} | {master_story[:80]}",
                f"Rule: {rule_signal} ({rule_conf}%) | LLM: {llm_signal} ({llm_conf}%)",
                f"Sentiment: {sentiment_bias} (score {sentiment_score:+d}, adj {sentiment_boost:+d}%)",
                f"Risk: approved | Lot {risk_out.get('lot', risk_out.get('lot_size', 0))}",
            ]
            if master_risks:
                reasons.append(f"Risks: {', '.join(master_risks[:2])}")
            if master_critique:
                reasons.append(f"Critique: {master_critique[:80]}")

        elif sell_votes > buy_votes and sell_votes >= self.MIN_CONSENSUS:
            decision = "SELL"
            reasons = [
                f"MasterAnalyst: {master_sig} | {master_story[:80]}",
                f"Rule: {rule_signal} ({rule_conf}%) | LLM: {llm_signal} ({llm_conf}%)",
                f"Sentiment: {sentiment_bias} (score {sentiment_score:+d}, adj {sentiment_boost:+d}%)",
                f"Risk: approved | Lot {risk_out.get('lot', risk_out.get('lot_size', 0))}",
            ]
            if master_risks:
                reasons.append(f"Risks: {', '.join(master_risks[:2])}")
            if master_critique:
                reasons.append(f"Critique: {master_critique[:80]}")

        else:
            decision = "WAIT"
            adj_conf = 0
            reasons  = [
                f"No consensus — Master: {master_sig}, Rule: {rule_signal}, LLM: {llm_signal}",
                "Conflicting signals — wait for confirmation",
            ]
            if master_critique:
                reasons.append(f"Master critique: {master_critique[:80]}")

        # ──────────────────────────────────────────────────────
        # Day 53 — Dynamic Confidence Engine final pass
        # ──────────────────────────────────────────────────────
        confidence_engine_result = None
        if decision in ("BUY", "SELL"):
            confidence_engine_result = self.confidence_engine.adjust_decision(
                signal          = decision,
                base_confidence = adj_conf,
                pattern         = pattern,
                pair            = pair,
                timeframe       = timeframe,
                regime          = regime_label,
            )

            if confidence_engine_result["should_skip"]:
                decision = "NO TRADE"
                adj_conf = 0
                reasons.append(
                    f"⛔ ConfidenceEngine SKIP: {confidence_engine_result.get('skip_reason')}"
                )
            elif confidence_engine_result["decision"] == "WAIT":
                decision = "WAIT"
                adj_conf = 0
                reasons.append(
                    f"⚠️ ConfidenceEngine WAIT: {confidence_engine_result.get('reason')}"
                )
            else:
                old_conf = adj_conf
                adj_conf = confidence_engine_result["final_confidence"]
                reasons.append(
                    f"🎯 Day53 Confidence: {confidence_engine_result.get('reason')} "
                    f"({old_conf}% → {adj_conf}%)"
                )

        entry = master_ctx.get("master_entry") or risk_out.get("entry")
        sl    = master_ctx.get("master_sl")    or risk_out.get("sl_price")
        tp    = master_ctx.get("master_tp1")   or risk_out.get("tp_price")

        return self._result(
            decision, adj_conf, risk_out, reasons,
            entry=entry, sl=sl, tp=tp,
            pattern=pattern, pair=pair, timeframe=timeframe, regime=regime_label,
            confidence_engine_result=confidence_engine_result,
        )

    # ──────────────────────────────────────────────────────────
    # Day 53 helper — pattern extraction from analysis pipeline
    # ──────────────────────────────────────────────────────────

    def _extract_pattern(self, analysis_out: dict) -> str:
        """
        ConfidenceEngine pattern-key এর জন্য একটা single representative
        pattern বের করো। Priority: advanced pattern > candlestick pattern.
        """
        adv_ctx = analysis_out.get("advanced_pat_ctx", {}) or {}
        pat_ctx = analysis_out.get("pat_ctx", {}) or {}

        pattern = (
            adv_ctx.get("top_pattern")
            or adv_ctx.get("dominant_pattern")
            or pat_ctx.get("latest_pattern")
        )
        return pattern or "Unknown"

    def _result(self, decision, confidence, risk_out, reasons,
                entry=None, sl=None, tp=None,
                pattern=None, pair=None, timeframe=None, regime=None,
                confidence_engine_result=None) -> dict:
        return {
            "decision":   decision,
            "confidence": confidence,
            "entry":      entry or risk_out.get("entry"),
            "sl":         sl    or risk_out.get("sl_price"),
            "tp":         tp    or risk_out.get("tp_price"),
            "sl_pips":    risk_out.get("sl_pips", 0),
            "tp_pips":    risk_out.get("tp_pips", 0),
            "lot":        risk_out.get("lot", risk_out.get("lot_size", 0)),
            "rr":         risk_out.get("rr_ratio", 0),
            "reasons":    reasons,
            # Day 53 — needed downstream (LearningAgent / MemoryIntegration)
            # to call confidence_engine.record_outcome() after trade closes.
            "pattern":    pattern,
            "pair":       pair,
            "timeframe":  timeframe,
            "regime":     regime,
            "confidence_engine": confidence_engine_result,
        }

    def print_summary(self, result: dict) -> None:
        icons = {"BUY": "🟢", "SELL": "🔴", "WAIT": "🟡", "NO TRADE": "⚪"}
        icon  = icons.get(result["decision"], "⚪")
        bar   = "=" * 44
        log.info(bar)
        log.info(f"  {icon}  FINAL DECISION  (Day 42 + Day 53)")
        log.info(bar)
        log.info(f"  Decision    : {result['decision']}")
        log.info(f"  Confidence  : {result['confidence']}%")
        log.info(f"  Pattern     : {result.get('pattern')}  ({result.get('pair')} {result.get('timeframe')} {result.get('regime')})")
        if result["decision"] in ("BUY", "SELL"):
            log.info(f"  Entry       : {result['entry']}")
            log.info(f"  SL          : {result['sl']}  ({result['sl_pips']} pips)")
            log.info(f"  TP          : {result['tp']}  ({result['tp_pips']} pips)")
            log.info(f"  Lot         : {result['lot']}")
            log.info(f"  R:R         : 1:{result['rr']}")
        log.info("  -- Reasoning --")
        for r in result["reasons"]:
            log.info(f"    * {r}")
        log.info(bar)

    def get_ai_context(self, result: dict) -> dict:
        return {
            "final_decision":   result["decision"],
            "final_confidence": result["confidence"],
            "final_entry":      result.get("entry"),
            "final_sl":         result.get("sl"),
            "final_tp":         result.get("tp"),
            "final_lot":        result.get("lot"),
            "final_rr":         result.get("rr"),
            # Day 53
            "final_pattern":    result.get("pattern"),
            "final_pair":       result.get("pair"),
            "final_timeframe":  result.get("timeframe"),
            "final_regime":     result.get("regime"),
        }