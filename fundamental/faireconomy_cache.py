# fundamental/faireconomy_cache.py  —  Day 92 shared cache
# ============================================================
# FairEconomy JSON endpoint-এর জন্য process-wide singleton cache।
#
# সমস্যা (Day 92 log থেকে):
#   17:51:51  economic_calendar_api  | [FairEconomy] fetch failed: 429
#   17:51:52  news_filter            | [FairEconomy] fetch failed: 429
#
# দুটো module নিজস্ব _fetch_faireconomy() দিয়ে একই endpoint-ে
# একই সেকেন্ডে call করছিল → rate limit দ্বিগুণ হচ্ছিল।
#
# Fix: এই module-ে একটাই cache dict এবং একটাই fetch_faireconomy()
# function আছে। news_filter.py এবং economic_calendar_api.py দুটোই
# এই function import করে ব্যবহার করবে — তাই HTTP request একবারই হবে।
#
# Day 97+ FIXES:
#   #1: _fetching flag prevents cache stampede (5 threads → 5 HTTP requests → 429)
#   #2: Retry-After log now shows ACTUAL sleep time (was misleading)
#   #3: CACHE_TTL 60s → 300s (calendar doesn't change every minute)
# ============================================================

import time
import threading
from datetime import datetime

import pytz
import requests

from utils.logger import get_logger

log = get_logger("faireconomy_cache")

FAIRECONOMY_URL     = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
# Day 97+ FIX #3: 60s → 300s. Economic calendar doesn't change every minute;
# 5 minutes is safe and reduces API calls by 5x.
CACHE_TTL_SECONDS   = 300.0  # 5 minutes

# ── Singleton cache ───────────────────────────────────────────
_cache_lock = threading.Lock()
_cache: dict = {
    "data":       None,   # list[dict] | None
    "fetched_at": 0.0,    # time.monotonic() timestamp
}

# Day 97+ FIX #1: _fetching flag prevents cache stampede.
# Without this, multiple threads hitting cache-miss simultaneously would all
# fire HTTP requests → 429 Too Many Requests.
_fetching = False


def fetch_faireconomy(
    watched_currencies: set,
    high_impact_keywords: list,
) -> list:
    """
    FairEconomy JSON feed থেকে economic events fetch করে।
    একই process-ে যেকোনো module থেকে call হোক — TTL (300s) শেষ না হওয়া
    পর্যন্ত শুধু প্রথম call-ই HTTP request করবে, বাকিরা cache পাবে।

    Day 97+ FIX #1: _fetching flag prevents cache stampede — if one thread
    is already fetching, other threads return stale cache (or []) instead
    of firing duplicate HTTP requests.

    Returns: list of event dicts.
    """
    global _cache, _fetching

    now_mono = time.monotonic()

    # ── Fast path: cache hit ──────────────────────────────────
    with _cache_lock:
        age = now_mono - _cache["fetched_at"]
        if _cache["data"] is not None and age < CACHE_TTL_SECONDS:
            log.debug(f"[FairEconomy] cache hit (age={age:.1f}s) — skipping HTTP request")
            return _cache["data"]

        # Day 97+ FIX #1: cache stampede prevention
        # If another thread is already fetching, DON'T fire another request.
        # Return stale cache if available, else empty list.
        if _fetching:
            if _cache["data"] is not None:
                log.debug("[FairEconomy] cache miss but fetch in progress — returning stale cache")
                return _cache["data"]
            else:
                log.debug("[FairEconomy] cache miss, fetch in progress, no stale cache — returning []")
                return []

        # Claim the fetch — other threads will now see _fetching=True
        _fetching = True

    # ── Cache miss: HTTP fetch (only ONE thread reaches here) ────
    try:
        # Day 97+ FIX #2: retry with backoff, but log the ACTUAL sleep time
        # (was logging server's Retry-After but capping sleep at 30s — misleading)
        raw = None
        last_err = None
        for attempt in range(3):
            try:
                resp = requests.get(FAIRECONOMY_URL, timeout=10)
                if resp.status_code == 429:
                    retry_after_raw = resp.headers.get("Retry-After", "5")
                    try:
                        retry_after = int(retry_after_raw)
                    except ValueError:
                        retry_after = 5
                    # FIX #2: log the ACTUAL sleep time, not the server's value
                    actual_sleep = min(retry_after, 30)
                    log.warning(
                        f"[FairEconomy] 429 Too Many Requests — "
                        f"server says wait {retry_after}s, "
                        f"actual sleep={actual_sleep}s (attempt {attempt+1}/3)"
                    )
                    time.sleep(actual_sleep)
                    last_err = "HTTP 429 rate-limited"
                    continue
                resp.raise_for_status()
                raw = resp.json()
                break
            except requests.exceptions.HTTPError as he:
                if resp.status_code >= 500 and attempt < 2:
                    backoff = 2 ** attempt
                    log.warning(
                        f"[FairEconomy] HTTP {resp.status_code} — "
                        f"sleep={backoff}s (attempt {attempt+1}/3)"
                    )
                    time.sleep(backoff)
                    last_err = f"HTTP {resp.status_code}"
                    continue
                raise
            except requests.exceptions.RequestException as re:
                if attempt < 2:
                    backoff = 2 ** attempt
                    log.warning(
                        f"[FairEconomy] network error: {re} — "
                        f"sleep={backoff}s (attempt {attempt+1}/3)"
                    )
                    time.sleep(backoff)
                    last_err = str(re)
                    continue
                raise

        if raw is None:
            log.warning(f"[FairEconomy] fetch failed after retries: {last_err}")
            with _cache_lock:
                _fetching = False  # release flag
                if _cache["data"] is not None:
                    log.warning("[FairEconomy] using stale cache as fallback")
                    return _cache["data"]
            return []

        events = []
        for item in raw:
            currency = item.get("country", "").upper()
            if currency not in watched_currencies:
                continue

            impact  = item.get("impact", "").lower()
            is_high = impact == "high"
            title   = item.get("title", "")

            if not is_high:
                is_high = any(
                    kw.lower() in title.lower()
                    for kw in high_impact_keywords
                )

            date_str = item.get("date", "")
            try:
                dt = datetime.fromisoformat(date_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=pytz.utc)
                utc_dt = dt.astimezone(pytz.utc)
            except Exception:
                continue

            events.append({
                "title":       title,
                "currency":    currency,
                "high_impact": is_high,
                "time":        utc_dt,
            })

        # ── Update cache + release fetch flag ─────────────────
        with _cache_lock:
            _cache["data"]       = events
            _cache["fetched_at"] = time.monotonic()
            _fetching = False  # Day 97+ FIX #1: release flag

        log.info(f"[FairEconomy] fetched {len(events)} events (cache updated)")
        return events

    except Exception as e:
        log.warning(f"[FairEconomy] fetch failed: {e}")
        with _cache_lock:
            _fetching = False  # Day 97+ FIX #1: release flag on error too
            if _cache["data"] is not None:
                log.warning("[FairEconomy] using stale cache as fallback")
                return _cache["data"]
        return []
