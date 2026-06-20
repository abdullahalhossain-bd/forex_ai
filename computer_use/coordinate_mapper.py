# computer_use/coordinate_mapper.py  —  Day 48 | Coordinate Mapping Engine ⭐⭐⭐⭐⭐
# ============================================================
# Day 48-এর সবচেয়ে গুরুত্বপূর্ণ ও সবচেয়ে ঝুঁকিপূর্ণ অংশ:
#
#       Price  ←──────────────→  Screen Pixel
#
# AI জানে price (1.0850, 1.1000 ইত্যাদি) — কিন্তু mouse তো price বোঝে
# না, মাউস বোঝে pixel (x, y)। এই ফাইল সেই translation layer।
#
# Formula (doc অনুযায়ী):
#       screen_y = chart_top +
#                  ((max_price - current_price) / price_range) * chart_height
#
# Time axis-এর জন্যও একই ধরনের linear mapping, কারণ TradingView-এর
# candle-spacing প্রায় uniform (zoom/scroll না হলে)।
#
# Day 46 (browser_controller.py / TradingViewAgent) এর উপর বসে এই
# module কাজ করে — chart canvas-এর bounding_box() ও price-scale label
# text Playwright দিয়ে পড়ে।
#
# ⚠️ TradingView frontend selector বদলালে এখানের selector list-টা
#    আপডেট করতে হবে (একই caveat যা tradingview_agent.py-তেও আছে)।
# ============================================================

import re
import time
from datetime import datetime, timezone

from utils.logger import get_logger

log = get_logger("computer_use.coordinate_mapper")

# Chart canvas element বের করার জন্য — image_capture.py-এর সাথে consistent selector list
CHART_CONTAINER_SELECTORS = [
    ".chart-container",
    "[data-name='pane-widget-renderer']",
    ".chart-gui-wrapper",
    "canvas.pane-canvas",
]

# Price scale label-গুলো যেখানে থাকে (ডান পাশে, Y axis)
PRICE_SCALE_SELECTORS = [
    '[class*="priceScale"] [class*="labelRow"]',
    '[data-name="price-axis"] text',
    '.price-axis-container text',
]

# Time scale label-গুলো (নিচে, X axis)
TIME_SCALE_SELECTORS = [
    '[class*="timeScale"] [class*="label"]',
    '[data-name="time-axis"] text',
]


class CoordinateMapper:
    """
    Day 48 Core — Price ↔ Pixel translation layer।

    Usage:
        mapper = CoordinateMapper(controller=browser_controller)
        cal = mapper.calibrate()
        if cal["success"]:
            x, y = mapper.price_to_pixel(1.0850)
            price = mapper.pixel_to_price(y)
    """

    def __init__(self, controller=None, page=None):
        """
        controller: Day 46 BrowserController instance (preferred)
        page:       সরাসরি Playwright page (controller না দিলে)
        """
        self.controller = controller
        self.page = page or (controller.page if controller else None)

        # Calibration state — calibrate() call করার পর fill হবে
        self.chart_area: dict = {}      # {x, y, width, height}
        self.price_min: float = None
        self.price_max: float = None
        self.time_min = None
        self.time_max = None
        self.candle_count: int = 0
        self.calibrated_at: str = None
        self.is_calibrated: bool = False

    # ═══════════════════════════════════════════════════════
    # 1. CHART AREA DETECTION
    # ═══════════════════════════════════════════════════════

    def detect_chart_area(self) -> dict:
        """
        Chart canvas-এর bounding box বের করো (toolbar/sidebar বাদ দিয়ে)।
        image_capture.py-এর _find_chart_element() এর মতোই selector list।
        """
        if not self.page:
            return {}

        for sel in CHART_CONTAINER_SELECTORS:
            try:
                el = self.page.locator(sel).first
                if el.is_visible(timeout=2000):
                    box = el.bounding_box()
                    if box and box["width"] > 100 and box["height"] > 100:
                        log.info(f"[CoordinateMapper] Chart area found via '{sel}' → {box}")
                        return box
            except Exception:
                continue

        log.warning("[CoordinateMapper] Chart area not found with any selector")
        return {}

    # ═══════════════════════════════════════════════════════
    # 2. PRICE SCALE DETECTION  ⭐⭐⭐⭐⭐
    # ═══════════════════════════════════════════════════════

    def detect_price_scale(self) -> tuple:
        """
        ডানদিকের price-axis label পড়ে chart-এর visible price range
        (min, max) বের করো। chart_agent.py-এর _get_chart_price_range()
        এর উন্নত version — একাধিক selector + sanity-check সহ।

        Returns: (price_min, price_max) অথবা (None, None) যদি না পাওয়া যায়
        """
        if not self.page:
            return None, None

        for sel in PRICE_SCALE_SELECTORS:
            try:
                labels = self.page.locator(sel).all_text_contents()
            except Exception:
                continue

            prices = []
            for label in labels:
                cleaned = re.sub(r"[^\d.\-]", "", label.replace(",", ""))
                try:
                    if cleaned:
                        prices.append(float(cleaned))
                except ValueError:
                    continue

            # কমপক্ষে ৩টা valid number পেলেই reliable ধরা হবে
            if len(prices) >= 3:
                prices = sorted(set(prices))
                price_min, price_max = prices[0], prices[-1]
                # Sanity check: spread খুব ছোট/বড় না হওয়া উচিত
                if price_max > price_min and (price_max - price_min) < price_min:
                    log.info(
                        f"[CoordinateMapper] Price scale detected via '{sel}': "
                        f"{price_min} → {price_max}"
                    )
                    return price_min, price_max

        log.warning("[CoordinateMapper] Price scale not detected from DOM")
        return None, None

    # ═══════════════════════════════════════════════════════
    # 3. TIME SCALE DETECTION
    # ═══════════════════════════════════════════════════════

    def detect_time_scale(self) -> tuple:
        """
        নিচের time-axis label পড়ে visible candle/time range আন্দাজ করো।
        Trend-line ও Fibonacci drawing-এর জন্য X-coordinate দরকার হলে
        কাজে লাগে। Exact timestamp resolve করা কঠিন (TradingView label
        sparse দেখায়) — তাই এখানে শুধু label count থেকে approximate
        "kতা candle visible" বের করা হয়, আর X mapping linear ধরা হয়।
        """
        if not self.page:
            return 0, 0

        for sel in TIME_SCALE_SELECTORS:
            try:
                labels = self.page.locator(sel).all_text_contents()
                labels = [l for l in labels if l.strip()]
                if len(labels) >= 2:
                    log.info(
                        f"[CoordinateMapper] Time scale detected via '{sel}': "
                        f"{len(labels)} labels visible"
                    )
                    return 0, len(labels)
            except Exception:
                continue

        log.warning("[CoordinateMapper] Time scale not detected — using chart width fallback")
        return 0, 0

    # ═══════════════════════════════════════════════════════
    # 4. FULL CALIBRATION  ⭐⭐⭐⭐⭐
    # ═══════════════════════════════════════════════════════

    def calibrate(self, fallback_price: float = None, fallback_spread_pct: float = 0.005) -> dict:
        """
        Chart area + price scale + time scale — সব একসাথে detect করো।
        Drawing শুরু করার আগে এটা অবশ্যই call করতে হবে।

        fallback_price: price scale detect না হলে (current_price ± spread%)
                        দিয়ে fallback range বানানোর জন্য (chart_agent.py-এর
                        মতো একই fallback strategy)।

        Returns:
            {
                "success": bool,
                "price_to_pixel": bool,
                "chart_area": {...},
                "price_range": [min, max],
                "method": "dom_detected" | "fallback",
            }
        """
        self.chart_area = self.detect_chart_area()
        if not self.chart_area:
            log.error("[CoordinateMapper] Calibration FAILED — chart area not found")
            self.is_calibrated = False
            return {
                "success": False, "price_to_pixel": False,
                "chart_area": {}, "price_range": [None, None],
                "method": None, "reason": "chart_area_not_found",
            }

        price_min, price_max = self.detect_price_scale()
        method = "dom_detected"

        if price_min is None or price_max is None:
            if fallback_price:
                price_min = fallback_price * (1 - fallback_spread_pct)
                price_max = fallback_price * (1 + fallback_spread_pct)
                method = "fallback"
                log.warning(
                    f"[CoordinateMapper] Using fallback price range "
                    f"({price_min:.5f} → {price_max:.5f})"
                )
            else:
                log.error("[CoordinateMapper] Calibration FAILED — no price scale & no fallback")
                self.is_calibrated = False
                return {
                    "success": False, "price_to_pixel": False,
                    "chart_area": self.chart_area, "price_range": [None, None],
                    "method": None, "reason": "price_scale_not_found",
                }

        time_min, candle_count = self.detect_time_scale()

        self.price_min = price_min
        self.price_max = price_max
        self.time_min = time_min
        self.candle_count = candle_count
        self.calibrated_at = datetime.now(timezone.utc).isoformat()
        self.is_calibrated = True

        result = {
            "success": True,
            "price_to_pixel": True,
            "chart_area": self.chart_area,
            "price_range": [price_min, price_max],
            "method": method,
            "calibrated_at": self.calibrated_at,
        }
        log.info(
            f"[CoordinateMapper] Calibration OK ✅ | area={self.chart_area} | "
            f"price=[{price_min:.5f}, {price_max:.5f}] | method={method}"
        )
        return result

    def recalibrate_if_stale(self, max_age_seconds: int = 30, fallback_price: float = None) -> dict:
        """
        Chart move/scroll/zoom হলে আগের calibration ভুল হয়ে যেতে পারে।
        একটা নির্দিষ্ট সময় পার হয়ে গেলে auto re-calibrate করো (Mistake
        Recovery flow-এর "Chart move হলে → Recalculate" অংশ)।
        """
        if not self.is_calibrated or not self.calibrated_at:
            return self.calibrate(fallback_price=fallback_price)

        try:
            age = (
                datetime.now(timezone.utc)
                - datetime.fromisoformat(self.calibrated_at)
            ).total_seconds()
        except Exception:
            age = max_age_seconds + 1

        if age > max_age_seconds:
            log.info(f"[CoordinateMapper] Calibration stale ({age:.0f}s) — recalibrating")
            return self.calibrate(fallback_price=fallback_price)

        return {
            "success": True, "price_to_pixel": True,
            "chart_area": self.chart_area, "price_range": [self.price_min, self.price_max],
            "method": "cached",
        }

    # ═══════════════════════════════════════════════════════
    # 5. PRICE → PIXEL  ⭐⭐⭐⭐⭐  (the core formula)
    # ═══════════════════════════════════════════════════════

    def price_to_y(self, price: float) -> float:
        """
        Doc formula:
            screen_y = chart_top +
                       ((max_price - current_price) / price_range) * chart_height
        """
        if not self.is_calibrated:
            raise RuntimeError("CoordinateMapper not calibrated — call calibrate() first")

        price_range = self.price_max - self.price_min
        if price_range <= 0:
            raise ValueError("Invalid price range — price_max <= price_min")

        ratio = (self.price_max - price) / price_range
        # Chart edge-এ exactly ক্লিক করলে toolbar/scale-এর সাথে ওভারল্যাপ
        # হতে পারে, তাই ৩%-৯৭% এর মধ্যে clamp করা (chart_agent.py-এর
        # _price_to_y() এর সাথে consistent margin)
        ratio = max(0.03, min(0.97, ratio))

        return self.chart_area["y"] + ratio * self.chart_area["height"]

    def price_to_pixel(self, price: float, x: float = None) -> tuple:
        """
        Price → (x, y) pixel। x না দিলে chart-এর horizontal center ব্যবহার
        হবে (horizontal line drawing-এর জন্য যথেষ্ট — TradingView
        horizontal line tool ক্লিক করা x যেকোনো জায়গায় হলেও পুরো width
        জুড়ে line টেনে দেয়)।
        """
        y = self.price_to_y(price)
        if x is None:
            x = self.chart_area["x"] + self.chart_area["width"] * 0.5
        return (round(x, 1), round(y, 1))

    # ═══════════════════════════════════════════════════════
    # 6. PIXEL → PRICE  (reverse mapping — verification-এর জন্য দরকার)
    # ═══════════════════════════════════════════════════════

    def pixel_to_price(self, y: float) -> float:
        """Reverse formula — drawing verify করার সময় pixel থেকে price বের করতে।"""
        if not self.is_calibrated:
            raise RuntimeError("CoordinateMapper not calibrated — call calibrate() first")

        ratio = (y - self.chart_area["y"]) / self.chart_area["height"]
        ratio = max(0.0, min(1.0, ratio))
        price = self.price_max - ratio * (self.price_max - self.price_min)
        return round(price, 5)

    # ═══════════════════════════════════════════════════════
    # 7. TIME/CANDLE → X  (trend line ও fib-এর দুই প্রান্তের জন্য)
    # ═══════════════════════════════════════════════════════

    def candle_index_to_x(self, candles_back_from_right: int) -> float:
        """
        Doc flow: candle/time → pixel coordinate।

        TradingView-তে সাধারণত সবচেয়ে ডানের candle = সবচেয়ে recent।
        candles_back_from_right=0 মানে সবচেয়ে ডানের candle, 10 মানে
        তার ১০টা আগের candle — ইত্যাদি। candle_count জানা থাকলে সেটা
        দিয়ে spacing বের করা হয়, না জানলে chart width-এর উপর reasonable
        default (≈50 visible candle) ধরে নেওয়া হয়।
        """
        if not self.chart_area:
            raise RuntimeError("CoordinateMapper not calibrated — call calibrate() first")

        visible_candles = self.candle_count if self.candle_count >= 5 else 50
        spacing = self.chart_area["width"] / visible_candles

        x = self.chart_area["x"] + self.chart_area["width"] - (candles_back_from_right * spacing)
        # Chart-এর বাইরে চলে গেলে edge-এ clamp করো
        x = max(self.chart_area["x"] + 5, min(self.chart_area["x"] + self.chart_area["width"] - 5, x))
        return round(x, 1)

    # ═══════════════════════════════════════════════════════
    # UTIL / DEBUG
    # ═══════════════════════════════════════════════════════

    def get_calibration_summary(self) -> dict:
        return {
            "is_calibrated":  self.is_calibrated,
            "chart_area":     self.chart_area,
            "price_min":      self.price_min,
            "price_max":      self.price_max,
            "candle_count":   self.candle_count,
            "calibrated_at":  self.calibrated_at,
        }

    def print_summary(self, result: dict = None) -> None:
        bar = "═" * 54
        print(f"\n{bar}")
        print("  📐  COORDINATE MAPPER  (Day 48)")
        print(bar)
        result = result or self.get_calibration_summary()
        print(f"  Calibrated     : {'✅' if result.get('success', self.is_calibrated) else '❌'}")
        area = result.get("chart_area", self.chart_area)
        if area:
            print(f"  Chart Area     : x={area.get('x')} y={area.get('y')} "
                  f"w={area.get('width')} h={area.get('height')}")
        prange = result.get("price_range", [self.price_min, self.price_max])
        if prange and prange[0] is not None:
            print(f"  Price Range    : {prange[0]:.5f} → {prange[1]:.5f}")
        if result.get("method"):
            print(f"  Method         : {result['method']}")
        print(bar + "\n")