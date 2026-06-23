"""
core/health_monitor.py — Unified health monitor
================================================

A single health-check service that periodically polls every registered
service, records its health into the event bus, and exposes a JSON snapshot
for the dashboard.

Replaces both the dead `core/monitoring_system.py` (which is never imported)
and the dead `automation/system_health.py`. Those modules still exist but
their canonical replacement is this file.

Public API:
  * `HealthMonitor` — the monitor class.
  * `HealthStatus` — enum of system health states.
  * `get_health_monitor()` — singleton accessor.
"""

from __future__ import annotations

import logging
import platform
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from core.event_bus import EventBus, get_bus
from core.service_registry import ServiceRegistry, ServiceStatus, get_registry

log = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheck:
    """A single named health check."""
    name: str
    fn: Callable[[], Dict[str, Any]]
    critical: bool = False
    last_result: Optional[Dict[str, Any]] = None
    last_run: Optional[float] = None


@dataclass
class HealthSnapshot:
    """A point-in-time snapshot of system health."""
    timestamp: float
    overall: HealthStatus
    services: Dict[str, Dict[str, Any]]
    checks: Dict[str, Dict[str, Any]]
    system: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat(),
            "overall": self.overall.value,
            "services": self.services,
            "checks": self.checks,
            "system": self.system,
        }


class HealthMonitor:
    """Background health monitor. Runs in a daemon thread when started."""

    def __init__(
        self,
        registry: Optional[ServiceRegistry] = None,
        bus: Optional[EventBus] = None,
        interval_sec: float = 30.0,
    ):
        self.registry = registry or get_registry()
        self.bus = bus or get_bus()
        self.interval_sec = max(5.0, interval_sec)
        self._checks: Dict[str, HealthCheck] = {}
        self._history: List[HealthSnapshot] = []
        self._history_max = 100
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._last_snapshot: Optional[HealthSnapshot] = None

    # ── registration ────────────────────────────────────────────────

    def register_check(self, name: str, fn: Callable[[], Dict[str, Any]], critical: bool = False) -> None:
        """Register a custom health check. `fn` must return a dict with at
        least `{"ok": bool}`. Add `"detail": "..."` for context."""
        with self._lock:
            self._checks[name] = HealthCheck(name=name, fn=fn, critical=critical)

    # ── polling ─────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="health-monitor", daemon=True
        )
        self._thread.start()
        log.info("HealthMonitor started (interval=%ss)", self.interval_sec)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        log.info("HealthMonitor stopped")

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                snap = self.run_once()
                self.bus.publish("health.report", snap.to_dict(), source="health_monitor")
            except Exception as e:
                log.error("HealthMonitor loop error: %s", e, exc_info=True)
            self._stop.wait(self.interval_sec)

    # ── one-shot ────────────────────────────────────────────────────

    def run_once(self) -> HealthSnapshot:
        """Run every registered check + collect service health from registry."""
        # Service health from registry
        services = self.registry.health()

        # Custom checks
        checks: Dict[str, Dict[str, Any]] = {}
        with self._lock:
            check_items = list(self._checks.items())
        for name, chk in check_items:
            t0 = time.time()
            try:
                result = chk.fn() or {}
                if "ok" not in result:
                    result["ok"] = True
                result["duration_ms"] = round((time.time() - t0) * 1000, 1)
            except Exception as e:
                result = {"ok": False, "error": str(e), "duration_ms": round((time.time() - t0) * 1000, 1)}
            chk.last_result = result
            chk.last_run = time.time()
            checks[name] = result

        # System metrics
        system = self._collect_system_metrics()

        # Overall status
        overall = self._compute_overall(services, checks)

        snap = HealthSnapshot(
            timestamp=time.time(),
            overall=overall,
            services=services,
            checks=checks,
            system=system,
        )
        with self._lock:
            self._history.append(snap)
            if len(self._history) > self._history_max:
                self._history.pop(0)
            self._last_snapshot = snap
        return snap

    def _compute_overall(self, services: Dict[str, Dict], checks: Dict[str, Dict]) -> HealthStatus:
        any_failed = False
        any_degraded = False
        for name, info in services.items():
            st = info.get("status", "registered")
            if st == ServiceStatus.FAILED.value:
                any_failed = True
            elif st in (ServiceStatus.DEGRADED.value, ServiceStatus.SHUTDOWN.value):
                any_degraded = True
        for name, chk in checks.items():
            if not chk.get("ok", False):
                # critical check failing → unhealthy
                with self._lock:
                    rec = self._checks.get(name)
                    if rec and rec.critical:
                        any_failed = True
                    else:
                        any_degraded = True
        if any_failed:
            return HealthStatus.UNHEALTHY
        if any_degraded:
            return HealthStatus.DEGRADED
        return HealthStatus.HEALTHY

    def _collect_system_metrics(self) -> Dict[str, Any]:
        metrics: Dict[str, Any] = {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        try:
            import psutil
            vm = psutil.virtual_memory()
            metrics["cpu_pct"] = psutil.cpu_percent(interval=0.1)
            metrics["mem_used_pct"] = vm.percent
            metrics["mem_available_mb"] = round(vm.available / (1024 * 1024), 1)
            disk = psutil.disk_usage("/")
            metrics["disk_used_pct"] = disk.percent
        except Exception:
            pass
        return metrics

    # ── introspection ───────────────────────────────────────────────

    def latest(self) -> Optional[HealthSnapshot]:
        with self._lock:
            return self._last_snapshot

    def history(self, limit: int = 20) -> List[HealthSnapshot]:
        with self._lock:
            return list(self._history[-limit:])

    def status(self) -> Dict[str, Any]:
        snap = self.latest()
        if snap is None:
            snap = self.run_once()
        return snap.to_dict()


# ── singleton ───────────────────────────────────────────────────────

_MONITOR: Optional[HealthMonitor] = None


def get_health_monitor() -> HealthMonitor:
    global _MONITOR
    if _MONITOR is None:
        _MONITOR = HealthMonitor()
    return _MONITOR
