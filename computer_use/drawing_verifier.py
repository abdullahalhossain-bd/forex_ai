# computer_use/drawing_verifier.py  —  Day 48 | Drawing Verification ⭐⭐⭐⭐⭐
# ============================================================
# Doc Section 7 — "AI click করলেই হবে না, আঁকা সত্যিই হলো কিনা চেক
# করতে হবে।"
#
# Two-tier verification (doc-এর Option 1 + Option 2 একসাথে):
#
#   Tier 1 — DOM Object Count (PRIMARY, fast, selector-independent)
#       TradingView প্রতিটা drawing object-কে internal "object tree"-তে
#       রাখে। Drawing করার আগে count নিয়ে, পরে আবার count নিয়ে compare
#       করলে নতুন object তৈরি হয়েছে কিনা বোঝা যায় — কোনো screenshot/OCR
#       লাগে না (tradingview_agent.verify_chart() এর মতোই philosophy)।
#
#   Tier 2 — Vision Confirmation (FALLBACK, doc-এর Option 1)
#       DOM count অনিশ্চিত/ব্যর্থ হলে Day 47-এর ImageCapture +
#       VisionAnalyzer reuse করে screenshot পাঠিয়ে Claude-কে directly
#       জিজ্ঞেস করা হয় "একটা horizontal line দেখা যাচ্ছে কিনা ~price-এ"।
#
# এই দুই tier মিলিয়ে "Drawing Confidence" score (bonus #3) ও বের করা
# হয় chart_drawer.py-তে।
# ============================================================

import time

from utils.logger import get_logger

log = get_logger("computer_use.drawing_verifier")

# TradingView-এর drawing objects সাধারণত এই ধরনের DOM node-এ থাকে
# (chart pane-এর overlay layer-এ আঁকা হয়)
DRAWING_OBJECT_SELECTORS = [
    '[data-name="legend-source-item"]',     # legend-এ drawing entries আসে
    '.pane-line-tool',
    '[class*="line-tool"]',
]


class DrawingVerifier:
    """
    Usage:
        verifier = DrawingVerifier(controller=browser_controller, mapper=coordinate_mapper)
        before = verifier.count_drawing_objects()
        # ... draw করো ...
        result = verifier.verify_drawing_added(before_count=before, expected_price=1.0850)
    """

    def __init__(self, controller, mapper=None, image_capture=None, vision_analyzer=None):
        """
        controller : Day 46 BrowserController
        mapper     : Day 48 CoordinateMapper (pixel→price reverse check-এর জন্য)
        image_capture / vision_analyzer : Day 47 modules — না দিলে lazy-init হবে
        """
        self.controller = controller
        self.page = controller.page
        self.mapper = mapper
        self._image_capture = image_capture
        self._vision_analyzer = vision_analyzer

    # ═══════════════════════════════════════════════════════
    # TIER 1 — DOM OBJECT COUNT
    # ═══════════════════════════════════════════════════════

    def count_drawing_objects(self) -> int:
        """বর্তমানে chart-এ কতগুলো drawing object আছে (legend/object-tree থেকে)।"""
        total = 0
        for sel in DRAWING_OBJECT_SELECTORS:
            try:
                total += self.page.locator(sel).count()
            except Exception:
                continue
        return total

    def verify_drawing_added(
        self,
        before_count: int,
        expected_price: float = None,
        timeout_seconds: float = 3.0,
    ) -> dict:
        """
        Drawing action-এর আগে নেওয়া count-এর সাথে এখনকার count compare
        করো। নতুন object detect হলে DOM-tier verification পাস।

        expected_price দিলে (এবং mapper available থাকলে) অতিরিক্তভাবে
        nearby drawn-line এর approx price reverse-calculate করার চেষ্টাও
        করা হয় (best-effort — TradingView legend থেকে exact price পড়া
        selector-নির্ভর ও ভঙ্গুর, তাই এটা soft-check, hard requirement না)।
        """
        deadline = time.time() + timeout_seconds
        after_count = before_count
        while time.time() < deadline:
            after_count = self.count_drawing_objects()
            if after_count > before_count:
                break
            time.sleep(0.3)

        added = after_count > before_count
        result = {
            "tier": "dom_object_count",
            "verified": added,
            "before_count": before_count,
            "after_count": after_count,
            "expected_price": expected_price,
        }
        icon = "✅" if added else "❓"
        log.info(
            f"[DrawingVerifier] {icon} DOM check | before={before_count} "
            f"after={after_count} verified={added}"
        )
        return result

    # ═══════════════════════════════════════════════════════
    # TIER 2 — VISION CONFIRMATION  (fallback, doc Option 1)
    # ═══════════════════════════════════════════════════════

    def verify_with_vision(
        self,
        symbol: str,
        timeframe: str,
        drawing_type: str,
        expected_price: float = None,
        expected_description: str = None,
    ) -> dict:
        """
        DOM-tier অনিশ্চিত হলে Day 47-এর Vision pipeline দিয়ে নিশ্চিত করো —
        screenshot নিয়ে Claude-কে সরাসরি জিজ্ঞেস করা "এই type-এর drawing
        chart-এ দেখা যাচ্ছে কিনা"।
        """
        capture = self._get_image_capture()
        analyzer = self._get_vision_analyzer()

        if not capture or not analyzer:
            return {
                "tier": "vision", "verified": None,
                "reason": "vision_modules_unavailable",
            }

        cap_result = capture.capture_chart(symbol, timeframe)
        if not cap_result.get("success"):
            return {"tier": "vision", "verified": None, "reason": "capture_failed"}

        question = self._build_verification_question(
            drawing_type, expected_price, expected_description
        )

        try:
            from computer_use.vision import VisionAgent
            quick = VisionAgent()
            vision_out = quick.analyze_chart(cap_result["path"], question=question)
            analysis_text = (vision_out.get("analysis") or "").strip()
        except Exception as e:
            log.warning(f"[DrawingVerifier] vision call error: {e}")
            return {"tier": "vision", "verified": None, "reason": str(e)}

        verified = self._interpret_vision_answer(analysis_text)
        result = {
            "tier": "vision",
            "verified": verified,
            "analysis": analysis_text,
            "image_path": cap_result.get("path"),
        }
        icon = "✅" if verified else ("❓" if verified is None else "❌")
        log.info(f"[DrawingVerifier] {icon} Vision check | {drawing_type} @ {expected_price}")
        return result

    def _build_verification_question(self, drawing_type, expected_price, expected_description) -> str:
        desc = expected_description or drawing_type
        price_hint = f" near price level {expected_price}" if expected_price else ""
        return (
            f"একটা {desc}{price_hint} TradingView chart-এ visible কিনা শুধু বলো। "
            f"উত্তর শুরু করো 'YES' অথবা 'NO' দিয়ে, তারপর এক লাইনে কারণ লেখো।"
        )

    def _interpret_vision_answer(self, text: str):
        upper = text.strip().upper()
        if upper.startswith("YES"):
            return True
        if upper.startswith("NO"):
            return False
        return None   # অস্পষ্ট উত্তর

    # ═══════════════════════════════════════════════════════
    # COMBINED VERIFICATION  (DOM first, vision fallback)
    # ═══════════════════════════════════════════════════════

    def verify(
        self,
        before_count: int,
        symbol: str = None,
        timeframe: str = None,
        drawing_type: str = "drawing",
        expected_price: float = None,
        use_vision_fallback: bool = True,
    ) -> dict:
        """
        Day 48 main entry point — chart_drawer.py এখান থেকেই কল করে।

        Flow:
            DOM check → verified দিলে done
                       → অনিশ্চিত/false হলে (এবং symbol/timeframe দেওয়া
                         থাকলে) Vision fallback চালাও
        """
        dom_result = self.verify_drawing_added(before_count, expected_price)

        if dom_result["verified"]:
            return {**dom_result, "final_verified": True, "method": "dom"}

        if use_vision_fallback and symbol and timeframe:
            vision_result = self.verify_with_vision(
                symbol, timeframe, drawing_type, expected_price
            )
            final = vision_result.get("verified")
            return {
                "dom": dom_result,
                "vision": vision_result,
                "final_verified": bool(final) if final is not None else False,
                "method": "vision_fallback",
            }

        return {**dom_result, "final_verified": False, "method": "dom_only"}

    # ═══════════════════════════════════════════════════════
    # LAZY INIT — Day 47 modules reuse
    # ═══════════════════════════════════════════════════════

    def _get_image_capture(self):
        if self._image_capture is None:
            try:
                from computer_use.image_capture import ImageCapture
                self._image_capture = ImageCapture(page=self.page)
            except Exception as e:
                log.warning(f"[DrawingVerifier] ImageCapture init failed: {e}")
                return None
        return self._image_capture

    def _get_vision_analyzer(self):
        if self._vision_analyzer is None:
            try:
                from computer_use.vision_analyzer import VisionAnalyzer
                self._vision_analyzer = VisionAnalyzer()
            except Exception as e:
                log.warning(f"[DrawingVerifier] VisionAnalyzer init failed: {e}")
                return None
        return self._vision_analyzer

    # ═══════════════════════════════════════════════════════
    # PRINT SUMMARY
    # ═══════════════════════════════════════════════════════

    def print_summary(self, result: dict) -> None:
        bar = "═" * 52
        print(f"\n{bar}")
        print("  🔍  DRAWING VERIFIER  (Day 48)")
        print(bar)
        print(f"  Final Verified : {'✅' if result.get('final_verified') else '❌'}")
        print(f"  Method         : {result.get('method')}")
        dom = result.get("dom", result if result.get("tier") == "dom_object_count" else None)
        if dom:
            print(f"  DOM Before/After: {dom.get('before_count')} → {dom.get('after_count')}")
        vision = result.get("vision")
        if vision:
            print(f"  Vision Verified : {vision.get('verified')}")
            if vision.get("analysis"):
                print(f"  Vision Note     : {vision['analysis'][:80]}")
        print(bar + "\n")