"""
core/llm_key_manager.py — Multi-Key LLM Rotation Manager (Day 72+)
=====================================================================

Manages multiple API keys per provider (Groq, Gemini) with automatic
failover. If one key hits a rate limit or fails, it automatically
switches to the next available key.

Features:
  * Round-robin key rotation (distributes load across keys)
  * Automatic failover (key 1 fails → try key 2 → try key 3)
  * Rate limit tracking (temporarily disables keys that hit 429)
  * Health stats per key (success count, fail count, last error)
  * Supports unlimited keys per provider

Usage:
    manager = get_llm_key_manager()
    groq_client = manager.get_groq_client()   # returns a working Groq client
    gemini_client = manager.get_gemini_client()  # returns a working Gemini client

Environment variables (in .env):
    GROQ_API_KEY_1=gsk_xxx
    GROQ_API_KEY_2=gsk_yyy
    GROQ_API_KEY_3=gsk_zzz
    GROQ_API_KEY=gsk_xxx        # backwards compat (treated as key 1)

    GEMINI_API_KEY_1=AIzaXxx
    GEMINI_API_KEY_2=AIzaYyy
    GEMINI_API_KEY=AIzaXxx      # backwards compat
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

# Load .env from multiple possible locations
from pathlib import Path as _Path
for _env_path in [
    _Path(__file__).resolve().parent.parent / ".env",  # project root
    _Path.cwd() / ".env",                                # current working dir
    _Path.home() / ".env",                               # home dir
]:
    if _env_path.exists():
        load_dotenv(str(_env_path))
        break
log = logging.getLogger("llm_key_manager")


def classify_llm_error(error: Exception) -> dict:
    """Classify LLM API failures without false positives (e.g. 'rate' in 'generate')."""
    error_str = str(error)
    err_lower = error_str.lower()
    return {
        "error_str": error_str,
        "error_type": type(error).__name__,
        "rate_limited": (
            "429" in error_str
            or "too many requests" in err_lower
            or "rate limit" in err_lower
            or "rate_limit" in err_lower
        ),
        "auth_failed": (
            "401" in error_str
            or "403" in error_str
            or "unauthorized" in err_lower
            or "invalid api key" in err_lower
            or "invalid x-api-key" in err_lower
        ),
    }


def log_llm_call_failure(
    logger: logging.Logger,
    provider: str,
    model: str,
    attempt: int,
    max_retries: int,
    error: Exception,
) -> dict:
    """Log full LLM failure details for diagnosis."""
    info = classify_llm_error(error)
    logger.error(
        "[LLM] %s failed attempt %s/%s | model=%s | type=%s | "
        "rate_limited=%s | auth_failed=%s | error=%s",
        provider,
        attempt + 1,
        max_retries,
        model,
        info["error_type"],
        info["rate_limited"],
        info["auth_failed"],
        info["error_str"][:800],
        exc_info=True,
    )
    return info


# ── Groq 429 retry-after parser ────────────────────────────────────
#
# Groq's TPD (tokens-per-day) rate-limit response looks like:
#   "Rate limit reached for model `llama-3.3-70b-versatile` ...
#    Please try again in 10m1.344s. Need more tokens? ..."
#
# The previous code hardcoded a 30-second cooldown when rate_limited=True,
# which is wildly wrong: the actual cooldown can be minutes to hours.
# This parser extracts the real wait time so the KeyHealth object
# disables the key for the right duration.

_GROQ_RETRY_RE_MMSS = re.compile(r"(\d+)m\s*([\d.]+)s")
_GROQ_RETRY_RE_SS   = re.compile(r"([\d.]+)\s*s")
_GROQ_RETRY_RE_MM   = re.compile(r"(\d+)\s*m(?:in)?(?:ute)?s?", re.IGNORECASE)
_GROQ_RETRY_RE_HDR  = re.compile(r"retry[-_ ]?after['\"\s:=]+(\d+)", re.IGNORECASE)

# Hard caps so a single malformed error message can't lock a key for an hour
MIN_RETRY_COOLDOWN = 60       # seconds — even "1s" gets bumped to 60s
MAX_RETRY_COOLDOWN = 60 * 30  # 30 min cap — TPD resets are rarely longer than this
DEFAULT_RETRY_COOLDOWN = 300  # 5 min fallback if parsing fails


def parse_groq_retry_after(error_str: str) -> int:
    """Parse 'Please try again in Xm Y.Ys' from a Groq 429 response.

    Returns the cooldown in seconds (clamped to [60, 1800]) plus a +5s
    safety margin. Falls back to DEFAULT_RETRY_COOLDOWN (300s) if no
    parseable duration is found.
    """
    if not error_str:
        return DEFAULT_RETRY_COOLDOWN
    s = str(error_str)

    # Format: "10m1.344s"
    m = _GROQ_RETRY_RE_MMSS.search(s)
    if m:
        total = int(m.group(1)) * 60 + float(m.group(2))
        return max(MIN_RETRY_COOLDOWN, min(MAX_RETRY_COOLDOWN, int(total) + 5))

    # Format: "45s" or "1.344s"
    m = _GROQ_RETRY_RE_SS.search(s)
    if m:
        total = float(m.group(1))
        return max(MIN_RETRY_COOLDOWN, min(MAX_RETRY_COOLDOWN, int(total) + 5))

    # Format: "10m" or "10 minutes"
    m = _GROQ_RETRY_RE_MM.search(s)
    if m:
        total = int(m.group(1)) * 60
        return max(MIN_RETRY_COOLDOWN, min(MAX_RETRY_COOLDOWN, total + 5))

    # HTTP-style "Retry-After: 120"
    m = _GROQ_RETRY_RE_HDR.search(s)
    if m:
        total = int(m.group(1))
        return max(MIN_RETRY_COOLDOWN, min(MAX_RETRY_COOLDOWN, total + 5))

    return DEFAULT_RETRY_COOLDOWN


# ── Key health tracking ─────────────────────────────────────────────

@dataclass
class KeyHealth:
    """Tracks health of one API key."""
    key: str
    provider: str             # groq / gemini
    index: int                # 0-based index
    success_count: int = 0
    fail_count: int = 0
    last_error: str = ""
    last_success: float = 0.0
    rate_limited_until: float = 0.0  # timestamp until which key is disabled
    is_active: bool = True

    @property
    def is_available(self) -> bool:
        """Key is available if active AND not rate-limited."""
        if not self.is_active:
            return False
        if self.rate_limited_until > time.time():
            return False
        return True

    def mark_success(self) -> None:
        self.success_count += 1
        self.last_success = time.time()
        self.rate_limited_until = 0.0  # clear any rate limit

    def mark_failure(self, error: str = "", rate_limited: bool = False) -> None:
        self.fail_count += 1
        self.last_error = error[:200]

        # ── Network errors should NOT disable the key ───────────────
        # DNS failures (getaddrinfo), connection refused, timeouts etc.
        # are NOT a key problem — they're a local network problem.
        # Disabling the key on these just makes a temporary outage
        # permanent for 2 minutes.  Detect + skip the disable logic.
        err_lower = error.lower()
        is_network_error = any(s in err_lower for s in (
            "getaddrinfo", "connection", "timeout", "timed out",
            "network", "dns", "unreachable", "refused", "reset",
            "11001", "etimedout", "ehostunreach", "enetunreach",
            "ssl", "certificate", "proxyerror",
        ))

        if rate_limited:
            # Parse "Please try again in 10m1.344s" from Groq's 429 body and
            # use the real cooldown.  Falls back to DEFAULT_RETRY_COOLDOWN
            # (300s) if parsing fails.  Clamped to [60, 1800] seconds.
            cooldown = parse_groq_retry_after(error)
            self.rate_limited_until = time.time() + cooldown
            log.warning(
                f"[LLM Keys] {self.provider} key #{self.index + 1} "
                f"rate-limited, disabled for {cooldown}s"
            )
        elif "401" in error or "unauthorized" in err_lower:
            # Invalid key — disable permanently
            self.is_active = False
            log.error(f"[LLM Keys] {self.provider} key #{self.index + 1} unauthorized — permanently disabled")
        elif is_network_error:
            # Network error — DON'T disable the key, just log it.
            # The next call will retry.  This prevents a 2-minute
            # disable spiral during temporary DNS / proxy outages.
            log.debug(
                f"[LLM Keys] {self.provider} key #{self.index + 1} network error "
                f"(NOT disabling — will retry): {error[:80]}"
            )
        elif self.fail_count > 20:
            # Too many failures — disable for 2 minutes (was 5 — too long)
            self.rate_limited_until = time.time() + 120
            log.warning(f"[LLM Keys] {self.provider} key #{self.index + 1} too many failures ({self.fail_count}), disabled for 2min")
        elif self.fail_count > 5:
            # Some failures — short cooldown
            self.rate_limited_until = time.time() + 10
            log.warning(f"[LLM Keys] {self.provider} key #{self.index + 1} {self.fail_count} failures, 10s cooldown")
        # Otherwise: single failure, no disable — try again next time

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "index": self.index,
            "active": self.is_active,
            "available": self.is_available,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "last_error": self.last_error[:100],
            "rate_limited": self.rate_limited_until > time.time(),
        }


class LLMKeyManager:
    """Multi-key rotation manager for Groq + Gemini."""

    def __init__(self):
        self._lock = threading.RLock()
        self._groq_keys: List[KeyHealth] = []
        self._gemini_keys: List[KeyHealth] = []
        self._groq_index = 0  # round-robin counter
        self._gemini_index = 0
        self._load_keys()

    def _load_keys(self) -> None:
        """Load all keys from environment variables."""
        # ── Groq keys ──
        groq_keys = []
        # Try GROQ_API_KEY_1, GROQ_API_KEY_2, ... then GROQ_API_KEY as fallback
        for i in range(1, 10):
            key = os.getenv(f"GROQ_API_KEY_{i}", "")
            if key and key.strip():
                groq_keys.append(key.strip())
        # Backwards compat: GROQ_API_KEY (if not already in list)
        legacy = os.getenv("GROQ_API_KEY", "")
        if legacy and legacy.strip() and legacy.strip() not in groq_keys:
            groq_keys.append(legacy.strip())

        for i, key in enumerate(groq_keys):
            self._groq_keys.append(KeyHealth(key=key, provider="groq", index=i))
        log.info(f"[LLM Keys] Loaded {len(self._groq_keys)} Groq key(s)")

        # ── Gemini keys ──
        gemini_keys = []
        for i in range(1, 10):
            key = os.getenv(f"GEMINI_API_KEY_{i}", "")
            if key and key.strip():
                gemini_keys.append(key.strip())
        legacy = os.getenv("GEMINI_API_KEY", "")
        if legacy and legacy.strip() and legacy.strip() not in gemini_keys:
            gemini_keys.append(legacy.strip())

        for i, key in enumerate(gemini_keys):
            self._gemini_keys.append(KeyHealth(key=key, provider="gemini", index=i))
        log.info(f"[LLM Keys] Loaded {len(self._gemini_keys)} Gemini key(s)")

    # ── Groq ──────────────────────────────────────────────────────

    def get_groq_client(self) -> Optional[Any]:
        """Get a working Groq client. Rotates through available keys."""
        with self._lock:
            available = [k for k in self._groq_keys if k.is_available]
            if not available:
                log.error("[LLM Keys] No available Groq keys!")
                return None

            # Round-robin: pick the next available key
            key = available[self._groq_index % len(available)]
            self._groq_index += 1

        try:
            from groq import Groq
            client = Groq(api_key=key.key)
            log.debug(f"[LLM Keys] Using Groq key #{key.index + 1}")
            return client
        except ImportError:
            log.warning("[LLM Keys] groq package not installed")
            return None
        except Exception as e:
            # Constructor failure is NOT the same as API call failure.
            # Don't disable the key for constructor errors — just log and return None.
            # The key will be retried on the next call.
            log.debug(f"[LLM Keys] Groq constructor failed (non-fatal): {e}")
            return None

    def get_groq_key_info(self) -> Optional[KeyHealth]:
        """Get the KeyHealth object for the next available Groq key."""
        with self._lock:
            available = [k for k in self._groq_keys if k.is_available]
            if not available:
                return None
            return available[self._groq_index % len(available)]

    def mark_groq_success(self) -> None:
        """Mark the current Groq key as successful."""
        with self._lock:
            available = [k for k in self._groq_keys if k.is_available]
            if available:
                available[(self._groq_index - 1) % len(available)].mark_success()

    def mark_groq_failure(self, error: str = "", rate_limited: bool = False) -> None:
        """Mark the current Groq key as failed."""
        with self._lock:
            available = [k for k in self._groq_keys if k.is_available]
            if available:
                available[(self._groq_index - 1) % len(available)].mark_failure(error, rate_limited)

    # ── Gemini ────────────────────────────────────────────────────

    def get_gemini_client(self) -> Optional[Any]:
        """Get a working Gemini client. Rotates through available keys."""
        with self._lock:
            available = [k for k in self._gemini_keys if k.is_available]
            if not available:
                log.error("[LLM Keys] No available Gemini keys!")
                return None

            key = available[self._gemini_index % len(available)]
            self._gemini_index += 1

        try:
            from google import genai as google_genai
            client = google_genai.Client(api_key=key.key)
            log.debug(f"[LLM Keys] Using Gemini key #{key.index + 1}")
            return client
        except ImportError:
            log.warning("[LLM Keys] google-genai package not installed")
            return None
        except Exception as e:
            # Constructor failure — don't disable key, just return None
            log.debug(f"[LLM Keys] Gemini constructor failed (non-fatal): {e}")
            return None

    def get_gemini_key_info(self) -> Optional[KeyHealth]:
        with self._lock:
            available = [k for k in self._gemini_keys if k.is_available]
            if not available:
                return None
            return available[self._gemini_index % len(available)]

    def mark_gemini_success(self) -> None:
        with self._lock:
            available = [k for k in self._gemini_keys if k.is_available]
            if available:
                available[(self._gemini_index - 1) % len(available)].mark_success()

    def mark_gemini_failure(self, error: str = "", rate_limited: bool = False) -> None:
        with self._lock:
            available = [k for k in self._gemini_keys if k.is_available]
            if available:
                available[(self._gemini_index - 1) % len(available)].mark_failure(error, rate_limited)

    # ── Per-cycle LLM call throttle (Day 81+) ───────────────────
    # Prevents the Groq rate-limit storm by capping total LLM calls
    # per "cycle" (1 cycle = 1 symbol processed by 1 AITrader).
    # The cycle boundary is marked by reset_cycle_calls() which
    # trader.py calls at the top of each run_cycle().

    _cycle_call_count: int = 0
    _cycle_call_lock: threading.Lock = threading.Lock()
    _last_call_ts: float = 0.0

    # Day 81+ hotfix: GLOBAL rolling-window cap.  Per-cycle cap alone
    # is not enough — with 6 pairs × 5 calls/cycle = 30 calls in 2
    # minutes, all 6 Groq keys hit TPD limit.  This global cap limits
    # total calls across ALL cycles in a rolling 60-second window.
    # Default 12 calls/min (≈ 2 cycles × 6 calls each).
    _global_call_timestamps: deque = deque()
    _global_call_lock: threading.Lock = threading.Lock()

    def reset_cycle_calls(self) -> None:
        """Call at the start of each symbol cycle to reset the per-cycle
        LLM call counter.  trader.py calls this in run_cycle().

        Note: the GLOBAL rolling-window cap is NOT reset here — it
        persists across cycles to prevent the cross-cycle Groq storm.
        """
        with self._cycle_call_lock:
            self._cycle_call_count = 0

    def check_cycle_throttle(self) -> tuple[bool, str]:
        """Check if the current cycle has exceeded MAX_LLM_CALLS_PER_CYCLE.

        Returns (allowed, reason).  When allowed=False, the caller should
        skip the LLM call and use a fallback (e.g. rule engine signal).
        Also enforces LLM_CALL_INTERVAL_SEC between calls to the same
        provider (Groq free-tier rate-limit mitigation).

        Day 81+ hotfix: also enforces a GLOBAL rolling-window cap of
        MAX_LLM_CALLS_PER_MIN (default 12) calls per 60 seconds across
        all cycles.  Without this, 6 pairs × 5 calls/cycle = 30 calls
        in 2 minutes drains all 6 Groq keys' TPD quota.
        """
        try:
            from config import (
                MAX_LLM_CALLS_PER_CYCLE,
                LLM_CALL_INTERVAL_SEC,
                MAX_LLM_CALLS_PER_MIN,
            )
        except Exception:
            MAX_LLM_CALLS_PER_CYCLE = 8
            LLM_CALL_INTERVAL_SEC = 1.0
            MAX_LLM_CALLS_PER_MIN = 12

        # ── Global rolling-window cap (cross-cycle) ──
        now = time.time()
        with self._global_call_lock:
            # Evict timestamps older than 60 seconds
            cutoff = now - 60.0
            while self._global_call_timestamps and self._global_call_timestamps[0] < cutoff:
                self._global_call_timestamps.popleft()
            if len(self._global_call_timestamps) >= MAX_LLM_CALLS_PER_MIN:
                # Calculate sleep time until oldest timestamp exits window
                oldest = self._global_call_timestamps[0]
                wait_for = max(0.0, oldest + 60.0 - now)
                return False, (
                    f"global cap reached ({len(self._global_call_timestamps)}/"
                    f"{MAX_LLM_CALLS_PER_MIN} in last 60s) — retry in {wait_for:.0f}s"
                )

        with self._cycle_call_lock:
            # Per-cycle count cap
            if self._cycle_call_count >= MAX_LLM_CALLS_PER_CYCLE:
                return False, (
                    f"cycle cap reached ({self._cycle_call_count}/"
                    f"{MAX_LLM_CALLS_PER_CYCLE}) — skip LLM, use fallback"
                )
            # Per-call interval enforcement
            now = time.time()
            elapsed = now - self._last_call_ts
            if elapsed < LLM_CALL_INTERVAL_SEC:
                sleep_for = LLM_CALL_INTERVAL_SEC - elapsed
                # Release lock during sleep so other threads can proceed
                self._cycle_call_lock.release()
                try:
                    time.sleep(sleep_for)
                finally:
                    self._cycle_call_lock.acquire()
            self._cycle_call_count += 1
            self._last_call_ts = time.time()

        # Record this call in the global window (after cycle lock released)
        with self._global_call_lock:
            self._global_call_timestamps.append(time.time())

        return True, f"call {self._cycle_call_count}/{MAX_LLM_CALLS_PER_CYCLE} (global {len(self._global_call_timestamps)}/{MAX_LLM_CALLS_PER_MIN})"

    # ── Status ────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Return status of all keys for dashboard."""
        with self._lock:
            return {
                "groq": {
                    "total": len(self._groq_keys),
                    "available": sum(1 for k in self._groq_keys if k.is_available),
                    "keys": [k.to_dict() for k in self._groq_keys],
                },
                "gemini": {
                    "total": len(self._gemini_keys),
                    "available": sum(1 for k in self._gemini_keys if k.is_available),
                    "keys": [k.to_dict() for k in self._gemini_keys],
                },
            }

    def reset_keys(self, provider: str = "all") -> None:
        """Clear fail counters + rate-limit cooldowns so all keys become
        available again.  Use this when a network outage tripped the
        disable thresholds and you want immediate recovery.

        Args:
            provider: "groq", "gemini", or "all" (default).
        """
        with self._lock:
            targets = []
            if provider in ("all", "groq"):
                targets.extend(self._groq_keys)
            if provider in ("all", "gemini"):
                targets.extend(self._gemini_keys)
            cleared = 0
            for k in targets:
                if not k.is_active:
                    continue
                k.fail_count = 0
                k.rate_limited_until = 0.0
                k.last_error = ""
                cleared += 1
            log.info(f"[LLM Keys] Reset {cleared} {provider} key(s) — all cooldowns cleared")

    @property
    def has_any_groq(self) -> bool:
        return any(k.is_available for k in self._groq_keys)

    @property
    def has_any_gemini(self) -> bool:
        return any(k.is_available for k in self._gemini_keys)

    @property
    def has_any_llm(self) -> bool:
        return self.has_any_groq or self.has_any_gemini

    # ── Global exhaustion detection ──────────────────────────────
    # When all keys for a provider are rate-limited simultaneously,
    # the previous code would return None from get_groq_client() and
    # callers would bail immediately — but the next call cycle (10s
    # later via the supervisor) would call get_groq_client() again,
    # and again, and again, hammering the still-rate-limited keys
    # and producing the 429 storm seen in the production logs.
    #
    # The fix: when all keys are exhausted, callers should *wait*
    # for the soonest-recovering key instead of looping fast.

    @property
    def all_groq_rate_limited(self) -> bool:
        """True if there is at least one Groq key AND all are unavailable."""
        with self._lock:
            return bool(self._groq_keys) and not any(
                k.is_available for k in self._groq_keys
            )

    @property
    def all_gemini_rate_limited(self) -> bool:
        with self._lock:
            return bool(self._gemini_keys) and not any(
                k.is_available for k in self._gemini_keys
            )

    def wait_for_any_groq(
        self,
        max_wait: float = 300.0,
        poll_interval: float = 10.0,
    ) -> bool:
        """Block until at least one Groq key becomes available, or
        ``max_wait`` seconds elapse.

        Returns True if a key is now available, False on timeout.  Use
        this from callers when ``get_groq_client()`` returns None to
        avoid hammering the API in a tight retry loop.

        Logs an ETA every poll cycle so the operator can see progress.
        """
        deadline = time.time() + max_wait
        while True:
            with self._lock:
                if any(k.is_available for k in self._groq_keys):
                    return True
                # ETA = soonest rate_limited_until among Groq keys
                soonest = min(
                    (k.rate_limited_until for k in self._groq_keys
                     if k.rate_limited_until > time.time()),
                    default=0.0,
                )
            remaining = deadline - time.time()
            if remaining <= 0:
                return self.has_any_groq
            eta = max(0.0, soonest - time.time())
            log.warning(
                f"[LLM Keys] All Groq keys exhausted — "
                f"soonest recovers in {eta:.0f}s, "
                f"max_wait remaining {remaining:.0f}s"
            )
            # Sleep the smaller of poll_interval / eta / remaining
            sleep_for = min(poll_interval, max(2.0, eta), remaining)
            time.sleep(sleep_for)
        # unreachable
        return self.has_any_groq


# ── Singleton ───────────────────────────────────────────────────────

_MANAGER: Optional[LLMKeyManager] = None
_MANAGER_LOCK = threading.Lock()


def get_llm_key_manager() -> LLMKeyManager:
    global _MANAGER
    if _MANAGER is None:
        with _MANAGER_LOCK:
            if _MANAGER is None:
                _MANAGER = LLMKeyManager()
    return _MANAGER
