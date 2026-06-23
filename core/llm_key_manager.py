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
import threading
import time
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
            # Disable for only 30 seconds on rate limit (was 60 — too long)
            self.rate_limited_until = time.time() + 30
            log.warning(f"[LLM Keys] {self.provider} key #{self.index + 1} rate-limited, disabled for 30s")
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
