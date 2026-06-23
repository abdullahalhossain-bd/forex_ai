"""
ml/confidence_fusion.py — Confidence fusion engine (Day 70)
==============================================================

Fuses individual model confidences into a single ensemble confidence
using three mechanisms:

1. **Weighted Average** — each model has a weight (from model_weights.json).
   Default: XGBoost 35%, LSTM 25%, RF 20%, Rules 20%.

2. **Market Regime Adjustment** — weights shift based on current regime:
   - TRENDING  → boost XGBoost + LSTM (they handle trends well)
   - RANGING   → boost RF + Rules (they handle ranges well)
   - VOLATILE  → boost Rules + RF (robust to noise)
   - BREAKOUT  → boost XGBoost + Rules

3. **Performance-Based Weight Adjustment** — if a model's recent win rate
   is significantly above/below average, its weight is adjusted up/down.
   This is the "Model Performance Memory" feature.

4. **Conflict Penalty** — if models disagree (strong dissent detected by
   VotingEngine), the ensemble confidence is penalized.

The output is a single calibrated confidence (0-100) that feeds into
the final trade decision.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger
from ml.voting_engine import ModelVote, VoteResult

log = get_logger("confidence_fusion")

WEIGHTS_PATH = Path(__file__).resolve().parent / "model_weights.json"


@dataclass
class FusionResult:
    """Output of the confidence fusion process."""
    final_confidence: float = 0.0       # 0-100
    weighted_confidence: float = 0.0    # before conflict penalty
    regime: str = "UNKNOWN"
    weights_used: Dict[str, float] = field(default_factory=dict)
    per_model_contribution: Dict[str, float] = field(default_factory=dict)
    conflict_penalty: float = 0.0
    has_conflict: bool = False
    conflict_reason: str = ""
    abstain: bool = False               # True if conflict too severe
    abstain_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ConfidenceFusion:
    """Fuses multi-model confidences into one calibrated ensemble confidence."""

    def __init__(self):
        self._lock = threading.RLock()
        self._default_weights = self._load_weights()
        self._performance_stats: Dict[str, Dict[str, float]] = {}
        # {"xgboost": {"win_rate": 64.0, "count": 100}, ...}

    def _load_weights(self) -> Dict[str, float]:
        """Load default weights from model_weights.json."""
        try:
            if WEIGHTS_PATH.exists():
                data = json.loads(WEIGHTS_PATH.read_text(encoding="utf-8"))
                return {
                    k: v for k, v in data.items()
                    if not k.startswith("_") and isinstance(v, (int, float))
                }
        except Exception as e:
            log.warning(f"[Fusion] weights load failed: {e}")
        return {"xgboost": 0.35, "random_forest": 0.20, "lstm": 0.25, "rules": 0.20}

    def _get_regime_adjustments(self, regime: str) -> Dict[str, float]:
        """Get weight adjustments for the current market regime."""
        regime = regime.upper()
        try:
            if WEIGHTS_PATH.exists():
                data = json.loads(WEIGHTS_PATH.read_text(encoding="utf-8"))
                adjustments = data.get("_regime_adjustments", {}).get(regime, {})
                return {k: v for k, v in adjustments.items() if isinstance(v, (int, float))}
        except Exception:
            pass
        return {}

    def update_performance(self, model_name: str, win_rate: float, sample_count: int) -> None:
        """Update a model's recent performance stats for weight adjustment."""
        with self._lock:
            self._performance_stats[model_name] = {
                "win_rate": win_rate,
                "count": sample_count,
            }
            log.info(f"[Fusion] performance updated: {model_name} WR={win_rate:.1f}% ({sample_count} samples)")

    def _performance_adjustment(self, model_name: str) -> float:
        """Calculate weight adjustment based on recent performance.

        If a model's win rate is above 60% (with ≥20 samples), boost its weight.
        If below 40%, reduce it.
        """
        stats = self._performance_stats.get(model_name)
        if not stats or stats.get("count", 0) < 20:
            return 0.0
        wr = stats.get("win_rate", 50.0)
        if wr >= 65:
            return 0.05   # +5% weight
        elif wr >= 60:
            return 0.03   # +3% weight
        elif wr <= 35:
            return -0.05  # -5% weight
        elif wr <= 40:
            return -0.03  # -3% weight
        return 0.0

    def fuse(
        self,
        votes: List[ModelVote],
        vote_result: VoteResult,
        regime: str = "UNKNOWN",
    ) -> FusionResult:
        """Fuse model confidences into a single ensemble confidence.

        Args:
            votes: List of ModelVote from all models.
            vote_result: The VoteResult from VotingEngine (contains dissent info).
            regime: Current market regime (TRENDING / RANGING / BREAKOUT / VOLATILE).

        Returns:
            FusionResult with final_confidence + breakdown.
        """
        result = FusionResult(regime=regime.upper())

        if not votes:
            return result

        # 1. Start with default weights
        weights = self._default_weights.copy()

        # 2. Apply regime adjustments
        regime_adj = self._get_regime_adjustments(regime)
        for model, adj in regime_adj.items():
            if model in weights:
                weights[model] += adj

        # 3. Apply performance adjustments
        for model in weights:
            weights[model] += self._performance_adjustment(model)

        # 4. Normalize weights to sum to 1.0
        total_weight = sum(weights.values())
        if total_weight > 0:
            weights = {k: v / total_weight for k, v in weights.items()}
        result.weights_used = {k: round(v, 4) for k, v in weights.items()}

        # 5. Weighted confidence
        weighted_sum = 0.0
        for vote in votes:
            w = weights.get(vote.model_name, 0.0)
            contribution = vote.confidence * w
            weighted_sum += contribution
            result.per_model_contribution[vote.model_name] = round(contribution, 2)

        result.weighted_confidence = round(weighted_sum, 2)

        # 6. Conflict penalty
        if vote_result.has_strong_dissent:
            result.has_conflict = True
            result.conflict_penalty = 15.0  # -15% confidence
            result.conflict_reason = vote_result.dissent_reason
            log.warning(f"[Fusion] conflict detected → -{result.conflict_penalty}% penalty")

        # 7. Final confidence
        result.final_confidence = max(0.0, min(100.0,
            result.weighted_confidence - result.conflict_penalty))

        # 8. Abstain check — if conflict is too severe
        try:
            data = json.loads(WEIGHTS_PATH.read_text(encoding="utf-8"))
            abstain_threshold = data.get("_thresholds", {}).get("abstain_if_conflict_above", 0.8)
        except Exception:
            abstain_threshold = 0.8

        # If 2+ models strongly dissent, abstain entirely
        if len(vote_result.dissenting_models) >= 2:
            result.abstain = True
            result.abstain_reason = (
                f"2+ models strongly dissent ({'/'.join(vote_result.dissenting_models)}) — "
                f"abstaining from trade"
            )
            result.final_confidence = 0.0

        return result


# ── Singleton ───────────────────────────────────────────────────────

_FUSION: Optional[ConfidenceFusion] = None


def get_confidence_fusion() -> ConfidenceFusion:
    global _FUSION
    if _FUSION is None:
        _FUSION = ConfidenceFusion()
    return _FUSION
