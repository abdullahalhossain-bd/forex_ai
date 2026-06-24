"""
monitoring/signal_debugger.py — Signal Pipeline Debugger (Day 81+)
====================================================================

WHY THIS EXISTS:
    The system has 9+ pipeline layers (Market → Indicators → SMC →
    Liquidity → Pattern → Sentiment → ML → LLM → Risk → Execution).
    Each layer can independently reject a trade. When the system runs
    24h without a single trade, there's no way to know WHICH layer
    is killing the signal — until now.

WHAT IT DOES:
    Every cycle, the trader calls `debugger.start_cycle(symbol)` then
    records each layer's verdict as it happens:

        debugger.record("market_data", "OK", "300 candles fetched")
        debugger.record("smc",         "BUY", "BOS confirmed @ 1.0850")
        debugger.record("ml",          "WAIT", "confidence 45% < 50% threshold")
        debugger.record("risk",        "REJECTED", "lot 0 — Kelly negative")
        debugger.record_final("NO_TRADE", "Risk rejected: Kelly negative")

    At end of cycle, debugger logs a one-block summary so you can
    instantly see WHERE signals die:

        ┌─ EURUSD M15 cycle ─────────────────────────┐
        │ market_data    OK       300 candles        │
        │ indicators     OK       RSI=52 trend=UP    │
        │ smc            BUY      BOS @ 1.0850       │
        │ liquidity      DETECTED 1.0820 sweep       │
        │ pattern        NEUTRAL  no signal          │
        │ sentiment      BULLISH  +8 boost           │
        │ ml             BUY      68% confidence     │
        │ llm            WAIT     45% (below 50%)   │
        │ risk           REJECT   Kelly negative     │
        │ permission     BLOCK    3/5 checks passed  │
        │ ────────────────────────────────────────── │
        │ FINAL: NO_TRADE — Risk rejected            │
        │ ────────────────────────────────────────── │
        │ BLOCKED_AT: risk                           │
        └────────────────────────────────────────────┘

USAGE:
    from monitoring.signal_debugger import get_signal_debugger

    debugger = get_signal_debugger()
    debugger.start_cycle("EURUSD", "M15")

    # ... in market_agent.py:
    debugger.record("market_data", "OK", f"{len(df)} candles")

    # ... in smc_engine.py:
    debugger.record("smc", signal, f"{structure} @ {level}")

    # ... at end of cycle in trader.py:
    debugger.record_final(final_action, reject_reason)
    debugger.log_cycle_summary()
    debugger.save_to_file()  # for dashboard
"""
from __future__ import annotations

import json
import os
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

from utils.logger import get_logger

log = get_logger("signal_debugger")

# Where the latest cycle's full debug log lives (dashboard reads this)
DEBUG_FILE = "memory/signal_debug.jsonl"
DEBUG_HISTORY_LIMIT = 500  # keep last N cycles in JSONL


# ── Per-layer verdict ─────────────────────────────────────────

@dataclass
class LayerVerdict:
    """One pipeline layer's verdict for one cycle."""
    layer: str           # e.g. "market_data", "smc", "ml", "llm", "risk"
    status: str          # OK / BUY / SELL / WAIT / REJECT / BLOCK / ERROR
    detail: str = ""     # short human-readable reason
    timestamp: float = field(default_factory=time.time)

    @property
    def icon(self) -> str:
        return {
            "OK":       "[OK]",
            "BUY":      "[BUY]",
            "SELL":     "[SELL]",
            "WAIT":     "[WAIT]",
            "REJECT":   "[REJ]",
            "BLOCK":    "[BLK]",
            "ERROR":    "[ERR]",
            "NEUTRAL":  "[---]",
            "DETECTED": "[DET]",
        }.get(self.status, f"[{self.status[:3].upper()}]")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer":      self.layer,
            "status":     self.status,
            "detail":     self.detail,
            "timestamp":  self.timestamp,
        }


# ── Per-cycle record ──────────────────────────────────────────

@dataclass
class CycleDebug:
    """All layer verdicts + final outcome for one cycle."""
    symbol: str
    timeframe: str
    started_at: float
    layers: List[LayerVerdict] = field(default_factory=list)
    final_action: str = ""
    final_reason: str = ""
    blocked_at: Optional[str] = None  # which layer killed the trade

    def record(self, layer: str, status: str, detail: str = "") -> None:
        self.layers.append(LayerVerdict(layer=layer, status=status, detail=detail))

    def record_final(self, action: str, reason: str = "") -> None:
        self.final_action = action
        self.final_reason = reason
        # Find which layer blocked the trade.
        # A "blocker" is a layer with status REJECT/BLOCK/ERROR — these are
        # HARD blocks (the layer explicitly refused to proceed).
        # WAIT is soft — it just means "no strong opinion" — so we don't
        # count it as a blocker.
        # We look for the LAST hard-block in the chain, because that's the
        # one that actually killed the trade (earlier blocks may have been
        # worked around by subsequent layers).
        for v in reversed(self.layers):
            if v.status in ("REJECT", "BLOCK", "ERROR"):
                self.blocked_at = v.layer
                break
        # If no hard-block but final is NO_TRADE/WAIT, the killer is the
        # last layer that emitted WAIT (no signal)
        if not self.blocked_at and action in ("NO_TRADE", "WAIT"):
            for v in reversed(self.layers):
                if v.status == "WAIT":
                    self.blocked_at = v.layer
                    break

    def summary_block(self) -> str:
        """One-box ASCII summary for the log file."""
        lines = [
            f"┌─ {self.symbol} {self.timeframe} cycle ─────────────────────────┐",
        ]
        for v in self.layers:
            lines.append(f"│ {v.layer:<14} {v.icon:<7} {v.detail:<22} │")
        lines.append("│ ────────────────────────────────────────── │")
        action_icon = {
            "BUY":     "🟢 BUY",
            "SELL":    "🔴 SELL",
            "WAIT":    "⏳ WAIT",
            "NO_TRADE":"⛔ NO_TRADE",
        }.get(self.final_action, self.final_action)
        lines.append(f"│ FINAL: {action_icon:<9} — {self.final_reason[:24]:<24} │")
        if self.blocked_at:
            lines.append(f"│ ────────────────────────────────────────── │")
            lines.append(f"│ BLOCKED_AT: {self.blocked_at:<31} │")
        lines.append("└────────────────────────────────────────────┘")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol":      self.symbol,
            "timeframe":   self.timeframe,
            "started_at":  datetime.fromtimestamp(self.started_at, tz=timezone.utc).isoformat(),
            "layers":      [v.to_dict() for v in self.layers],
            "final_action": self.final_action,
            "final_reason": self.final_reason,
            "blocked_at":  self.blocked_at,
        }


# ── Singleton debugger ────────────────────────────────────────

class SignalDebugger:
    """
    Accumulates layer verdicts across the current cycle and across
    historical cycles (for trend analysis).
    """

    def __init__(self, history_limit: int = 500):
        self._current: Optional[CycleDebug] = None
        self._history: Deque[Dict[str, Any]] = deque(maxlen=history_limit)
        # Aggregate stats — how often is each layer the blocker?
        self._block_counts: Dict[str, int] = {}

    # ── Per-cycle API ──────────────────────────────────────────

    def start_cycle(self, symbol: str, timeframe: str) -> None:
        self._current = CycleDebug(
            symbol=symbol,
            timeframe=timeframe,
            started_at=time.time(),
        )

    def record(self, layer: str, status: str, detail: str = "") -> None:
        """Record one layer's verdict. No-op if start_cycle wasn't called."""
        if self._current is None:
            return
        self._current.record(layer, status, detail)

    def record_final(self, action: str, reason: str = "") -> None:
        if self._current is None:
            return
        self._current.record_final(action, reason)

    def log_cycle_summary(self) -> None:
        """Print the one-box summary to the logger."""
        if self._current is None:
            return
        log.info("\n" + self._current.summary_block())

    def save_to_file(self) -> None:
        """Persist this cycle to JSONL for dashboard / trend analysis."""
        if self._current is None:
            return
        os.makedirs(os.path.dirname(DEBUG_FILE), exist_ok=True)
        record = self._current.to_dict()
        self._history.append(record)
        if self._current.blocked_at:
            self._block_counts[self._current.blocked_at] = \
                self._block_counts.get(self._current.blocked_at, 0) + 1
        try:
            with open(DEBUG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, default=str) + "\n")
        except Exception as e:
            log.debug(f"signal_debugger save failed: {e}")

    # ── Aggregate stats ────────────────────────────────────────

    def block_stats(self) -> Dict[str, Any]:
        """Summary of which layers blocked trades over the recent history."""
        total = sum(self._block_counts.values())
        return {
            "total_blocked_cycles": total,
            "by_layer":             dict(self._block_counts),
            "most_common_blocker":  max(self._block_counts,
                                        key=self._block_counts.get) if self._block_counts else None,
        }

    def recent_blocks(self, last_n: int = 10) -> List[Dict[str, Any]]:
        """Last N cycles that ended in NO_TRADE — for dashboard."""
        return [r for r in self._history if r.get("final_action") in ("NO_TRADE", "WAIT")][-last_n:]

    def recent_trades(self, last_n: int = 10) -> List[Dict[str, Any]]:
        """Last N cycles that ended in a trade — for dashboard."""
        return [r for r in self._history if r.get("final_action") in ("BUY", "SELL")][-last_n:]


# ── Singleton accessor ────────────────────────────────────────

_DEBUGGER: Optional[SignalDebugger] = None


def get_signal_debugger() -> SignalDebugger:
    global _DEBUGGER
    if _DEBUGGER is None:
        _DEBUGGER = SignalDebugger()
    return _DEBUGGER
