"""
intelligence/sentiment_model.py — Financial news sentiment analyzer
====================================================================

A FinBERT-style sentiment analyzer that understands forex-specific
language. Instead of generic "positive/negative", it outputs:

  * **sentiment**: positive / negative / neutral
  * **tone**: HAWKISH / DOVISH / NEUTRAL (central bank tone)
  * **currency**: which currency is most affected
  * **impact_score**: 0.0-1.0 financial impact magnitude
  * **keywords**: extracted financial terms ("rates", "inflation", "QE", etc.)

Implementation: uses Groq (llama-3.3-70b) as primary, Gemini as fallback.
No external FinBERT model needed — the LLM does the heavy lifting with a
carefully crafted financial-sentiment prompt.

If no LLM is available, falls back to a rule-based keyword analyzer that
catches the most common patterns ("higher rates" → hawkish, "rate cut" →
dovish, etc.).
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from utils.logger import get_logger

load_dotenv()
log = get_logger("sentiment_model")


# ── LLM client init — Groq (primary) + Gemini (fallback) via KeyManager ──
LLM_AVAILABLE = False
_groq_client = None
_gemini_client = None
_key_manager = None
MODEL = ""

try:
    from core.llm_key_manager import get_llm_key_manager
    _key_manager = get_llm_key_manager()
    _groq_client = _key_manager.get_groq_client()
    if _groq_client is not None:
        MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        LLM_AVAILABLE = True
        log.info(f"[SentimentModel] Groq client initialized | model={MODEL}")
    if not LLM_AVAILABLE:
        _gemini_client = _key_manager.get_gemini_client()
        if _gemini_client is not None:
            MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
            LLM_AVAILABLE = True
            log.info(f"[SentimentModel] Gemini client initialized (fallback) | model={MODEL}")
except Exception as e:
    log.warning(f"[SentimentModel] LLMKeyManager init failed: {e} — trying single-key")
    groq_key = os.getenv("GROQ_API_KEY_1") or os.getenv("GROQ_API_KEY", "")
    if groq_key:
        try:
            from groq import Groq
            _groq_client = Groq(api_key=groq_key)
            MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
            LLM_AVAILABLE = True
        except Exception as e2:
            log.warning(f"[SentimentModel] Groq init failed: {e2}")
    if not LLM_AVAILABLE:
        gemini_key = os.getenv("GEMINI_API_KEY_1") or os.getenv("GEMINI_API_KEY", "")
        if gemini_key:
            try:
                from google import genai as google_genai
                _gemini_client = google_genai.Client(api_key=gemini_key)
                MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
                LLM_AVAILABLE = True
            except Exception as e2:
                log.warning(f"[SentimentModel] Gemini init failed: {e2}")

if not LLM_AVAILABLE:
    log.warning("[SentimentModel] No LLM — using rule-based keyword fallback")


@dataclass
class SentimentResult:
    """Structured sentiment analysis output."""
    sentiment: str           # positive / negative / neutral
    tone: str                # HAWKISH / DOVISH / NEUTRAL
    currency: str            # USD / EUR / GBP / JPY / ALL
    impact_score: float      # 0.0 - 1.0
    keywords: List[str]
    summary: str
    confidence: float        # 0-100
    source: str              # llm / rule_based

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Rule-based fallback keywords ────────────────────────────────────
HAWKISH_KEYWORDS = [
    "higher rates", "rate hike", "rate increase", "tightening", "fight inflation",
    "inflation concern", "strong economy", "robust growth", "hot economy",
    "aggressive", "hawkish", "higher for longer", "inflation fight",
    "monetary tightening", "reduce balance sheet", "quantitative tightening",
    "rate normalization", "overheating", "wage growth strong",
]

DOVISH_KEYWORDS = [
    "rate cut", "rate reduction", "cut rates", "lower rates", "easing",
    "dovish", "accommodative", "support economy", "economic support",
    "quantitative easing", "qe", "stimulus", "soft landing",
    "inflation cooling", "inflation slowing", "weak economy",
    "recession risk", "employment concern", "growth concern",
    "pause rate hikes", "pause hikes", "hold rates steady",
]

CURRENCY_KEYWORDS = {
    "USD": ["fed ", "fomc", "federal reserve", "powell", "dollar", "usd", "us economy", "us inflation", "us rates"],
    "EUR": ["ecb", "lagarde", "eurozone", "euro area", "euro ", "eur ", "eu inflation", "eu rates"],
    "GBP": ["boe", "bailey", "bank of england", "uk economy", "pound", "gbp", "uk inflation", "brexit"],
    "JPY": ["boj", "ueda", "bank of japan", "japan economy", "yen", "jpy", "japan inflation"],
}


# ── LLM prompt ──────────────────────────────────────────────────────
_SENTIMENT_PROMPT = """You are a financial sentiment analyzer specialized in forex news.

Analyze the following news headline/snippet and return ONLY valid JSON (no markdown, no extra text).

JSON schema:
{
  "sentiment": "positive" | "negative" | "neutral",
  "tone": "HAWKISH" | "DOVISH" | "NEUTRAL",
  "currency": "USD" | "EUR" | "GBP" | "JPY" | "ALL",
  "impact_score": 0.0-1.0,
  "keywords": ["most important 2-4 financial terms"],
  "summary": "1-sentence forex-impact summary",
  "confidence": 0-100
}

Rules:
- HAWKISH = higher rates / tightening / inflation fighting → bullish for that currency
- DOVISH  = rate cuts / easing / economic support → bearish for that currency
- "Higher rates" is NOT positive — it's HAWKISH (bullish for the currency mentioned)
- "Rate cut" is NOT negative — it's DOVISH (bearish for the currency mentioned)
- If the news is about Fed/USD, currency = "USD"; ECB/EUR → "EUR"; BoE/GBP → "GBP"; BoJ/JPY → "JPY"
- impact_score: 1.0 = extreme (FOMC rate decision), 0.7 = high (CPI/NFP), 0.4 = medium, 0.2 = low
- If you cannot determine, return sentiment="neutral", tone="NEUTRAL", currency="ALL", impact_score=0.0

News text:
"""


class SentimentModel:
    """Financial news sentiment analyzer (LLM-powered with rule-based fallback)."""

    def __init__(self):
        self._lock = threading.RLock()

    def analyze(self, text: str) -> SentimentResult:
        """Analyze a news headline/snippet and return structured sentiment."""
        if not text or not text.strip():
            return SentimentResult(
                sentiment="neutral", tone="NEUTRAL", currency="ALL",
                impact_score=0.0, keywords=[], summary="empty input",
                confidence=0.0, source="rule_based",
            )

        # Try LLM first
        if LLM_AVAILABLE:
            try:
                result = self._analyze_with_llm(text)
                if result is not None:
                    return result
            except Exception as e:
                log.warning(f"[SentimentModel] LLM analysis failed: {e} — using rule-based fallback")

        # Fallback: rule-based
        return self._analyze_with_rules(text)

    def _analyze_with_llm(self, text: str) -> Optional[SentimentResult]:
        """Use Groq/Gemini to analyze sentiment.

        Day 81+ hotfix: per-cycle LLM throttle caps total calls per
        symbol cycle to MAX_LLM_CALLS_PER_CYCLE.  Also enforces
        LLM_CALL_INTERVAL_SEC between calls to prevent Groq 429 storm.
        SentimentModel was previously bypassing the throttle — that
        caused 30+ 429 errors per cycle in production.
        """
        # Per-cycle throttle check
        if _key_manager is not None:
            try:
                allowed, reason = _key_manager.check_cycle_throttle()
                if not allowed:
                    log.info(f"[SentimentModel] LLM skipped — {reason}")
                    return None
            except Exception:
                pass

        prompt = _SENTIMENT_PROMPT + f'"""\n{text[:1500]}\n"""'

        raw = None
        if _groq_client is not None:
            try:
                resp = _groq_client.chat.completions.create(
                    model=MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=400,
                )
                raw = resp.choices[0].message.content
            except Exception as e:
                log.debug(f"[SentimentModel] Groq call failed: {e}")

        if raw is None and _gemini_client is not None:
            try:
                resp = _gemini_client.models.generate_content(model=MODEL, contents=prompt)
                raw = resp.text
            except Exception as e:
                log.debug(f"[SentimentModel] Gemini call failed: {e}")

        if raw is None:
            return None

        # Parse JSON from response
        try:
            # Strip markdown fences if present
            raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
            raw = re.sub(r"\s*```$", "", raw).strip()
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                data = json.loads(raw)

            return SentimentResult(
                sentiment=str(data.get("sentiment", "neutral")).lower(),
                tone=str(data.get("tone", "NEUTRAL")).upper(),
                currency=str(data.get("currency", "ALL")).upper(),
                impact_score=float(data.get("impact_score", 0.0)),
                keywords=list(data.get("keywords", []))[:5],
                summary=str(data.get("summary", ""))[:300],
                confidence=float(data.get("confidence", 50)),
                source="llm",
            )
        except Exception as e:
            log.warning(f"[SentimentModel] LLM JSON parse failed: {e} — raw: {raw[:200]}")
            return None

    def _analyze_with_rules(self, text: str) -> SentimentResult:
        """Rule-based fallback: keyword matching."""
        text_lower = text.lower()

        # Detect tone
        tone = "NEUTRAL"
        hawkish_hits = sum(1 for kw in HAWKISH_KEYWORDS if kw in text_lower)
        dovish_hits = sum(1 for kw in DOVISH_KEYWORDS if kw in text_lower)
        if hawkish_hits > dovish_hits:
            tone = "HAWKISH"
        elif dovish_hits > hawkish_hits:
            tone = "DOVISH"

        # Detect currency
        currency = "ALL"
        currency_hits = {}
        for cur, keywords in CURRENCY_KEYWORDS.items():
            hits = sum(1 for kw in keywords if kw in text_lower)
            if hits > 0:
                currency_hits[cur] = hits
        if currency_hits:
            currency = max(currency_hits, key=currency_hits.get)

        # Sentiment from tone
        if tone == "HAWKISH":
            sentiment = "positive"  # positive for the currency
        elif tone == "DOVISH":
            sentiment = "negative"
        else:
            sentiment = "neutral"

        # Impact score from keyword density
        total_hits = hawkish_hits + dovish_hits
        impact_score = min(1.0, total_hits * 0.2)

        # Extract matched keywords
        keywords = []
        for kw in HAWKISH_KEYWORDS + DOVISH_KEYWORDS:
            if kw in text_lower and kw not in keywords:
                keywords.append(kw)
            if len(keywords) >= 4:
                break

        return SentimentResult(
            sentiment=sentiment,
            tone=tone,
            currency=currency,
            impact_score=impact_score,
            keywords=keywords,
            summary=f"Rule-based: {tone} signal for {currency}" if tone != "NEUTRAL" else "No strong signal",
            confidence=min(80.0, 40.0 + total_hits * 10),
            source="rule_based",
        )


# ── singleton ───────────────────────────────────────────────────────
_SENTIMENT_MODEL: Optional[SentimentModel] = None


def get_sentiment_model() -> SentimentModel:
    global _SENTIMENT_MODEL
    if _SENTIMENT_MODEL is None:
        _SENTIMENT_MODEL = SentimentModel()
    return _SENTIMENT_MODEL
