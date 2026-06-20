# computer_use/screen_detector.py  —  Day 50 | Screen Detector ⭐
# ============================================================
# Doc-এর Section 2 (Popup), 5 (Wrong Page), 6 (Screenshot Quality)
# একসাথে — এই তিনটাই "screen-এ কী আছে সেটা বোঝা" এই common category-তে
# পড়ে, তাই একটা module-এ রাখা হলো (StabilityManager পরের ফাইলে এগুলো
# orchestrate করবে)।
#
# ⚠️ TradingView নিয়মিত popup/cookie-banner DOM বদলায় (একই caveat যা
#    browser_controller.py/tradingview_agent.py-তেও আছে) — নিচের
#    selector list best-effort, না কাজ করলে Inspect Element দিয়ে আপডেট
#    করো।
# ============================================================

import time

from utils.logger import get_logger

log = get_logger("computer_use.screen_detector")

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except Exception as e:
    CV2_AVAILABLE = False
    log.warning(f"[ScreenDetector] opencv/numpy unavailable: {e}")

# ── Doc Section 2: Popup types — cookie / notification / update / error ──
POPUP_SELECTORS = [
    '[data-dialog-name="notice"]',
    '[class*="cookieConsent"]',
    '[class*="cookie-banner"]',
    '[data-name="popups-portal"] [role="dialog"]',
    '.tv-dialog',
    '[data-name="alert-dialog"]',
]

# প্রতিটা popup type-এর close button — popup ধরা পড়লে এগুলো ক্রমান্বয়ে try করা হয়
POPUP_CLOSE_SELECTORS = [
    '[data-name="close"]',
    'button[aria-label="Close"]',
    '.tv-dialog__close',
    '[class*="cookieConsent"] button',
]

# ── Doc Section 3: session expired indicator ──
# tradingview_agent.login() নিজেই login সফল হলে এই selector চেক করে —
# তাই "session expired" মানে এই selector এখন আর নেই
LOGGED_IN_SELECTOR = '[data-name="header-user-menu-button"]'


class ScreenDetector:
    """
    Usage:
        detector = ScreenDetector(controller=browser_controller)
        if detector.has_popup():
            detector.close_popup()
        if detector.is_logged_out():
            ...
        if not detector.is_correct_page(expected_symbol="EURUSD"):
            ...
        quality = detector.check_screenshot_quality(image_path)
    """

    BLUR_VARIANCE_THRESHOLD = 50    # doc-এর "quality < 50" সরাসরি reuse
    DARK_BRIGHTNESS_THRESHOLD = 25  # mean pixel brightness এর নিচে গেলে "dark screen"

    def __init__(self, controller):
        """controller: Day 46 BrowserController"""
        self.controller = controller
        self.page = controller.page

    # ═══════════════════════════════════════════════════════
    # 1. POPUP DETECTION + CLOSE  (doc Section 2)
    # ═══════════════════════════════════════════════════════

    def has_popup(self) -> bool:
        for sel in POPUP_SELECTORS:
            try:
                if self.page.locator(sel).first.is_visible(timeout=800):
                    log.info(f"[ScreenDetector] Popup detected via '{sel}'")
                    return True
            except Exception:
                continue
        return False

    def close_popup(self, retries: int = 2) -> bool:
        """
        Popup বন্ধ করার চেষ্টা — প্রথমে close button selector, fail করলে
        Escape key (doc-এর কোনো method না, কিন্তু TradingView dialog
        সাধারণত Escape-এও বন্ধ হয়, একটা সহজ fallback)।
        """
        for attempt in range(1, retries + 1):
            for sel in POPUP_CLOSE_SELECTORS:
                try:
                    el = self.page.locator(sel).first
                    if el.is_visible(timeout=800):
                        el.click()
                        time.sleep(1)
                        if not self.has_popup():
                            log.info(f"[ScreenDetector] Popup closed via '{sel}' ✅")
                            return True
                except Exception:
                    continue

            # Fallback — Escape key
            try:
                self.page.keyboard.press("Escape")
                time.sleep(1)
            except Exception:
                pass

            if not self.has_popup():
                log.info("[ScreenDetector] Popup closed via Escape fallback ✅")
                return True

        log.warning(f"[ScreenDetector] Popup close failed after {retries} attempts")
        return False

    # ═══════════════════════════════════════════════════════
    # 2. SESSION / LOGIN CHECK  (doc Section 3 — "session expired" detector;
    #    actual re-login tradingview_agent.login()-এ করা আছে, এখানে শুধু চেক)
    # ═══════════════════════════════════════════════════════

    def is_logged_out(self, timeout: int = 2000) -> bool:
        """
        True হলে মানে user-menu button নেই — session expired/logged out।
        tradingview_agent.login() নিজেই সফল হলে এই একই selector চেক করে,
        তাই এখানে শুধু "আগে থেকেই logged in" নিশ্চিত হওয়া হচ্ছে।
        """
        try:
            logged_in = self.page.locator(LOGGED_IN_SELECTOR).first.is_visible(timeout=timeout)
            return not logged_in
        except Exception:
            return True   # selector খুঁজেই না পেলে নিরাপদ assumption: logged out

    # ═══════════════════════════════════════════════════════
    # 3. PAGE IDENTITY CHECK  (doc Section 5 — wrong page detection)
    # ═══════════════════════════════════════════════════════

    def is_correct_page(self, expected_symbol: str) -> bool:
        """
        tradingview_agent.get_current_symbol() এর মতোই browser tab
        <title>-এর উপর নির্ভর করে (selector-independent, সবচেয়ে reliable)।
        """
        title = self.controller.current_title()
        expected = expected_symbol.upper().replace("/", "")
        return expected in title.upper()

    # ═══════════════════════════════════════════════════════
    # 4. CHART LOADED CHECK  (doc Section 4-এর সহায়ক — chart_drawer.py-র
    #    coordinate_mapper.CHART_CONTAINER_SELECTORS এর সাথে consistent)
    # ═══════════════════════════════════════════════════════

    def is_chart_loaded(self, timeout: int = 3000) -> bool:
        from computer_use.coordinate_mapper import CHART_CONTAINER_SELECTORS
        for sel in CHART_CONTAINER_SELECTORS:
            try:
                el = self.page.locator(sel).first
                if el.is_visible(timeout=timeout):
                    box = el.bounding_box()
                    if box and box["width"] > 100 and box["height"] > 100:
                        return True
            except Exception:
                continue
        return False

    # ═══════════════════════════════════════════════════════
    # 5. SCREENSHOT QUALITY  (doc Section 6 — Laplacian variance)
    # ═══════════════════════════════════════════════════════

    def check_screenshot_quality(self, image_path: str) -> dict:
        """
        doc-এর calculate_quality() এর সরাসরি বাস্তবায়ন — Laplacian
        variance দিয়ে blur measure করা, plus brightness check (doc-এ
        "dark screen" mention আছে কিন্তু আলাদা formula দেওয়া নেই, তাই
        সেটাও যোগ করা হলো একই function-এ)।

        Returns:
            { "ok": bool, "blur_variance": float, "brightness": float,
              "reason": str|None }
        """
        if not CV2_AVAILABLE:
            return {"ok": True, "blur_variance": None, "brightness": None,
                    "reason": "opencv unavailable — quality check skipped"}

        img = cv2.imread(image_path)
        if img is None:
            return {"ok": False, "blur_variance": 0, "brightness": 0,
                     "reason": f"Could not read image: {image_path}"}

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        brightness = float(np.mean(gray))

        if variance < self.BLUR_VARIANCE_THRESHOLD:
            return {"ok": False, "blur_variance": round(variance, 1),
                    "brightness": round(brightness, 1), "reason": "Image too blurry"}

        if brightness < self.DARK_BRIGHTNESS_THRESHOLD:
            return {"ok": False, "blur_variance": round(variance, 1),
                    "brightness": round(brightness, 1), "reason": "Screen too dark"}

        return {"ok": True, "blur_variance": round(variance, 1),
                "brightness": round(brightness, 1), "reason": None}