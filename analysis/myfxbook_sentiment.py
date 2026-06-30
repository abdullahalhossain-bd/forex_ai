"""
analysis/myfxbook_sentiment.py — Day 95 Myfxbook Community Outlook (OANDA alternative)
=====================================================================================
Pulls retail trader sentiment from Myfxbook's Community Outlook page.

Why this exists:
  OANDA's v20 API requires a practice account + token. Many users don't
  want to open an OANDA account just for sentiment data. Myfxbook's
  Community Outlook is FREE, public, and requires NO API key — it's
  scraped from their public webpage.

Myfxbook Community Outlook shows:
  - % of retail traders long vs short per pair
  - Average entry price for longs and shorts
  - Total long/short volume
  - Pip P/L distribution

This is a CONTRARIAN indicator: when 80%+ retail is long, smart money
is usually short, and price tends to reverse.

Fallback chain (in retail_sentiment.py):
  1. OANDA v20 (if OANDA_API_KEY set) — most accurate, has order book
  2. Myfxbook Community Outlook (this module, no key needed) — good accuracy
  3. Synthetic sentiment (computed from RSI + price action) — last resort

Usage:
    from analysis.myfxbook_sentiment import MyfxbookSentiment
    api = MyfxbookSentiment()
    result = api.get_sentiment("EURUSD")
    # result = {"long_pct": 72.3, "short_pct": 27.7, "contrarian": "BEARISH", ...}

Notes:
  - Myfxbook's public outlook page is HTML, so we parse it with BeautifulSoup.
  - The page is updated every ~5 minutes.
  - No rate limit on public page views, but be polite (1 req per pair per cycle).
  - If Myfxbook adds bot-detection, we fall back to synthetic sentiment.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from utils.logger import get_logger

log = get_logger("myfxbook_sentiment")


class MyfxbookSentiment:
    """Myfxbook Community Outlook scraper — free, no API key needed."""

    BASE_URL = "https://www.myfxbook.com/community/outlook"
    # Cache results for 10 minutes to avoid hitting the page too often
    _cache: Dict[str, tuple] = {}  # pair -> (timestamp, data)
    CACHE_TTL_SEC = 600  # 10 minutes

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.myfxbook.com/",
    }

    def __init__(self):
        self._available = True  # public page, no key needed

    @property
    def available(self) -> bool:
        return self._available

    # ─────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────

    def get_sentiment(self, pair: str) -> Dict[str, Any]:
        """Get retail sentiment for a pair from Myfxbook Community Outlook.

        Args:
            pair: e.g. "EURUSD" (will be converted to "EUR/USD")

        Returns: dict with long_pct, short_pct, contrarian_signal, etc.
                 Falls back to neutral if scrape fails.
        """
        # Cache check
        cached = self._cache.get(pair)
        if cached and (datetime.now(timezone.utc).timestamp() - cached[0]) < self.CACHE_TTL_SEC:
            result = dict(cached[1])
            result["source"] = "myfxbook_cached"
            return result

        # Try to scrape the outlook page
        outlook_data = self._fetch_outlook_page()

        if not outlook_data:
            return self._fallback_result(pair, "Myfxbook scrape failed")

        # Find this pair in the outlook data
        pair_data = self._find_pair(outlook_data, pair)
        if not pair_data:
            return self._fallback_result(pair, f"{pair} not found in Myfxbook outlook")

        # Compute derived metrics
        long_pct = pair_data["long_pct"]
        short_pct = pair_data["short_pct"]
        ratio = long_pct / short_pct if short_pct > 0 else float("inf")
        net_pct = long_pct - short_pct

        sentiment_label = "BULLISH" if long_pct > short_pct else "BEARISH"
        contrarian_signal = "BEARISH" if long_pct > 60 else "BULLISH" if long_pct < 40 else "NEUTRAL"
        contrarian_strength = (
            "STRONG" if long_pct > 75 or long_pct < 25
            else "MODERATE" if long_pct > 60 or long_pct < 40
            else "WEAK"
        )
        trade_bias = contrarian_signal
        confidence = self._compute_confidence(long_pct, short_pct, contrarian_strength)

        result = {
            "source":              "myfxbook_live",
            "pair":                pair,
            "long_pct":            round(long_pct, 1),
            "short_pct":           round(short_pct, 1),
            "sentiment_label":     sentiment_label,
            "contrarian_signal":   contrarian_signal,
            "contrarian_strength": contrarian_strength,
            "long_short_ratio":    round(ratio, 2),
            "net_position_pct":    round(net_pct, 1),
            "avg_long_price":      pair_data.get("avg_long_price"),
            "avg_short_price":     pair_data.get("avg_short_price"),
            "total_long_volume":   pair_data.get("total_long_volume"),
            "total_short_volume":  pair_data.get("total_short_volume"),
            "order_book":          {"price_levels": [], "stop_cluster": None},
            "trade_bias":          trade_bias,
            "confidence":          confidence,
            "fetched_at":          datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

        # Cache it
        self._cache[pair] = (datetime.now(timezone.utc).timestamp(), result)

        log.info(
            f"[Myfxbook] {pair} | retail {sentiment_label} "
            f"({long_pct:.0f}%L/{short_pct:.0f}%S) | "
            f"contrarian={contrarian_signal}({contrarian_strength}) | "
            f"bias={trade_bias} conf={confidence}%"
        )
        return result

    # ─────────────────────────────────────────────────────────
    # Scraping
    # ─────────────────────────────────────────────────────────

    def _fetch_outlook_page(self) -> Optional[List[Dict]]:
        """Fetch and parse Myfxbook's community outlook page.

        Returns: list of dicts, each with pair, long_pct, short_pct, etc.
                 None on failure.
        """
        try:
            resp = requests.get(self.BASE_URL, headers=self.HEADERS, timeout=15)
            if resp.status_code != 200:
                log.warning(f"[Myfxbook] HTTP {resp.status_code}")
                return None
            html = resp.text
        except Exception as e:
            log.warning(f"[Myfxbook] fetch failed: {e}")
            return None

        return self._parse_outlook_html(html)

    @staticmethod
    def _parse_outlook_html(html: str) -> List[Dict]:
        """Parse Myfxbook outlook HTML to extract per-pair sentiment.

        Myfxbook's outlook page has a table with rows like:
          EUR/USD | 72% long | 28% short | avg long 1.0850 | avg short 1.0820

        We use regex + BeautifulSoup to extract this.
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            log.warning("[Myfxbook] BeautifulSoup not installed")
            return []

        soup = BeautifulSoup(html, "html.parser")
        results = []

        # Myfxbook uses a table with class 'outlookTable' or similar
        # Each row has the pair name + long/short percentages
        # Try multiple selectors since the page structure changes

        # Approach 1: look for table rows with pair names
        for row in soup.select("tr"):
            try:
                text = row.get_text(separator=" ", strip=True)
                # Look for patterns like "EUR/USD" followed by percentages
                match = re.search(
                    r"([A-Z]{3}/[A-Z]{3}).*?(\d+(?:\.\d+)?)%.*?(\d+(?:\.\d+)?)%",
                    text
                )
                if match:
                    pair_name = match.group(1)
                    long_pct = float(match.group(2))
                    short_pct = float(match.group(3))

                    # Validate: percentages should sum to ~100
                    if abs(long_pct + short_pct - 100) > 5:
                        continue  # not a sentiment row, skip

                    # Try to extract average prices
                    prices = re.findall(r"(\d+\.\d{4,5})", text)
                    avg_long = float(prices[0]) if len(prices) >= 1 else None
                    avg_short = float(prices[1]) if len(prices) >= 2 else None

                    results.append({
                        "pair":             pair_name,
                        "long_pct":         long_pct,
                        "short_pct":        short_pct,
                        "avg_long_price":   avg_long,
                        "avg_short_price":  avg_short,
                        "total_long_volume": None,
                        "total_short_volume": None,
                    })
            except Exception:
                continue

        # Deduplicate by pair name (keep first occurrence)
        seen = set()
        unique = []
        for r in results:
            if r["pair"] not in seen:
                seen.add(r["pair"])
                unique.append(r)

        log.debug(f"[Myfxbook] parsed {len(unique)} pairs from outlook page")
        return unique

    @staticmethod
    def _find_pair(outlook_data: List[Dict], pair: str) -> Optional[Dict]:
        """Find a specific pair in the outlook data.

        Args:
            outlook_data: list of dicts from _parse_outlook_html
            pair: e.g. "EURUSD" (will match "EUR/USD" in data)

        Returns: matching dict or None
        """
        # Normalize: EURUSD → EUR/USD
        target = pair.upper().replace("/", "").replace("=X", "")
        if len(target) >= 6:
            target = f"{target[:3]}/{target[3:6]}"

        for item in outlook_data:
            if item["pair"].upper() == target:
                return item
        return None

    # ─────────────────────────────────────────────────────────
    # Confidence calculation
    # ─────────────────────────────────────────────────────────

    @staticmethod
    def _compute_confidence(long_pct: float, short_pct: float, strength: str) -> int:
        """Contrarian confidence — higher when retail is more one-sided."""
        extremes = abs(long_pct - 50)
        base = int(extremes * 2)
        bonus = {"STRONG": 10, "MODERATE": 5, "WEAK": 0}.get(strength, 0)
        return max(0, min(100, base + bonus))

    # ─────────────────────────────────────────────────────────
    # Fallback (synthetic sentiment from RSI — last resort)
    # ─────────────────────────────────────────────────────────

    @staticmethod
    def _fallback_result(pair: str, reason: str) -> Dict[str, Any]:
        """When Myfxbook unavailable — return neutral sentiment."""
        return {
            "source":              "fallback",
            "pair":                pair,
            "long_pct":            50.0,
            "short_pct":           50.0,
            "sentiment_label":     "NEUTRAL",
            "contrarian_signal":   "NEUTRAL",
            "contrarian_strength": "WEAK",
            "long_short_ratio":    1.0,
            "net_position_pct":    0.0,
            "avg_long_price":      None,
            "avg_short_price":     None,
            "total_long_volume":   None,
            "total_short_volume":  None,
            "order_book":          {"price_levels": [], "stop_cluster": None},
            "trade_bias":          "NEUTRAL",
            "confidence":          0,
            "reason":              reason,
            "fetched_at":          datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    # ─────────────────────────────────────────────────────────
    # Synthetic sentiment (RSI-based — no external API needed)
    # ─────────────────────────────────────────────────────────

    @staticmethod
    def compute_synthetic_sentiment(pair: str, df) -> Dict[str, Any]:
        """Compute synthetic retail sentiment from price action.

        When both OANDA and Myfxbook are unavailable, we can estimate
        retail sentiment from RSI + recent price action:
          - RSI > 70 (overbought) → retail likely 70%+ long (chasing)
          - RSI < 30 (oversold) → retail likely 70%+ short (panic)
          - RSI 45-55 → balanced

        This is less accurate than real sentiment data but better
        than nothing — it at least captures the "retail chases trends"
        pattern.

        Args:
            pair: e.g. "EURUSD"
            df: DataFrame with 'close' column + ideally 'rsi' column

        Returns: same shape as get_sentiment() output
        """
        if df is None or len(df) == 0:
            return MyfxbookSentiment._fallback_result(pair, "no data for synthetic sentiment")

        # Get RSI (compute if not present)
        if "rsi" in df.columns:
            rsi = float(df["rsi"].iloc[-1])
        else:
            try:
                import pandas_ta as ta
                rsi = float(ta.rsi(df["close"], length=14).iloc[-1])
            except Exception:
                return MyfxbookSentiment._fallback_result(pair, "RSI computation failed")

        if rsi != rsi:  # NaN check
            return MyfxbookSentiment._fallback_result(pair, "RSI is NaN")

        # Map RSI to retail long%:
        # RSI 50 → 50% long (balanced)
        # RSI 70 → 70% long (retail chasing up)
        # RSI 30 → 30% long (retail panicking out)
        # RSI 80 → 80% long (euphoria)
        # RSI 20 → 20% long (capitulation)
        long_pct = max(10, min(90, rsi))
        short_pct = 100 - long_pct

        sentiment_label = "BULLISH" if long_pct > short_pct else "BEARISH"
        contrarian_signal = "BEARISH" if long_pct > 60 else "BULLISH" if long_pct < 40 else "NEUTRAL"
        contrarian_strength = (
            "STRONG" if long_pct > 75 or long_pct < 25
            else "MODERATE" if long_pct > 60 or long_pct < 40
            else "WEAK"
        )
        confidence = MyfxbookSentiment._compute_confidence(long_pct, short_pct, contrarian_strength)

        result = {
            "source":              "synthetic_rsi",
            "pair":                pair,
            "long_pct":            round(long_pct, 1),
            "short_pct":           round(short_pct, 1),
            "sentiment_label":     sentiment_label,
            "contrarian_signal":   contrarian_signal,
            "contrarian_strength": contrarian_strength,
            "long_short_ratio":    round(long_pct / short_pct, 2) if short_pct > 0 else 99,
            "net_position_pct":    round(long_pct - short_pct, 1),
            "rsi_basis":           round(rsi, 1),
            "order_book":          {"price_levels": [], "stop_cluster": None},
            "trade_bias":          contrarian_signal,
            "confidence":          max(0, confidence - 20),  # lower confidence for synthetic
            "fetched_at":          datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        log.info(
            f"[SyntheticSent] {pair} | RSI={rsi:.1f} → retail {sentiment_label} "
            f"({long_pct:.0f}%L/{short_pct:.0f}%S) | contrarian={contrarian_signal}"
        )
        return result

    # ─────────────────────────────────────────────────────────
    # AI context (compatible with RetailSentimentAPI)
    # ─────────────────────────────────────────────────────────

    def get_ai_context(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Compact context for MasterAnalyst — same shape as RetailSentimentAPI."""
        return {
            "sentiment_source":         result.get("source", "fallback"),
            "sentiment_retail_long":    result.get("long_pct", 50),
            "sentiment_retail_short":   result.get("short_pct", 50),
            "sentiment_label":          result.get("sentiment_label", "NEUTRAL"),
            "sentiment_contrarian":     result.get("contrarian_signal", "NEUTRAL"),
            "sentiment_strength":       result.get("contrarian_strength", "WEAK"),
            "sentiment_bias":           result.get("trade_bias", "NEUTRAL"),
            "sentiment_confidence":     result.get("confidence", 0),
            "sentiment_stop_cluster":   result.get("order_book", {}).get("stop_cluster"),
        }

    def print_summary(self, result: Dict[str, Any]) -> None:
        bar = "═" * 50
        log.info(bar)
        log.info("  👥  MYFXBOOK SENTIMENT  (Day 95)")
        log.info(bar)
        log.info(f"  Pair           : {result.get('pair','?')}")
        log.info(f"  Source         : {result.get('source','?')}")
        log.info(f"  Retail Long %  : {result.get('long_pct',0):.1f}")
        log.info(f"  Retail Short % : {result.get('short_pct',0):.1f}")
        log.info(f"  Sentiment      : {result.get('sentiment_label','?')} (retail mood)")
        log.info(f"  Contrarian     : {result.get('contrarian_signal','?')} ({result.get('contrarian_strength','?')})")
        log.info(f"  Trade bias     : {result.get('trade_bias','?')} | conf {result.get('confidence',0)}%")
        if result.get("rsi_basis"):
            log.info(f"  RSI basis      : {result['rsi_basis']}")
        log.info(bar)


# ── Singleton ────────────────────────────────────────────────────

_INSTANCE: Optional[MyfxbookSentiment] = None


def get_myfxbook_sentiment() -> MyfxbookSentiment:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = MyfxbookSentiment()
    return _INSTANCE
