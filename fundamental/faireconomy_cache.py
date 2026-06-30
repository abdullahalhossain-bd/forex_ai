# fundamental/faireconomy_cache.py  —  Day 92 shared cache
# ============================================================
# FairEconomy JSON endpoint-এর জন্য process-wide singleton cache।
#
# সমস্যা (Day 92 log থেকে):
#   17:51:51  economic_calendar_api  | [FairEconomy] fetch failed: 429
#   17:51:52  news_filter            | [FairEconomy] fetch failed: 429
#
# দুটো module নিজস্ব _fetch_faireconomy() দিয়ে একই endpoint-এ
# একই সেকেন্ডে call করছিল → rate limit দ্বিগুণ হচ্ছিল।
#
# Fix: এই module-এ একটাই cache dict এবং একটাই fetch_faireconomy()
# function আছে। news_filter.py এবং economic_calendar_api.py দুটোই
# এই function import করে ব্যবহার করবে — তাই HTTP request একবারই হবে।
#
# Usage (উভয় module-এ):
#   from fundamental.faireconomy_cache import fetch_faireconomy
#   events = fetch_faireconomy(watched_currencies, high_impact_keywords)
# ============================================================

import time
import threading
from datetime import datetime

import pytz
import requests

from utils.logger import get_logger

log = get_logger("faireconomy_cache")

FAIRECONOMY_URL     = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CACHE_TTL_SECONDS   = 60.0   # একই cycle-এ (60s) দ্বিতীয় call → cache hit

# ── Singleton cache ───────────────────────────────────────────
_cache_lock = threading.Lock()
_cache: dict = {
    "data":       None,   # list[dict] | None
    "fetched_at": 0.0,    # time.monotonic() timestamp
}


def fetch_faireconomy(
    watched_currencies: set,
    high_impact_keywords: list,
) -> list:
    """
    FairEconomy JSON feed থেকে economic events fetch করে।
    একই process-এ যেকোনো module থেকে call হোক — TTL (60s) শেষ না হওয়া
    পর্যন্ত শুধু প্রথম call-ই HTTP request করবে, বাকিরা cache পাবে।

    Returns: list of event dicts:
        {
            "title":       str,
            "currency":    str,   # e.g. "USD"
            "high_impact": bool,
            "time":        datetime (UTC, timezone-aware),
        }
    """
    global _cache

    now_mono = time.monotonic()

    # ── Fast path: cache hit ──────────────────────────────────
    with _cache_lock:
        age = now_mono - _cache["fetched_at"]
        if _cache["data"] is not None and age < CACHE_TTL_SECONDS:
            log.debug(f"[FairEconomy] cache hit (age={age:.1f}s) — skipping HTTP request")
            return _cache["data"]

    # ── Cache miss: HTTP fetch ────────────────────────────────
    try:
        resp = requests.get(FAIRECONOMY_URL, timeout=10)
        resp.raise_for_status()
        raw = resp.json()

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

        # ── Update cache ──────────────────────────────────────
        with _cache_lock:
            _cache["data"]       = events
            _cache["fetched_at"] = time.monotonic()

        log.info(f"[FairEconomy] fetched {len(events)} events (cache updated)")
        return events

    except Exception as e:
        log.warning(f"[FairEconomy] fetch failed: {e}")

        # Stale cache fallback — expired হলেও না থাকার চেয়ে ভালো
        with _cache_lock:
            if _cache["data"] is not None:
                log.warning("[FairEconomy] using stale cache as fallback")
                return _cache["data"]

        return []