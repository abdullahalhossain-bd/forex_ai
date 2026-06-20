# agents/decision_agent.py  —  Day 42 | Final Decision Agent (Master-Aware)

from utils.logger import get_logger

log = get_logger("decision_agent")


class DecisionAgent:
    """
    Day 42: MasterAnalyst output-কে primary signal source হিসেবে ব্যবহার করে।

    Vote hierarchy:
        1. MasterAnalyst (LLM synthesized brain)   — weight 3
        2. Classic LLM Analyst                     — weight 2
        3. Rule engine                             — weight 1

    Confidence = MasterAnalyst final_confidence (already weighted internally).
    """

    MIN_CONSENSUS = 2

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

        reasons  = []
        decision = "WAIT"

        # Gates
        if not news_ok:
            return self._result("NO TRADE", 0, risk_out,
                ["News window active — trading blocked"])

        if not risk_approved:
            return self._result("NO TRADE", 0, risk_out,
                [f"Risk rejected: {risk_out.get('reject_reason')}"])

        if final_signal == "NO TRADE" and has_conflict:
            return self._result("NO TRADE", 0, risk_out, [
                f"Sentiment conflict: Technical {rule_signal} vs Sentiment {sentiment_bias}",
                conflict_result.get("recommendation", ""),
            ])

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

        entry = master_ctx.get("master_entry") or risk_out.get("entry")
        sl    = master_ctx.get("master_sl")    or risk_out.get("sl_price")
        tp    = master_ctx.get("master_tp1")   or risk_out.get("tp_price")

        return self._result(decision, adj_conf, risk_out, reasons, entry=entry, sl=sl, tp=tp)

    def _result(self, decision, confidence, risk_out, reasons,
                entry=None, sl=None, tp=None) -> dict:
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
        }

    def print_summary(self, result: dict) -> None:
        icons = {"BUY": "🟢", "SELL": "🔴", "WAIT": "🟡", "NO TRADE": "⚪"}
        icon  = icons.get(result["decision"], "⚪")
        bar   = "=" * 44
        log.info(bar)
        log.info(f"  {icon}  FINAL DECISION  (Day 42)")
        log.info(bar)
        log.info(f"  Decision    : {result['decision']}")
        log.info(f"  Confidence  : {result['confidence']}%")
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
        }