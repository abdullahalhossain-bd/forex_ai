"""
fundamental/fred_data.py — Day 94 FRED API (Federal Reserve Economic Data)
=========================================================================
Pulls macro-economic data directly from the St. Louis Fed's FRED database.
This is the OFFICIAL source for US economic indicators.

Free tier: unlimited requests with free API key (no daily cap).
Get key: https://fredaccount.stlouisfed.org/apikeys

Series we track (configurable via env):
  CPIAUCSL     — Consumer Price Index (US inflation)
  UNRATE       — Unemployment Rate
  DGS10        — 10-Year Treasury Yield
  DGS2         — 2-Year Treasury Yield
  T10Y2Y       — 10Y-2Y Yield Spread (recession indicator)
  FEDFUNDS     — Federal Funds Rate (current interest rate)
  DEXUSEU      — USD/EUR exchange rate (sanity check)
  VIXCLS       — VIX (volatility index)

Usage:
    from fundamental.fred_data import FREDApi
    fred = FREDApi()
    data = fred.get_macro_snapshot()
    # data = {"CPI": {"value":314.4, "date":"2024-12-01"}, "UNRATE": {...}, ...}

    # Or single series:
    cpi = fred.get_series("CPIAUCSL")
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

from utils.logger import get_logger

log = get_logger("fred_api")


# ── Tracked FRED series ──────────────────────────────────────────
# Each entry: series_id -> (label, category, description)
TRACKED_SERIES = {
    "CPIAUCSL":  ("CPI",              "inflation",   "Consumer Price Index (US inflation)"),
    "UNRATE":    ("Unemployment",     "labor",       "US Unemployment Rate (%)"),
    "DGS10":     ("10Y Yield",        "rates",       "10-Year Treasury Yield (%)"),
    "DGS2":      ("2Y Yield",         "rates",       "2-Year Treasury Yield (%)"),
    "T10Y2Y":    ("10Y-2Y Spread",    "rates",       "Yield curve spread (recession indicator)"),
    "FEDFUNDS":  ("Fed Funds Rate",   "rates",       "Federal Funds Rate (%)"),
    "DEXUSEU":   ("USD/EUR",          "fx",          "USD to EUR exchange rate"),
    "VIXCLS":    ("VIX",              "volatility",  "CBOE Volatility Index"),
}


class FREDApi:
    """FRED API client for macro-economic data."""

    BASE_URL = "https://api.stlouisfed.org/fred"

    def __init__(self):
        self._api_key = os.getenv("FRED_API_KEY", "").strip()

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    # ─────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────

    def get_macro_snapshot(self) -> Dict[str, Any]:
        """Fetch latest value of all tracked series in one call.

        Returns:
            {
              "series": {
                "CPI":          {"value": 314.4, "date": "2024-12-01", "change_pct": 0.3},
                "Unemployment": {"value": 4.1,   "date": "2024-12-01", "change_pct": 0.0},
                ...
              },
              "yield_curve":    "inverted" | "normal" | "flat" | "unknown",
              "inflation_trend":"rising" | "falling" | "stable",
              "rate_environment":"hawkish" | "dovish" | "neutral",
              "fetched_at":     ISO timestamp,
              "source":         "fred_live" | "fred_partial" | "none",
            }
        """
        if not self.available:
            return self._empty_result("FRED_API_KEY not set")

        series_data = {}
        success_count = 0
        for series_id, (label, category, desc) in TRACKED_SERIES.items():
            data = self.get_series(series_id)
            if data:
                series_data[label] = data
                success_count += 1

        if success_count == 0:
            return self._empty_result("All FRED series failed")

        # Compute derived indicators
        yield_curve = self._analyze_yield_curve(series_data)
        inflation_trend = self._analyze_inflation(series_data)
        rate_env = self._analyze_rate_environment(series_data, inflation_trend)

        result = {
            "series":           series_data,
            "yield_curve":      yield_curve,
            "inflation_trend":  inflation_trend,
            "rate_environment": rate_env,
            "fetched_at":       datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source":           "fred_live" if success_count == len(TRACKED_SERIES) else "fred_partial",
        }
        log.info(
            f"[FRED] {success_count}/{len(TRACKED_SERIES)} series | "
            f"yield_curve={yield_curve} | inflation={inflation_trend} | "
            f"rates={rate_env}"
        )
        return result

    def get_series(self, series_id: str) -> Optional[Dict[str, Any]]:
        """Fetch latest value of a single FRED series.

        Returns: {"value": float, "date": "YYYY-MM-DD", "change_pct": float}
                 or None on failure.
        """
        if not self.available:
            return None
        try:
            url = f"{self.BASE_URL}/series/observations"
            params = {
                "series_id":         series_id,
                "api_key":           self._api_key,
                "file_type":         "json",
                "sort_order":        "desc",
                "limit":             2,  # latest + previous for change calc
            }
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.debug(f"[FRED] {series_id} failed: {e}")
            return None

        observations = data.get("observations", [])
        if not observations:
            return None

        latest = observations[0]
        value_str = latest.get("value", ".")
        if value_str == ".":
            return None  # FRED uses "." for missing data

        try:
            value = float(value_str)
        except ValueError:
            return None

        date = latest.get("date", "")
        change_pct = 0.0
        if len(observations) > 1:
            try:
                prev_value = float(observations[1].get("value", "."))
                if prev_value != 0:
                    change_pct = round((value - prev_value) / prev_value * 100, 3)
            except (ValueError, ZeroDivisionError):
                pass

        return {
            "value":      value,
            "date":       date,
            "change_pct": change_pct,
        }

    # ─────────────────────────────────────────────────────────
    # Derived analysis
    # ─────────────────────────────────────────────────────────

    @staticmethod
    def _analyze_yield_curve(series: Dict) -> str:
        """Inverted yield curve (2Y > 10Y) is a recession signal."""
        y10 = series.get("10Y Yield", {}).get("value")
        y2  = series.get("2Y Yield", {}).get("value")
        if y10 is None or y2 is None:
            return "unknown"
        spread = y10 - y2
        if spread < -0.2:
            return "inverted"   # recession warning
        if spread > 0.5:
            return "normal"
        return "flat"

    @staticmethod
    def _analyze_inflation(series: Dict) -> str:
        """CPI trend — rising/falling/stable."""
        cpi = series.get("CPI", {})
        change = cpi.get("change_pct", 0)
        if change > 0.5:
            return "rising"
        if change < -0.3:
            return "falling"
        return "stable"

    @staticmethod
    def _analyze_rate_environment(series: Dict, inflation_trend: str) -> str:
        """Hawkish (raising rates) vs dovish (cutting rates)."""
        fed_rate = series.get("Fed Funds Rate", {}).get("value")
        if fed_rate is None:
            return "neutral"
        # Simplified: high rate + rising inflation = hawkish
        # Low rate + falling inflation = dovish
        if fed_rate > 4.0 and inflation_trend == "rising":
            return "hawkish"
        if fed_rate < 2.0 or inflation_trend == "falling":
            return "dovish"
        return "neutral"

    # ─────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────

    @staticmethod
    def _empty_result(reason: str) -> Dict[str, Any]:
        return {
            "series":           {},
            "yield_curve":      "unknown",
            "inflation_trend":  "stable",
            "rate_environment": "neutral",
            "fetched_at":       datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source":           "none",
            "reason":           reason,
        }

    def get_ai_context(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Compact context for MasterAnalyst."""
        s = result.get("series", {})
        return {
            "fred_source":          result.get("source", "none"),
            "fred_yield_curve":     result.get("yield_curve", "unknown"),
            "fred_inflation_trend": result.get("inflation_trend", "stable"),
            "fred_rate_env":        result.get("rate_environment", "neutral"),
            "fred_cpi":             s.get("CPI", {}).get("value"),
            "fred_unemployment":    s.get("Unemployment", {}).get("value"),
            "fred_fed_rate":        s.get("Fed Funds Rate", {}).get("value"),
            "fred_10y_yield":       s.get("10Y Yield", {}).get("value"),
            "fred_vix":             s.get("VIX", {}).get("value"),
        }

    def print_summary(self, result: Dict[str, Any]) -> None:
        bar = "═" * 50
        log.info(bar)
        log.info("  🏛️  FRED MACRO DATA  (Day 94)")
        log.info(bar)
        log.info(f"  Source         : {result.get('source','?')}")
        log.info(f"  Yield curve    : {result.get('yield_curve','?')}")
        log.info(f"  Inflation      : {result.get('inflation_trend','?')}")
        log.info(f"  Rate env       : {result.get('rate_environment','?')}")
        for label, data in result.get("series", {}).items():
            log.info(f"  {label:<16}: {data['value']}  ({data['date']}, {data['change_pct']:+.2f}%)")
        log.info(bar)


# ── Singleton ────────────────────────────────────────────────────

_INSTANCE: Optional[FREDApi] = None


def get_fred_api() -> FREDApi:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = FREDApi()
    return _INSTANCE
