"""
risk/confidence_scaler.py — Confidence-Based Position Scaling (Day 76)
=======================================================================

Scales position size based on the Master Decision Engine's confidence.

| Confidence | Multiplier | Description |
|---:|---:|---|
| < 55% | 0.0× | Reject — below minimum |
| 55-64% | 0.5× | Marginal — reduced size |
| 65-74% | 0.8× | Acceptable — slightly reduced |
| 75-84% | 1.0× | Normal — full base size |
| 85-89% | 1.3× | High — boosted size |
| 90-94% | 1.5× | Very high — strong boost |
| 95%+ | 1.8× | Exceptional — max boost |

Hard cap: never exceed 2.0× regardless of confidence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional

from utils.logger import get_logger

log = get_logger("confidence_scaler")

MAX_CONFIDENCE_MULT = 2.0  # absolute hard cap


@dataclass
class ConfidenceResult:
    """Output of confidence scaling."""
    factor: float       # multiplier (0.0 to 2.0)
    level: str          # REJECT / MARGINAL / ACCEPTABLE / NORMAL / HIGH / VERY_HIGH / EXCEPTIONAL
    confidence: float   # original confidence
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ConfidenceScaler:
    """Confidence-based position size scaling."""

    # Confidence thresholds and multipliers
    THRESHOLDS = [
        (95, 1.8, "EXCEPTIONAL"),
        (90, 1.5, "VERY_HIGH"),
        (85, 1.3, "HIGH"),
        (75, 1.0, "NORMAL"),
        (65, 0.8, "ACCEPTABLE"),
        (55, 0.5, "MARGINAL"),
    ]

    def scale(self, confidence: float) -> ConfidenceResult:
        """Calculate confidence-based position multiplier.

        Args:
            confidence: Master Decision confidence (0-100).

        Returns:
            ConfidenceResult with multiplier + level.
        """
        confidence = max(0.0, min(100.0, confidence))

        for threshold, mult, level in self.THRESHOLDS:
            if confidence >= threshold:
                return ConfidenceResult(
                    factor=mult,
                    level=level,
                    confidence=confidence,
                    reason=f"Confidence {confidence:.0f}% → {level} → ×{mult}",
                )

        # Below 55% — reject
        return ConfidenceResult(
            factor=0.0,
            level="REJECT",
            confidence=confidence,
            reason=f"Confidence {confidence:.0f}% < 55% minimum → reject",
        )


# ── Singleton ───────────────────────────────────────────────────────

_SCALER: Optional[ConfidenceScaler] = None


def get_confidence_scaler() -> ConfidenceScaler:
    global _SCALER
    if _SCALER is None:
        _SCALER = ConfidenceScaler()
    return _SCALER
