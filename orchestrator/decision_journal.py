"""
orchestrator/decision_journal.py — Minimal stub (Day 60 placeholder)
=====================================================================

This file exists to satisfy the import in `orchestrator/trading_orchestrator.py`:

    from orchestrator.decision_journal import DecisionJournal

The full DecisionJournal logic was never implemented in the upstream repo.
This stub provides the API surface so the orchestrator can import cleanly.
The live decision persistence lives in `agents/learning_agent.py::LearningAgent`
and `memory/trade_memory.py::TradeMemory`.

Marked LEGACY_STUB in core/obsolete.py.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.constants import MEMORY_DIR

log = logging.getLogger(__name__)


class DecisionJournal:
    """Append-only JSON journal of every decision the orchestrator makes.

    Each entry is a dict with at least:
        {ts, cycle, symbol, decision, confidence, allowed, reason}
    """

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else MEMORY_DIR / "decision_journal.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            self._entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            log.warning("DecisionJournal load failed: %s", e)

    def record(self, entry: Dict[str, Any]) -> None:
        entry.setdefault("ts", time.time())
        self._entries.append(entry)
        try:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception as e:
            log.warning("DecisionJournal write failed: %s", e)

    def recent(self, limit: int = 50) -> List[Dict[str, Any]]:
        return list(self._entries[-limit:])

    def status(self) -> Dict[str, Any]:
        return {
            "entries_recorded": len(self._entries),
            "path": str(self.path),
        }
