# agents/learning_agent.py  —  Day 12 | Self-Learning Agent

import json
import os
from datetime import datetime
from utils.logger import get_logger

log  = get_logger("learning_agent")
PATH = "memory/trade_memory.json"


class LearningAgent:
    """
    প্রতিটা decision save করে।
    ভবিষ্যতে outcome জানলে শিখবে।
    Pattern performance track করবে।
    """

    def save_decision(
        self,
        decision_out:  dict,
        analysis_out:  dict,
        market_out:    dict,
    ) -> None:
        os.makedirs("memory", exist_ok=True)
        history = self._load()

        entry = {
            "id":          len(history) + 1,
            "timestamp":   datetime.utcnow().isoformat(),
            "symbol":      market_out.get("symbol"),
            "timeframe":   market_out.get("timeframe"),
            "decision":    decision_out.get("decision"),
            "confidence":  decision_out.get("confidence"),
            "entry":       decision_out.get("entry"),
            "sl":          decision_out.get("sl"),
            "tp":          decision_out.get("tp"),
            "lot":         decision_out.get("lot"),
            "rr":          decision_out.get("rr"),
            "regime":      market_out.get("regime", {}).get("regime"),
            "trend":       market_out.get("ind_ctx", {}).get("trend"),
            "rsi":         market_out.get("ind_ctx", {}).get("rsi"),
            "patterns":    analysis_out.get("pat_ctx", {}).get("recent_patterns", []),
            "rule_signal": analysis_out.get("signal", {}).get("signal"),
            "llm_signal":  analysis_out.get("llm", {}).get("signal"),
            "reasons":     decision_out.get("reasons", []),
            # outcome পরে update হবে (backtester/live)
            "outcome":     None,
            "pnl_pips":    None,
            "result":      None,   # WIN / LOSS / BE
        }

        history.append(entry)
        self._save(history)
        log.info(f"[LearningAgent] Decision #{entry['id']} saved — {entry['decision']}")

    def get_performance_stats(self) -> dict:
        history = self._load()
        closed  = [t for t in history if t.get("result")]

        if not closed:
            return {"total_decisions": len(history), "closed_trades": 0}

        wins    = [t for t in closed if t["result"] == "WIN"]
        losses  = [t for t in closed if t["result"] == "LOSS"]
        win_rate = round(len(wins) / len(closed) * 100, 1)
        avg_pnl  = round(
            sum(t.get("pnl_pips", 0) for t in closed) / len(closed), 1
        )

        # Pattern performance
        pat_stats = {}
        for t in closed:
            for p in (t.get("patterns") or []):
                if p not in pat_stats:
                    pat_stats[p] = {"win": 0, "loss": 0}
                if t["result"] == "WIN":
                    pat_stats[p]["win"] += 1
                else:
                    pat_stats[p]["loss"] += 1

        return {
            "total_decisions": len(history),
            "closed_trades":   len(closed),
            "wins":            len(wins),
            "losses":          len(losses),
            "win_rate":        win_rate,
            "avg_pnl_pips":    avg_pnl,
            "pattern_stats":   pat_stats,
        }

    def _load(self) -> list:
        if not os.path.exists(PATH):
            return []
        try:
            with open(PATH) as f:
                return json.load(f)
        except Exception:
            return []

    def _save(self, data: list) -> None:
        with open(PATH, "w") as f:
            json.dump(data[-500:], f, indent=2)   # শেষ 500টা রাখো