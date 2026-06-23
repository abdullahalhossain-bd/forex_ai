"""
core/master_decision.py — Master Decision Engine (Day 73)
============================================================

The central brain coordination layer. Collects signals from ALL
intelligence layers, fuses them with dynamic weights, validates
the decision, and produces the FINAL BUY/SELL/WAIT signal.

Pipeline:
  1. Collect signals from 4 layers:
     - Rule Engine (Confluence Day 67)
     - ML Ensemble (Day 69-70)
     - RL Agent (Day 71)
     - LLM Analyst (MasterAnalyst Day 42+)
  2. SignalFusion → weighted confidence + conflict detection
  3. DecisionValidator → emergency checks + reasonableness
  4. ConfidenceManager → dynamic weight adjustment from outcomes
  5. Final output: BUY/SELL/WAIT + confidence + position size + explanation

This replaces the fragmented Day 66-72 integration in AnalysisAgent
with a single clean coordination layer.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

from core.signal_fusion import SignalFusion, LayerSignal, FusionResult, get_signal_fusion
from core.decision_validator import DecisionValidator, ValidationResult, get_decision_validator
from core.confidence_manager import ConfidenceManager, get_confidence_manager

log = get_logger("master_decision")

DB_PATH = Path("memory/master_decisions.db")


@dataclass
class MasterDecision:
    """The final output of the Master Decision Engine."""
    pair: str
    timeframe: str
    final_signal: str          # BUY / SELL / WAIT / NO_TRADE
    master_confidence: float   # 0-100
    agreement: str             # "4/4"
    position_size: str         # FULL / HALF / REDUCED / WAIT / NO_TRADE
    position_multiplier: float
    layer_signals: Dict[str, str] = field(default_factory=dict)  # {"rule_engine": "BUY 71%"}
    has_conflict: bool = False
    conflict_reason: str = ""
    override_reason: str = ""
    explanation: List[str] = field(default_factory=list)
    weights_used: Dict[str, float] = field(default_factory=dict)
    validation_checks: List[Dict[str, Any]] = field(default_factory=list)
    generated_at: str = ""
    decision_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_telegram_alert(self) -> Optional[str]:
        """Format a high-conviction Telegram alert."""
        if self.final_signal not in ("BUY", "SELL"):
            return None
        dir_emoji = "🟢" if self.final_signal == "BUY" else "🔴"
        lines = [
            f"{dir_emoji} FOREX AI MASTER SIGNAL",
            f"━━━━━━━━━━━━━━━━━━━━━",
            f"Pair: {self.pair} ({self.timeframe})",
            f"Direction: {self.final_signal}",
            f"4-Layer Agreement: {self.agreement}",
            f"Master Confidence: {self.master_confidence:.0f}%",
            f"Position: {self.position_size}",
            f"━━━━━━━━━━━━━━━━━━━━━",
            f"Layers:",
        ]
        for layer, info in self.layer_signals.items():
            lines.append(f"  {info}")
        lines.append(f"━━━━━━━━━━━━━━━━━━━━━")
        if self.has_conflict:
            lines.append(f"⚠️ {self.conflict_reason[:100]}")
        if self.explanation:
            lines.append("Why:")
            for exp in self.explanation[:3]:
                lines.append(f"  {exp}")
        return "\n".join(lines)


class MasterDecisionEngine:
    """Central brain — collects, fuses, validates, and outputs the final decision."""

    def __init__(self):
        self.fusion = get_signal_fusion()
        self.validator = get_decision_validator()
        self.confidence_mgr = get_confidence_manager()
        self._lock = threading.RLock()
        self._init_db()

    def _init_db(self) -> None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(DB_PATH)) as c:
            c.execute("""
                CREATE TABLE IF NOT EXISTS master_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pair TEXT NOT NULL,
                    timeframe TEXT,
                    rule_signal TEXT,
                    ml_signal TEXT,
                    rl_signal TEXT,
                    llm_signal TEXT,
                    agreement TEXT,
                    confidence REAL,
                    final_signal TEXT,
                    position_size TEXT,
                    has_conflict INTEGER,
                    override_reason TEXT,
                    timestamp TEXT NOT NULL,
                    actual_result TEXT,
                    pnl_usd REAL
                )
            """)
            c.commit()

    def decide(
        self,
        pair: str,
        timeframe: str,
        rule_signal: str = "WAIT",
        rule_confidence: float = 0.0,
        ml_signal: str = "WAIT",
        ml_confidence: float = 0.0,
        rl_signal: str = "HOLD",
        rl_confidence: float = 50.0,
        llm_signal: str = "WAIT",
        llm_confidence: float = 0.0,
        rule_reasoning: str = "",
        ml_reasoning: str = "",
        rl_reasoning: str = "",
        llm_reasoning: str = "",
    ) -> MasterDecision:
        """Run the full master decision pipeline.

        Args:
            pair: Trading pair (e.g. "EURUSD").
            timeframe: Timeframe label.
            rule_signal/confidence: From Day 67 Confluence Engine.
            ml_signal/confidence: From Day 69-70 ML Ensemble.
            rl_signal/confidence: From Day 71 RL Agent.
            llm_signal/confidence: From Day 42+ MasterAnalyst.

        Returns:
            MasterDecision with the final signal + full breakdown.
        """
        # Get dynamic weights
        weights = self.confidence_mgr.get_weights()

        # ── Step 1: Collect signals from all 4 layers ─────────────
        signals: List[LayerSignal] = []

        # Normalize signals
        def _norm(s):
            if "STRONG_BUY" in str(s): return "BUY"
            if "STRONG_SELL" in str(s): return "SELL"
            return str(s).upper() if s else "WAIT"

        rule_sig = _norm(rule_signal)
        ml_sig = _norm(ml_signal)
        rl_sig = _norm(rl_signal) if rl_signal != "HOLD" else "WAIT"
        llm_sig = _norm(llm_signal)

        # Only include layers with meaningful signals
        if rule_sig in ("BUY", "SELL") or rule_confidence > 0:
            signals.append(LayerSignal(
                layer="rule_engine", signal=rule_sig,
                confidence=max(rule_confidence, 50.0 if rule_sig in ("BUY", "SELL") else 0),
                weight=weights.get("rule_engine", 0.30),
                reasoning=rule_reasoning[:100],
            ))

        if ml_sig in ("BUY", "SELL") or ml_confidence > 0:
            signals.append(LayerSignal(
                layer="ml_ensemble", signal=ml_sig,
                confidence=max(ml_confidence, 50.0 if ml_sig in ("BUY", "SELL") else 0),
                weight=weights.get("ml_ensemble", 0.30),
                reasoning=ml_reasoning[:100],
            ))

        if rl_sig in ("BUY", "SELL"):
            signals.append(LayerSignal(
                layer="rl_agent", signal=rl_sig,
                confidence=max(rl_confidence, 50.0),
                weight=weights.get("rl_agent", 0.20),
                reasoning=rl_reasoning[:100],
            ))

        if llm_sig in ("BUY", "SELL") or llm_confidence > 0:
            signals.append(LayerSignal(
                layer="llm_analyst", signal=llm_sig,
                confidence=max(llm_confidence, 50.0 if llm_sig in ("BUY", "SELL") else 0),
                weight=weights.get("llm_analyst", 0.20),
                reasoning=llm_reasoning[:100],
            ))

        # If no signals at all → WAIT
        if not signals:
            return MasterDecision(
                pair=pair.upper(), timeframe=timeframe,
                final_signal="WAIT", master_confidence=0.0,
                agreement="0/4", position_size="NO_TRADE", position_multiplier=0.0,
                explanation=["No intelligence layers produced a signal"],
                generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            )

        # ── Step 2: Fuse signals ───────────────────────────────────
        fusion_result = self.fusion.fuse(signals)

        # ── Step 3: Validate ───────────────────────────────────────
        validation = self.validator.validate(fusion_result, signals)

        # ── Step 4: Build final decision ───────────────────────────
        # Build layer display dict
        layer_display: Dict[str, str] = {}
        for s in signals:
            layer_display[s.layer] = f"{s.signal} {s.confidence:.0f}%"

        decision = MasterDecision(
            pair=pair.upper(),
            timeframe=timeframe,
            final_signal=validation.final_signal,
            master_confidence=validation.confidence,
            agreement=fusion_result.agreement,
            position_size=validation.position_size,
            position_multiplier=validation.position_multiplier,
            layer_signals=layer_display,
            has_conflict=fusion_result.has_conflict,
            conflict_reason=fusion_result.conflict_reason,
            override_reason=validation.override_reason,
            explanation=fusion_result.explanation,
            weights_used={k: round(v, 3) for k, v in weights.items()},
            validation_checks=validation.checks or [],
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

        # ── Step 5: Persist to DB ──────────────────────────────────
        try:
            with sqlite3.connect(str(DB_PATH)) as c:
                cur = c.execute("""
                    INSERT INTO master_decisions
                    (pair, timeframe, rule_signal, ml_signal, rl_signal, llm_signal,
                     agreement, confidence, final_signal, position_size, has_conflict,
                     override_reason, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    decision.pair, decision.timeframe,
                    layer_display.get("rule_engine", ""),
                    layer_display.get("ml_ensemble", ""),
                    layer_display.get("rl_agent", ""),
                    layer_display.get("llm_analyst", ""),
                    decision.agreement, decision.master_confidence,
                    decision.final_signal, decision.position_size,
                    1 if decision.has_conflict else 0,
                    decision.override_reason,
                    decision.generated_at,
                ))
                c.commit()
                decision.decision_id = cur.lastrowid
        except Exception as e:
            log.debug(f"[MasterDecision] DB save failed: {e}")

        log.info(
            f"[MasterDecision] {pair} {timeframe} → {decision.final_signal} "
            f"| conf={decision.master_confidence:.0f}% | agreement={decision.agreement} "
            f"| position={decision.position_size}"
            f"{' | CONFLICT' if decision.has_conflict else ''}"
            f"{' | OVERRIDE: ' + decision.override_reason if decision.override_reason else ''}"
        )

        return decision

    def record_outcome(self, decision_id: int, result: str, pnl_usd: float,
                       layer_predictions: Optional[Dict[str, str]] = None) -> None:
        """Record the actual trade outcome and update layer accuracy."""
        try:
            with sqlite3.connect(str(DB_PATH)) as c:
                c.execute(
                    "UPDATE master_decisions SET actual_result = ?, pnl_usd = ? WHERE id = ?",
                    (result, float(pnl_usd), decision_id),
                )
                c.commit()
        except Exception:
            pass

        # Update each layer's accuracy
        if layer_predictions:
            for layer, predicted in layer_predictions.items():
                self.confidence_mgr.record_outcome(layer, predicted, result)

    def stats(self) -> Dict[str, Any]:
        """Return master decision engine stats."""
        try:
            with sqlite3.connect(str(DB_PATH)) as c:
                total = c.execute("SELECT COUNT(*) FROM master_decisions").fetchone()[0]
                with_result = c.execute("SELECT COUNT(*) FROM master_decisions WHERE actual_result IS NOT NULL").fetchone()[0]
                wins = c.execute("SELECT COUNT(*) FROM master_decisions WHERE actual_result = 'WIN'").fetchone()[0]
                losses = c.execute("SELECT COUNT(*) FROM master_decisions WHERE actual_result = 'LOSS'").fetchone()[0]
        except Exception:
            total = with_result = wins = losses = 0
        return {
            "total_decisions": total,
            "closed_with_result": with_result,
            "wins": wins,
            "losses": losses,
            "win_rate": round((wins / (wins + losses) * 100) if (wins + losses) else 0, 1),
            "confidence_manager": self.confidence_mgr.status(),
        }


# ── Singleton ───────────────────────────────────────────────────────

_ENGINE: Optional[MasterDecisionEngine] = None


def get_master_decision_engine() -> MasterDecisionEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = MasterDecisionEngine()
    return _ENGINE
