# computer_use/chart_reader.py  —  Day 47 | Chart Vision Intelligence Layer ⭐
# ============================================================
# Day 47-এর CORE FILE।
#
# Pipeline:
#   TradingView open
#     ↓
#   Correct pair + timeframe load
#     ↓
#   Chart capture (ImageCapture)
#     ↓
#   Vision AI analysis (VisionAnalyzer)
#     ↓
#   Quant analysis-এর সাথে compare
#     ↓
#   Conflict detect → confidence adjust
#     ↓
#   Structured JSON signal
#     ↓
#   MasterAnalyst-এ inject
#
# Architecture:
#   Market Data
#       ↓
#   ┌────────────────────┐
#   │                    │
#   Quant Analysis   Vision Analysis
#   (OHLC/RSI/MACD)  (Chart Image)
#   │                    │
#   └─────────┬──────────┘
#             ↓
#       Master Analyst AI
#             ↓
#         Final Decision
# ============================================================

import os
import time
from datetime import datetime, timezone

from utils.logger import get_logger
from computer_use.image_capture import ImageCapture
from computer_use.vision_analyzer import VisionAnalyzer

log = get_logger("computer_use.chart_reader")


class ChartReader:
    """
    Day 47 Core — Visual Intelligence Layer।

    AI এখন দুই চোখে দেখবে:
      1. Quant চোখ: indicators, patterns (already built Day 1-46)
      2. Vision চোখ: chart image (Day 47)

    Usage:
        # TradingView browser-এর সাথে:
        from computer_use.tradingview_agent import TradingViewAgent
        tv = TradingViewAgent()
        tv.start()
        reader = ChartReader(tradingview_agent=tv)
        result = reader.capture_and_analyze("EURUSD", "M15")

        # Standalone (existing image):
        reader = ChartReader()
        result = reader.analyze_existing("chart.png", "EURUSD", "M15")

        # Full pipeline (vision + quant):
        fusion = reader.fuse_with_quant(vision_result, analysis_output)
    """

    def __init__(self, tradingview_agent=None):
        """
        tradingview_agent: TradingViewAgent instance (browser control-এর জন্য)
        None দিলে existing image analyze করা যাবে।
        """
        self.tv_agent = tradingview_agent
        self.capture = ImageCapture(
            page=tradingview_agent.controller.page if tradingview_agent else None
        )
        self.analyzer = VisionAnalyzer()

    # ═══════════════════════════════════════════════════════════
    # 1. MAIN: CAPTURE + ANALYZE
    # ═══════════════════════════════════════════════════════════

    def capture_and_analyze(
        self,
        symbol: str,
        timeframe: str,
        quant_ctx: dict = None,
        save_history: bool = True,
        trade_id: str = None,
    ) -> dict:
        """
        TradingView খুলে chart capture করো এবং Vision AI দিয়ে analyze করো।

        Flow:
            TradingView open → correct pair+TF → capture → vision AI → structured output

        Returns structured signal dict।
        """
        log.info(f"[ChartReader] Starting chart read: {symbol} {timeframe}")

        # Step 1: TradingView open + correct pair/TF
        if self.tv_agent:
            nav_ok = self._navigate_to_chart(symbol, timeframe)
            if not nav_ok:
                log.warning("[ChartReader] Navigation failed — trying capture anyway")
            time.sleep(2)   # chart render হতে দাও

        # Step 2: Chart capture
        capture_result = self.capture.capture_chart(symbol, timeframe)
        if not capture_result["success"]:
            return self._error_result(symbol, timeframe, "Chart capture failed")

        log.info(f"[ChartReader] Chart captured ✅ → {capture_result['path']}")

        # Step 3: Vision AI analysis
        if quant_ctx:
            vision_result = self.analyzer.analyze_with_context(
                image_path=capture_result["path"],
                symbol=symbol,
                timeframe=timeframe,
                current_price=quant_ctx.get("close", quant_ctx.get("price", 0)),
                rsi=quant_ctx.get("rsi"),
                macd=quant_ctx.get("macd_cross"),
                trend=quant_ctx.get("trend"),
                support=quant_ctx.get("nearest_support"),
                resistance=quant_ctx.get("nearest_resistance"),
            )
        else:
            vision_result = self.analyzer.analyze_image(capture_result["path"])

        # Step 4: History save
        if save_history:
            self.capture.save_to_history(symbol, timeframe, "before_trade", trade_id)

        # Step 5: Save to memory DB
        self.analyzer.save_to_memory(
            pair=symbol,
            timeframe=timeframe,
            image_path=capture_result["path"],
            vision_result=vision_result,
        )

        # Step 6: Build final result
        final = {
            "pair":           symbol,
            "timeframe":      timeframe,
            "capture":        capture_result,
            "vision":         vision_result,
            "vision_ctx":     self.analyzer.get_ai_context(vision_result),
            "timestamp":      datetime.now(timezone.utc).isoformat(),
        }

        self.print_summary(final)
        return final

    # ═══════════════════════════════════════════════════════════
    # 2. ANALYZE EXISTING IMAGE
    # ═══════════════════════════════════════════════════════════

    def analyze_existing(
        self,
        image_path: str,
        symbol: str,
        timeframe: str,
        quant_ctx: dict = None,
    ) -> dict:
        """
        Existing chart image analyze করো (browser automation ছাড়া)।
        Testing বা manual screenshot-এর জন্য।
        """
        if not os.path.exists(image_path):
            return self._error_result(symbol, timeframe, f"Image not found: {image_path}")

        log.info(f"[ChartReader] Analyzing existing image: {image_path}")

        if quant_ctx:
            vision_result = self.analyzer.analyze_with_context(
                image_path=image_path,
                symbol=symbol,
                timeframe=timeframe,
                current_price=quant_ctx.get("close", 0),
                rsi=quant_ctx.get("rsi"),
                macd=quant_ctx.get("macd_cross"),
                trend=quant_ctx.get("trend"),
                support=quant_ctx.get("nearest_support"),
                resistance=quant_ctx.get("nearest_resistance"),
            )
        else:
            vision_result = self.analyzer.analyze_image(image_path)

        self.analyzer.save_to_memory(symbol, timeframe, image_path, vision_result)

        return {
            "pair":       symbol,
            "timeframe":  timeframe,
            "capture":    {"path": image_path, "success": True},
            "vision":     vision_result,
            "vision_ctx": self.analyzer.get_ai_context(vision_result),
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        }

    # ═══════════════════════════════════════════════════════════
    # 3. MULTI-MODEL VERIFICATION
    # ═══════════════════════════════════════════════════════════

    def verify_with_multi_model(
        self,
        symbol: str,
        timeframe: str,
        quant_ctx: dict,
    ) -> dict:
        """
        Multi-model verification:
          Vision Model A + Vision Model B + Quant Engine → Consensus

        10/10 feature।
        """
        # Capture first
        capture_result = self.capture.capture_chart(symbol, timeframe)
        if not capture_result["success"]:
            return self._error_result(symbol, timeframe, "Capture failed")

        # Multi-model analysis
        multi_result = self.analyzer.multi_model_verify(
            image_path=capture_result["path"],
            quant_ctx=quant_ctx,
            symbol=symbol,
            timeframe=timeframe,
        )

        self.analyzer.print_summary(multi_result)

        return {
            "pair":       symbol,
            "timeframe":  timeframe,
            "capture":    capture_result,
            "multi":      multi_result,
            "vision_ctx": self.analyzer.get_ai_context(
                multi_result.get("model_b") or multi_result.get("model_a", {})
            ),
            "consensus":  multi_result.get("consensus", {}),
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        }

    # ═══════════════════════════════════════════════════════════
    # 4. QUANT + VISION FUSION  ⭐⭐⭐⭐⭐
    # ═══════════════════════════════════════════════════════════

    def fuse_with_quant(
        self,
        vision_result: dict,
        analysis_output: dict,
    ) -> dict:
        """
        Vision result + AnalysisAgent output → Fused signal।

        Priority logic:
          - Conflict আছে → confidence কমাও → WAIT prefer
          - Both agree → confidence বাড়াও
          - Vision strong pattern + Quant agree → high confidence

        Returns: final_signal, adjusted_confidence, fusion_notes
        """
        vision_ctx  = vision_result.get("vision_ctx", {})
        quant_sig   = analysis_output.get("final_signal", "NO TRADE")
        quant_conf  = analysis_output.get("signal", {}).get("confidence", 0)
        master_ctx  = analysis_output.get("master_ctx", {})

        vision_trend  = vision_ctx.get("vision_trend", "UNKNOWN")
        vision_conf   = vision_ctx.get("vision_confidence", 0)
        has_conflict  = vision_ctx.get("multi_model_conflict", False)

        # Conflict detection (vision vs quant)
        conflict_result = self.analyzer.detect_conflict(
            vision_result=vision_result.get("vision", {}),
            quant_ctx={
                "trend":  analysis_output.get("master_ctx", {}).get("master_signal", "WAIT"),
                "signal": quant_sig,
                "rsi":    analysis_output.get("df", None) and
                          analysis_output.get("ind_ctx", {}).get("rsi"),
            }
        )

        # Fusion logic
        fusion_notes = []
        adjusted_conf = quant_conf
        final_signal = quant_sig

        if conflict_result.get("has_conflict"):
            severity = conflict_result.get("conflict_severity", "LOW")
            adj = conflict_result.get("confidence_adjustment", -15)
            adjusted_conf = max(0, adjusted_conf + adj)
            fusion_notes.append(
                f"⚠️ Vision/Quant conflict ({severity}) — confidence adjusted {adj:+d}%"
            )
            if severity in ("HIGH", "MEDIUM") and adjusted_conf < 50:
                final_signal = "NO TRADE"
                fusion_notes.append("→ Signal changed to NO TRADE due to conflict")
        else:
            # Agreement bonus
            if vision_conf > 70 and quant_conf > 60:
                bonus = 8
                adjusted_conf = min(99, adjusted_conf + bonus)
                fusion_notes.append(f"✅ Vision/Quant agree → confidence +{bonus}%")

        # Pattern boost
        patterns = vision_ctx.get("vision_patterns", [])
        if patterns:
            fusion_notes.append(f"👁️ Vision patterns: {', '.join(patterns[:3])}")

        log.info(
            f"[ChartReader] Fusion | Quant: {quant_sig} ({quant_conf}%) | "
            f"Vision: {vision_trend} ({vision_conf}%) | "
            f"Conflict: {conflict_result.get('has_conflict')} | "
            f"Final: {final_signal} ({adjusted_conf}%)"
        )

        return {
            "final_signal":    final_signal,
            "adjusted_conf":   adjusted_conf,
            "original_conf":   quant_conf,
            "vision_trend":    vision_trend,
            "vision_conf":     vision_conf,
            "conflict":        conflict_result,
            "fusion_notes":    fusion_notes,
            "has_conflict":    conflict_result.get("has_conflict", False),
        }

    # ═══════════════════════════════════════════════════════════
    # 5. NAVIGATION HELPER
    # ═══════════════════════════════════════════════════════════

    def _navigate_to_chart(self, symbol: str, timeframe: str) -> bool:
        """TradingView-এ correct pair + timeframe navigate করো।"""
        try:
            result = self.tv_agent.execute_command({
                "action":    "OPEN_CHART",
                "pair":      symbol,
                "timeframe": timeframe,
            })
            return result.get("success", False)
        except Exception as e:
            log.error(f"[ChartReader] Navigation error: {e}")
            return False

    # ═══════════════════════════════════════════════════════════
    # UTILITIES
    # ═══════════════════════════════════════════════════════════

    def _error_result(self, symbol: str, timeframe: str, reason: str) -> dict:
        return {
            "pair":       symbol,
            "timeframe":  timeframe,
            "capture":    {"success": False},
            "vision":     {"error": reason, "trend": "UNKNOWN", "confidence": 0},
            "vision_ctx": {},
            "error":      reason,
            "timestamp":  datetime.now(timezone.utc).isoformat(),
        }

    def print_summary(self, result: dict) -> None:
        bar = "═" * 56
        vision = result.get("vision", {})
        vision_ctx = result.get("vision_ctx", {})

        trend_icon = {"BULLISH": "🟢", "BEARISH": "🔴", "SIDEWAYS": "🟡"}.get(
            vision.get("trend", ""), "⚪"
        )

        print(f"\n{bar}")
        print("  👁️   CHART READER  (Day 47)")
        print(bar)
        print(f"  Pair           : {result.get('pair')}")
        print(f"  Timeframe      : {result.get('timeframe')}")
        print()
        print(f"  ── Vision Analysis ──")
        print(f"  Trend          : {trend_icon} {vision.get('trend', 'UNKNOWN')}")
        print(f"  Strength       : {vision.get('trend_strength', '')}")
        print(f"  Momentum       : {vision.get('momentum', '')}")
        print(f"  Pattern        : {vision.get('pattern', [])}")
        print(f"  Condition      : {vision.get('market_condition', '')}")
        print()
        print(f"  ── Confidence ──")
        print(f"  Overall        : {vision.get('confidence', 0)}%")
        print(f"  Pattern        : {vision.get('pattern_confidence', 0)}%")
        print(f"  Trend          : {vision.get('trend_confidence', 0)}%")
        print(f"  Entry          : {vision.get('entry_confidence', 0)}%")
        if vision_ctx.get("vision_vs_quant"):
            print()
            print(f"  Vision vs Quant: {vision_ctx.get('vision_vs_quant')}")
        if vision.get("market_psychology"):
            print()
            print(f"  Psychology     : {vision.get('market_psychology', '')[:60]}")
        if result.get("error"):
            print(f"\n  ⚠️  Error: {result['error']}")
        print(bar + "\n")


# ═══════════════════════════════════════════════════════════════
# QUICK RUN — Direct test (existing image)
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    image_path = sys.argv[1] if len(sys.argv) > 1 else "test_chart.png"
    symbol     = sys.argv[2] if len(sys.argv) > 2 else "EURUSD"
    timeframe  = sys.argv[3] if len(sys.argv) > 3 else "M15"

    reader = ChartReader()

    if os.path.exists(image_path):
        print(f"\n📊 Analyzing: {image_path}")
        result = reader.analyze_existing(image_path, symbol, timeframe)
        reader.print_summary(result)
    else:
        print(f"❌ Image not found: {image_path}")
        print("Usage: python -m computer_use.chart_reader <image.png> <SYMBOL> <TIMEFRAME>")
        print("Example: python -m computer_use.chart_reader chart.png EURUSD M15")