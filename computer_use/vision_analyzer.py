# computer_use/vision_analyzer.py  —  Day 47 | Vision AI Analysis Engine
# ============================================================
# Chart image → Claude Vision → Structured JSON output
#
# Features:
#   ✅ Single model chart analysis
#   ✅ Context-aware analysis (image + quant data)
#   ✅ Multi-model verification (Vision A + Vision B + Quant)
#   ✅ Visual confidence scoring (pattern/trend/entry)
#   ✅ Vision vs Quant conflict detection
#   ✅ Memory DB integration (vision_analysis table)
# ============================================================

import base64
import json
import os
import re
import sqlite3
from datetime import datetime, timezone

from utils.logger import get_logger
from computer_use.vision_prompt import (
    BASIC_CHART_SYSTEM,
    CONTEXT_CHART_SYSTEM,
    CONFLICT_CHECK_SYSTEM,
    build_context_prompt,
    build_conflict_prompt,
)

log = get_logger("computer_use.vision_analyzer")

try:
    import anthropic
    _client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    LLM_AVAILABLE = True
except Exception:
    LLM_AVAILABLE = False
    log.warning("[VisionAnalyzer] anthropic not available")

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1000
VISION_DB = "memory/vision_analysis.db"


class VisionAnalyzer:
    """
    Chart image → structured trade analysis।

    Usage:
        analyzer = VisionAnalyzer()

        # Basic (image only):
        result = analyzer.analyze_image("chart.png")

        # Context-aware (image + quant):
        result = analyzer.analyze_with_context(
            "chart.png",
            symbol="EURUSD", timeframe="M15",
            rsi=45, trend="bearish", current_price=1.0850
        )

        # Multi-model verification:
        result = analyzer.multi_model_verify("chart.png", quant_ctx={...})
    """

    def __init__(self):
        self._init_db()

    # ═══════════════════════════════════════════════════════════
    # 1. BASIC CHART ANALYSIS
    # ═══════════════════════════════════════════════════════════

    def analyze_image(self, image_path: str) -> dict:
        """
        Chart image শুধু দেখে analysis করো (quant context ছাড়া)।
        """
        if not LLM_AVAILABLE:
            return self._fallback("LLM not available")

        b64 = self._load_image(image_path)
        if not b64:
            return self._fallback(f"Cannot load image: {image_path}")

        log.info(f"[VisionAnalyzer] Basic analysis: {image_path}")

        try:
            raw = self._call_vision_api(
                system=BASIC_CHART_SYSTEM,
                user_text="Analyze this TradingView chart. Return JSON only.",
                image_b64=b64,
            )
            result = self._parse_json(raw)
            result["analysis_type"] = "basic"
            result["image_path"] = image_path
            result["llm_raw"] = raw
            return result

        except Exception as e:
            log.error(f"[VisionAnalyzer] analyze_image error: {e}")
            return self._fallback(str(e))

    # ═══════════════════════════════════════════════════════════
    # 2. CONTEXT-AWARE ANALYSIS  ⭐⭐⭐⭐⭐
    # ═══════════════════════════════════════════════════════════

    def analyze_with_context(
        self,
        image_path: str,
        symbol: str,
        timeframe: str,
        current_price: float,
        rsi: float = None,
        macd: str = None,
        trend: str = None,
        support: float = None,
        resistance: float = None,
    ) -> dict:
        """
        Image + quant context দিয়ে analysis করো।
        Vision AI context বুঝলে ভুল কম করে।
        """
        if not LLM_AVAILABLE:
            return self._fallback("LLM not available")

        b64 = self._load_image(image_path)
        if not b64:
            return self._fallback(f"Cannot load image: {image_path}")

        user_text = build_context_prompt(
            symbol=symbol,
            timeframe=timeframe,
            current_price=current_price,
            rsi=rsi,
            macd=macd,
            trend=trend,
            support=support,
            resistance=resistance,
        )

        log.info(f"[VisionAnalyzer] Context analysis: {symbol} {timeframe}")

        try:
            raw = self._call_vision_api(
                system=CONTEXT_CHART_SYSTEM,
                user_text=user_text,
                image_b64=b64,
            )
            result = self._parse_json(raw)
            result["analysis_type"] = "context_aware"
            result["image_path"] = image_path
            result["llm_raw"] = raw

            # Override symbol/timeframe from context (more reliable)
            result["pair"] = symbol
            result["timeframe"] = timeframe

            log.info(
                f"[VisionAnalyzer] Done | Trend: {result.get('trend')} | "
                f"Confidence: {result.get('confidence')}%"
            )
            return result

        except Exception as e:
            log.error(f"[VisionAnalyzer] analyze_with_context error: {e}")
            return self._fallback(str(e))

    # ═══════════════════════════════════════════════════════════
    # 3. VISION + QUANT CONFLICT DETECTION  ⭐⭐⭐⭐⭐
    # ═══════════════════════════════════════════════════════════

    def detect_conflict(self, vision_result: dict, quant_ctx: dict) -> dict:
        """
        Vision analysis ও Quant analysis-এর মধ্যে conflict detect করো।

        Example conflict:
          Quant: BEARISH trend
          Vision: Hammer candle + bullish reversal pattern
          → Conflict detected → reduce confidence → wait
        """
        if not LLM_AVAILABLE:
            return self._simple_conflict_check(vision_result, quant_ctx)

        user_text = build_conflict_prompt(quant_ctx, vision_result)

        try:
            raw = self._call_llm_text(
                system=CONFLICT_CHECK_SYSTEM,
                user_text=user_text,
            )
            result = self._parse_json(raw)
            result["llm_raw"] = raw

            # Log conflict
            if result.get("has_conflict"):
                log.warning(
                    f"[VisionAnalyzer] ⚠️ CONFLICT DETECTED | "
                    f"Quant: {result.get('quant_says')} vs "
                    f"Vision: {result.get('vision_says')} | "
                    f"Severity: {result.get('conflict_severity')}"
                )
            else:
                log.info("[VisionAnalyzer] ✅ No conflict — Vision and Quant agree")

            return result

        except Exception as e:
            log.error(f"[VisionAnalyzer] detect_conflict error: {e}")
            return self._simple_conflict_check(vision_result, quant_ctx)

    def _simple_conflict_check(self, vision: dict, quant: dict) -> dict:
        """LLM ছাড়া simple rule-based conflict check।"""
        vision_trend = vision.get("trend", "")
        quant_trend  = quant.get("trend", quant.get("market_direction", ""))

        conflict = False
        if vision_trend and quant_trend:
            v_bull = "BULLISH" in vision_trend.upper()
            v_bear = "BEARISH" in vision_trend.upper()
            q_bull = "bullish" in quant_trend.lower()
            q_bear = "bearish" in quant_trend.lower()
            conflict = (v_bull and q_bear) or (v_bear and q_bull)

        return {
            "has_conflict": conflict,
            "conflict_type": "TREND" if conflict else "NONE",
            "quant_says": quant.get("signal", "WAIT"),
            "vision_says": vision.get("trend", "UNKNOWN"),
            "conflict_severity": "MEDIUM" if conflict else "NONE",
            "explanation": "Trend direction mismatch" if conflict else "Analysis aligned",
            "recommendation": "WAIT_FOR_CONFIRMATION" if conflict else "PROCEED",
            "confidence_adjustment": -15 if conflict else 0,
            "final_bias": "WAIT" if conflict else quant.get("signal", "WAIT"),
        }

    # ═══════════════════════════════════════════════════════════
    # 4. MULTI-MODEL VERIFICATION  ⭐⭐⭐⭐⭐
    # ═══════════════════════════════════════════════════════════

    def multi_model_verify(
        self,
        image_path: str,
        quant_ctx: dict,
        symbol: str = None,
        timeframe: str = None,
    ) -> dict:
        """
        Vision Model A + Vision Model B (different prompts) + Quant → consensus।

        Model A: Basic visual analysis
        Model B: Context-aware analysis
        Quant:   Technical indicators

        তারপর তিনটা মিলিয়ে consensus তৈরি হয়।
        """
        log.info("[VisionAnalyzer] Multi-model verification started")

        # Model A: Basic vision
        result_a = self.analyze_image(image_path)

        # Model B: Context-aware vision
        result_b = None
        if symbol and timeframe:
            result_b = self.analyze_with_context(
                image_path=image_path,
                symbol=symbol,
                timeframe=timeframe,
                current_price=quant_ctx.get("close", quant_ctx.get("price", 0)),
                rsi=quant_ctx.get("rsi"),
                macd=quant_ctx.get("macd_cross"),
                trend=quant_ctx.get("trend"),
                support=quant_ctx.get("nearest_support"),
                resistance=quant_ctx.get("nearest_resistance"),
            )

        # Conflict check (A vs Quant)
        conflict_a = self.detect_conflict(result_a, quant_ctx)

        # Conflict check (B vs Quant)
        conflict_b = None
        if result_b:
            conflict_b = self.detect_conflict(result_b, quant_ctx)

        # Consensus logic
        consensus = self._build_consensus(result_a, result_b, quant_ctx, conflict_a, conflict_b)

        return {
            "model_a": result_a,
            "model_b": result_b,
            "conflict_a": conflict_a,
            "conflict_b": conflict_b,
            "consensus": consensus,
            "analysis_type": "multi_model",
        }

    def _build_consensus(self, a, b, quant, conflict_a, conflict_b) -> dict:
        """তিনটা source-এর consensus তৈরি করো।"""
        votes = []

        # Model A vote
        a_trend = a.get("trend", "")
        if "BULLISH" in a_trend.upper():
            votes.append("BUY")
        elif "BEARISH" in a_trend.upper():
            votes.append("SELL")
        else:
            votes.append("WAIT")

        # Model B vote
        if b:
            b_trend = b.get("trend", "")
            if "BULLISH" in b_trend.upper():
                votes.append("BUY")
            elif "BEARISH" in b_trend.upper():
                votes.append("SELL")
            else:
                votes.append("WAIT")

        # Quant vote
        quant_signal = quant.get("signal", quant.get("rule_signal", "WAIT"))
        if quant_signal == "BUY":
            votes.append("BUY")
        elif quant_signal == "SELL":
            votes.append("SELL")
        else:
            votes.append("WAIT")

        buy_count  = votes.count("BUY")
        sell_count = votes.count("SELL")
        wait_count = votes.count("WAIT")

        # Majority
        if buy_count > sell_count and buy_count > wait_count:
            final = "BUY"
        elif sell_count > buy_count and sell_count > wait_count:
            final = "SELL"
        else:
            final = "WAIT"

        # Confidence
        total = len(votes)
        top_count = max(buy_count, sell_count, wait_count)
        agreement_pct = round(top_count / total * 100) if total > 0 else 0

        # Reduce if conflict
        has_any_conflict = (
            (conflict_a or {}).get("has_conflict", False) or
            (conflict_b or {}).get("has_conflict", False)
        )
        if has_any_conflict:
            agreement_pct = max(0, agreement_pct - 20)
            if agreement_pct < 50:
                final = "WAIT"

        avg_confidence = round(
            (a.get("confidence", 50) + (b.get("confidence", 50) if b else 50)) / 2
        )

        return {
            "signal":         final,
            "votes":          votes,
            "buy_votes":      buy_count,
            "sell_votes":     sell_count,
            "wait_votes":     wait_count,
            "agreement_pct":  agreement_pct,
            "has_conflict":   has_any_conflict,
            "avg_confidence": avg_confidence,
            "note": (
                f"Consensus: {final} | Agreement: {agreement_pct}% | "
                f"Conflict: {'YES' if has_any_conflict else 'NO'}"
            ),
        }

    # ═══════════════════════════════════════════════════════════
    # 5. AI CONTEXT  (MasterAnalyst-এ inject করার জন্য)
    # ═══════════════════════════════════════════════════════════

    def get_ai_context(self, result: dict) -> dict:
        """AnalysisAgent / MasterAnalyst-এ pass করার জন্য context।"""
        # Multi-model result হলে consensus থেকে নাও
        if result.get("analysis_type") == "multi_model":
            consensus = result.get("consensus", {})
            vision_main = result.get("model_b") or result.get("model_a", {})
        else:
            consensus = {}
            vision_main = result

        return {
            "vision_trend":          vision_main.get("trend", "UNKNOWN"),
            "vision_trend_strength": vision_main.get("trend_strength", "UNKNOWN"),
            "vision_patterns":       vision_main.get("pattern", []),
            "vision_candle_pattern": vision_main.get("candlestick_patterns", []),
            "vision_chart_pattern":  vision_main.get("chart_patterns", []),
            "vision_support":        vision_main.get("support", []),
            "vision_resistance":     vision_main.get("resistance", []),
            "vision_momentum":       vision_main.get("momentum", "UNKNOWN"),
            "vision_condition":      vision_main.get("market_condition", ""),
            "vision_psychology":     vision_main.get("market_psychology", ""),
            "vision_vs_quant":       vision_main.get("visual_vs_quant", "UNKNOWN"),
            "vision_conflict":       vision_main.get("conflict_detail", ""),
            # Confidence scores
            "vision_confidence":     vision_main.get("confidence", 0),
            "pattern_confidence":    vision_main.get("pattern_confidence", 0),
            "trend_confidence":      vision_main.get("trend_confidence", 0),
            "entry_confidence":      vision_main.get("entry_confidence", 0),
            # Multi-model
            "consensus_signal":      consensus.get("signal", "WAIT"),
            "consensus_agreement":   consensus.get("agreement_pct", 0),
            "multi_model_conflict":  consensus.get("has_conflict", False),
        }

    # ═══════════════════════════════════════════════════════════
    # 6. MEMORY DB  ⭐⭐⭐⭐⭐
    # ═══════════════════════════════════════════════════════════

    def save_to_memory(
        self,
        pair: str,
        timeframe: str,
        image_path: str,
        vision_result: dict,
        actual_result: str = None,   # WIN / LOSS / OPEN
    ) -> None:
        """Vision analysis result database-এ save করো।"""
        try:
            conn = sqlite3.connect(VISION_DB)
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO vision_analysis
                (date, pair, timeframe, chart_image, vision_result, actual_result)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                datetime.now(timezone.utc).isoformat(),
                pair,
                timeframe,
                image_path,
                json.dumps(vision_result, default=str),
                actual_result,
            ))
            conn.commit()
            conn.close()
            log.info(f"[VisionAnalyzer] Saved to memory DB: {pair} {timeframe}")
        except Exception as e:
            log.error(f"[VisionAnalyzer] DB save error: {e}")

    def _init_db(self) -> None:
        """vision_analysis table তৈরি করো।"""
        try:
            os.makedirs("memory", exist_ok=True)
            conn = sqlite3.connect(VISION_DB)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS vision_analysis (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    date           TEXT,
                    pair           TEXT,
                    timeframe      TEXT,
                    chart_image    TEXT,
                    vision_result  TEXT,
                    actual_result  TEXT
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            log.warning(f"[VisionAnalyzer] DB init error: {e}")

    # ═══════════════════════════════════════════════════════════
    # LLM HELPERS
    # ═══════════════════════════════════════════════════════════

    def _call_vision_api(self, system: str, user_text: str, image_b64: str) -> str:
        """Vision API call (image + text)।"""
        response = _client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": image_b64,
                        },
                    },
                    {"type": "text", "text": user_text},
                ],
            }],
        )
        return response.content[0].text.strip()

    def _call_llm_text(self, system: str, user_text: str) -> str:
        """Text-only LLM call (conflict detection-এর জন্য)।"""
        response = _client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            messages=[{"role": "user", "content": user_text}],
        )
        return response.content[0].text.strip()

    def _load_image(self, path: str) -> str:
        """Image file → base64 string।"""
        if not os.path.exists(path):
            log.error(f"[VisionAnalyzer] Image not found: {path}")
            return ""
        try:
            with open(path, "rb") as f:
                return base64.standard_b64encode(f.read()).decode("utf-8")
        except Exception as e:
            log.error(f"[VisionAnalyzer] Image load error: {e}")
            return ""

    def _parse_json(self, raw: str) -> dict:
        """LLM response থেকে JSON parse করো।"""
        text = raw.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                return json.loads(match.group())
            return {"error": "JSON parse failed", "raw": text[:200]}

    def _fallback(self, reason: str) -> dict:
        return {
            "trend": "UNKNOWN",
            "trend_strength": "UNKNOWN",
            "pattern": [],
            "market_condition": "Vision unavailable",
            "momentum": "UNKNOWN",
            "confidence": 0,
            "pattern_confidence": 0,
            "trend_confidence": 0,
            "entry_confidence": 0,
            "error": reason,
            "analysis_type": "fallback",
        }

    # ═══════════════════════════════════════════════════════════
    # PRINT SUMMARY
    # ═══════════════════════════════════════════════════════════

    def print_summary(self, result: dict) -> None:
        bar = "═" * 56

        # Multi-model result
        if result.get("analysis_type") == "multi_model":
            consensus = result.get("consensus", {})
            print(f"\n{bar}")
            print("  👁️   VISION ANALYZER — Multi-Model  (Day 47)")
            print(bar)
            print(f"  Consensus Signal  : {consensus.get('signal', 'WAIT')}")
            print(f"  Agreement         : {consensus.get('agreement_pct', 0)}%")
            print(f"  Votes             : BUY={consensus.get('buy_votes', 0)} "
                  f"SELL={consensus.get('sell_votes', 0)} WAIT={consensus.get('wait_votes', 0)}")
            print(f"  Has Conflict      : {'⚠️ YES' if consensus.get('has_conflict') else '✅ NO'}")
            print(f"  Avg Confidence    : {consensus.get('avg_confidence', 0)}%")
            print(bar + "\n")
            return

        # Single model result
        trend_icon = {"BULLISH": "🟢", "BEARISH": "🔴", "SIDEWAYS": "🟡"}.get(
            result.get("trend", ""), "⚪"
        )
        print(f"\n{bar}")
        print("  👁️   VISION ANALYZER  (Day 47)")
        print(bar)
        print(f"  Pair           : {result.get('pair', 'N/A')}")
        print(f"  Timeframe      : {result.get('timeframe', 'N/A')}")
        print(f"  Trend          : {trend_icon}  {result.get('trend', 'UNKNOWN')}")
        print(f"  Strength       : {result.get('trend_strength', '')}")
        print(f"  Momentum       : {result.get('momentum', '')}")
        print(f"  Pattern        : {result.get('pattern', [])}")
        print(f"  Condition      : {result.get('market_condition', '')}")
        print()
        print(f"  ── Confidence Scores ──")
        print(f"  Overall        : {result.get('confidence', 0)}%")
        print(f"  Pattern        : {result.get('pattern_confidence', 0)}%")
        print(f"  Trend          : {result.get('trend_confidence', 0)}%")
        print(f"  Entry          : {result.get('entry_confidence', 0)}%")
        if result.get("visual_vs_quant"):
            print()
            print(f"  Vision vs Quant : {result.get('visual_vs_quant')}")
        if result.get("error"):
            print(f"\n  ⚠️  Error: {result['error']}")
        print(bar + "\n")