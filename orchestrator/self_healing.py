"""
orchestrator/self_healing.py — Minimal stub (Day 60 placeholder)
=================================================================

This file exists to satisfy the import in `orchestrator/trading_orchestrator.py`:

    from orchestrator.self_healing import SelfHealingSystem

The full SelfHealingSystem logic was never implemented in the upstream repo.
This stub provides the API surface so the orchestrator can import cleanly.

Marked LEGACY_STUB in core/obsolete.py.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

log = logging.getLogger(__name__)


class SelfHealingSystem:
    """Detects recurring runtime errors and applies automatic remediation.

    Currently a no-op stub that records issues for future pattern analysis.
    Extension points:
      * restart crashed sub-systems
      * rotate log files
      * reconnect MT5
      * rebuild corrupted DB indexes
    """

    def __init__(self):
        self._issues: List[Dict[str, Any]] = []
        self._remediations: List[Dict[str, Any]] = []

    def record_issue(self, kind: str, detail: str) -> None:
        entry = {"ts": time.time(), "kind": kind, "detail": detail}
        self._issues.append(entry)
        log.warning("SelfHealing issue: %s — %s", kind, detail)
        # Try a no-op remediation so the orchestrator's _check_self_healing
        # has something to consume.
        self._try_remediate(kind, detail)

    def _try_remediate(self, kind: str, detail: str) -> bool:
        """Future: dispatch on `kind` to apply fixes. Currently a no-op."""
        self._remediations.append({"ts": time.time(), "kind": kind, "action": "noop"})
        return False

    def get_recent_issues(self, limit: int = 20) -> List[Dict[str, Any]]:
        return list(self._issues[-limit:])

    def status(self) -> Dict[str, Any]:
        return {
            "issues_recorded": len(self._issues),
            "remediations_attempted": len(self._remediations),
        }
