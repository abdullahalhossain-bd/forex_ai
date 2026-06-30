"""
fundamental/economic_surprise.py — Day 96 Economic Surprise Index
=================================================================
Compares actual economic data vs market forecast to detect "surprises"
that move the market. A surprise is when actual differs significantly
from forecast — markets react strongly to surprises.

Example:
  USD CPI
  Forecast: 3.2%
  Actual:   3.8%
  Surprise: +0.6% (higher than expected = USD bullish shock)

Sources:
  1. FRED API (we already have this — actual data)
  2. Economic calendar (forecast data from Trading Economics / FF)
  3. Manual forecast estimates (last resort)

Output:
    {
      "surprise_score":     +45,       # -100 to +100, positive = USD bullish
      "surprise_direction": "USD_BULLISH",
      "events":             [{"title","forecast","actual","surprise"}],
      "confidence":         70,
    }

Usage:
    from fundamental.economic_surprise import EconomicSurpriseEngine
    engine = EconomicSurpriseEngine()
    result = engine.analyze("USD")
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

log = get_logger("economic_surprise")


class EconomicSurpriseEngine:
    """Economic surprise index — actual vs forecast comparison."""

    # Keywords that indicate USD-bullish when actual > forecast
    USD_BULLISH_IF_HIGH = [
        "cpi", "inflation", "interest rate", "fed funds",
        "non-farm", "nfp", "gdp", "retail sales", "pmi",
    ]

    # Keywords that indicate USD-bearish when actual > forecast
    USD_BEARISH_IF_HIGH = [
        "unemployment", "jobless claims", "trade deficit",
    ]

    def __init__(self):
        pass

    def analyze(self, currency: str = "USD") -> Dict[str, Any]:
        """Compute economic surprise index for a currency.

        Args:
            currency: e.g. "USD", "EUR"

        Returns: dict with surprise_score, surprise_direction, events, etc.
        """
        # Get calendar events with actual + forecast
        events = self._get_events_with_actuals(currency)

        if not events:
            return self._fallback_result(currency, "no events with actual+forecast")

        # Compute surprise for each event
        surprises = []
        total_score = 0

        for ev in events:
            forecast = self._parse_numeric(ev.get("forecast", ""))
            actual = self._parse_numeric(ev.get("actual", ""))

            if forecast is None or actual is None:
                continue

            if forecast == 0:
                continue

            surprise_pct = ((actual - forecast) / abs(forecast)) * 100
            title_lower = ev.get("title", "").lower()

            # Determine direction
            is_bullish_if_high = any(kw in title_lower for kw in self.USD_BULLISH_IF_HIGH)
            is_bearish_if_high = any(kw in title_lower for kw in self.USD_BEARISH_IF_HIGH)

            if is_bearish_if_high:
                # Higher than expected = bearish for currency
                score = -surprise_pct
            elif is_bullish_if_high:
                # Higher than expected = bullish for currency
                score = surprise_pct
            else:
                score = surprise_pct  # default: higher = bullish

            # Clamp to ±100
            score = max(-100, min(100, score))

            surprises.append({
                "title":     ev.get("title", ""),
                "forecast":  ev.get("forecast", ""),
                "actual":    ev.get("actual", ""),
                "surprise_pct": round(surprise_pct, 2),
                "score":     round(score, 1),
            })
            total_score += score

        if not surprises:
            return self._fallback_result(currency, "no events with parseable numbers")

        # Average score
        avg_score = total_score / len(surprises)
        avg_score = max(-100, min(100, avg_score))

        # Direction
        if avg_score > 20:
            direction = f"{currency}_BULLISH"
        elif avg_score < -20:
            direction = f"{currency}_BEARISH"
        else:
            direction = "NEUTRAL"

        confidence = min(100, abs(avg_score) + len(surprises) * 10)

        result = {
            "source":             "economic_surprise",
            "currency":           currency,
            "surprise_score":     round(avg_score, 1),
            "surprise_direction": direction,
            "events":             surprises,
            "event_count":        len(surprises),
            "confidence":         int(confidence),
            "fetched_at":         datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        log.info(
            f"[EconSurprise] {currency} | score={avg_score:+.1f} | "
            f"dir={direction} | events={len(surprises)} | conf={confidence:.0f}%"
        )
        return result

    def _get_events_with_actuals(self, currency: str) -> List[Dict]:
        """Get economic events that have both forecast + actual values."""
        events = []
        try:
            from fundamental.economic_calendar_api import EconomicCalendarAPI
            cal = EconomicCalendarAPI()
            result = cal.get_calendar(currencies=[currency], hours_ahead=168)  # 7 days
            for ev in result.get("events", []):
                if ev.get("forecast") and ev.get("actual"):
                    events.append(ev)
        except Exception as e:
            log.debug(f"[EconSurprise] calendar fetch failed: {e}")
        return events

    @staticmethod
    def _parse_numeric(value: str) -> Optional[float]:
        """Parse a string like '3.2%' or '215000' or '0.5' to float."""
        if not value:
            return None
        try:
            # Remove %, K, M, B suffixes
            cleaned = value.strip().rstrip("%").rstrip("K").rstrip("M").rstrip("B")
            return float(cleaned)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _fallback_result(currency: str, reason: str) -> Dict[str, Any]:
        return {
            "source":             "fallback",
            "currency":           currency,
            "surprise_score":     0,
            "surprise_direction": "NEUTRAL",
            "events":             [],
            "event_count":        0,
            "confidence":         0,
            "reason":             reason,
            "fetched_at":         datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def get_ai_context(self, result: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "surprise_score":       result.get("surprise_score", 0),
            "surprise_direction":   result.get("surprise_direction", "NEUTRAL"),
            "surprise_event_count": result.get("event_count", 0),
            "surprise_confidence":  result.get("confidence", 0),
        }

    def print_summary(self, result: Dict[str, Any]) -> None:
        bar = "═" * 50
        log.info(bar)
        log.info("  📊  ECONOMIC SURPRISE  (Day 96)")
        log.info(bar)
        log.info(f"  Currency       : {result.get('currency','?')}")
        log.info(f"  Score          : {result.get('surprise_score',0):+.1f}")
        log.info(f"  Direction      : {result.get('surprise_direction','?')}")
        log.info(f"  Events         : {result.get('event_count',0)}")
        log.info(f"  Confidence     : {result.get('confidence',0)}%")
        for ev in result.get("events", [])[:3]:
            log.info(f"    {ev['title'][:30]} | F:{ev['forecast']} A:{ev['actual']} ({ev['surprise_pct']:+.1f}%)")
        log.info(bar)
