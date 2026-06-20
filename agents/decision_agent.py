# agents/decision_agent.py  —  Day 12 | Final Decision Agent

from utils.logger import get_logger

log = get_logger("decision_agent")


class DecisionAgent:
    """
    সব agent এর output দেখে final BUY / SELL / WAIT সিদ্ধান্ত নেয়।
    Rule engine + LLM + Risk তিনটাই agree করলে trade।
    """

    # কতগুলো agree করলে trade নেবো
    MIN_CONSENSUS = 2   # rule engine + LLM এর মধ্যে অন্তত 2টা match

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

        reasons  = []
        decision = "WAIT"

        # Gate 1 — news block
        if not news_ok:
            return self._result(
                "NO TRADE", 0, risk_out,
                ["News window active — trading blocked"]
            )

        # Gate 2 — risk not approved
        if not risk_approved:
            return self._result(
                "NO TRADE", 0, risk_out,
                [f"Risk rejected: {risk_out.get('reject_reason')}"]
            )

        # Normalize LLM signal (LLM returns WAIT, rule engine NO TRADE)
        llm_norm = "NO TRADE" if llm_signal == "WAIT" else llm_signal

        # Consensus check
        votes = {
            "rule": rule_signal,
            "llm":  llm_norm,
        }
        buy_votes  = sum(1 for v in votes.values() if v == "BUY")
        sell_votes = sum(1 for v in votes.values() if v == "SELL")

        avg_conf = round((rule_conf + llm_conf) / 2)

        if buy_votes >= self.MIN_CONSENSUS:
            decision = "BUY"
            reasons  = [
                f"Rule engine: BUY ({rule_conf}%)",
                f"LLM analyst: {llm_signal} ({llm_conf}%)",
                f"Risk: approved (lot {risk_out.get('lot', risk_out.get('lot_size'))})",
            ]

        elif sell_votes >= self.MIN_CONSENSUS:
            decision = "SELL"
            reasons  = [
                f"Rule engine: SELL ({rule_conf}%)",
                f"LLM analyst: {llm_signal} ({llm_conf}%)",
                f"Risk: approved (lot {risk_out.get('lot', risk_out.get('lot_size'))})",
            ]

        else:
            decision = "WAIT"
            avg_conf = 0
            reasons  = [
                f"No consensus — Rule: {rule_signal}, LLM: {llm_signal}",
                "Conflicting signals — wait for confirmation",
            ]

        return self._result(decision, avg_conf, risk_out, reasons)

    def _result(
        self,
        decision:  str,
        confidence: int,
        risk_out:  dict,
        reasons:   list,
    ) -> dict:
        return {
            "decision":   decision,
            "confidence": confidence,
            "entry":      risk_out.get("entry"),
            "sl":         risk_out.get("sl_price"),
            "tp":         risk_out.get("tp_price"),
            "sl_pips":    risk_out.get("sl_pips", 0),
            "tp_pips":    risk_out.get("tp_pips", 0),
            "lot":        risk_out.get("lot", risk_out.get("lot_size", 0)),
            "rr":         risk_out.get("rr_ratio", 0),
            "reasons":    reasons,
        }

    def print_summary(self, result: dict) -> None:
        icons = {"BUY": "🟢", "SELL": "🔴", "WAIT": "🟡", "NO TRADE": "⚪"}
        icon  = icons.get(result["decision"], "⚪")
        bar   = "═" * 44

        log.info(bar)
        log.info(f"  {icon}  FINAL DECISION")
        log.info(bar)
        log.info(f"  Decision    : {result['decision']}")
        log.info(f"  Confidence  : {result['confidence']}%")
        if result["decision"] in ("BUY", "SELL"):
            log.info(f"  Entry       : {result['entry']}")
            log.info(f"  SL          : {result['sl']}  ({result['sl_pips']} pips)")
            log.info(f"  TP          : {result['tp']}  ({result['tp_pips']} pips)")
            log.info(f"  Lot         : {result['lot']}")
            log.info(f"  R:R         : 1:{result['rr']}")
        log.info("  ── Reasoning ──")
        for r in result["reasons"]:
            log.info(f"    • {r}")
        log.info(bar)

    def get_ai_context(self, result: dict) -> dict:
        return {
            "final_decision":    result["decision"],
            "final_confidence":  result["confidence"],
            "final_entry":       result.get("entry"),
            "final_sl":          result.get("sl"),
            "final_tp":          result.get("tp"),
            "final_lot":         result.get("lot"),
            "final_rr":          result.get("rr"),
        }
