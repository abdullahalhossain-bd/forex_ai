# computer_use/image_capture.py  —  Day 47 | Chart Image Capture Engine
# ============================================================
# TradingView chart screenshot নিয়ে Vision Model-এ পাঠানোর জন্য।
#
# Features:
#   ✅ Browser automation থেকে chart capture (Playwright)
#   ✅ Chart area crop (indicator/toolbar বাদ দিয়ে)
#   ✅ Screenshot history save (before/during/after trade)
#   ✅ Base64 encode (Vision API-র জন্য)
#   ✅ Fallback: pyautogui screen capture
# ============================================================

import base64
import os
import time
from datetime import datetime, timezone

from utils.logger import get_logger

log = get_logger("computer_use.image_capture")

SCREENSHOT_DIR = "computer_use/charts"
HISTORY_DIR = "computer_use/chart_history"


class ImageCapture:
    """
    TradingView chart screenshot capture করে।

    Usage:
        capture = ImageCapture(page=playwright_page)
        result = capture.capture_chart("EURUSD", "M15")
        # result["path"] → saved file path
        # result["base64"] → base64 encoded image
    """

    def __init__(self, page=None):
        """
        page: Playwright page object (tradingview_agent থেকে pass করো)
        page না দিলে pyautogui fallback ব্যবহার হবে।
        """
        self.page = page
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        os.makedirs(HISTORY_DIR, exist_ok=True)

    # ═══════════════════════════════════════════════════════════
    # MAIN: CAPTURE CHART
    # ═══════════════════════════════════════════════════════════

    def capture_chart(
        self,
        symbol: str,
        timeframe: str,
        save_path: str = None,
        crop_chart_only: bool = True,
    ) -> dict:
        """
        TradingView chart screenshot নাও।

        Returns:
            {
                "success": bool,
                "path": str,
                "base64": str,
                "symbol": str,
                "timeframe": str,
                "timestamp": str,
                "size": (width, height)
            }
        """
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{symbol}_{timeframe}_{ts}.png"
        path = save_path or os.path.join(SCREENSHOT_DIR, filename)

        log.info(f"[ImageCapture] Capturing chart: {symbol} {timeframe}")

        # Playwright দিয়ে capture করো (preferred)
        if self.page:
            success = self._capture_playwright(path, crop_chart_only)
        else:
            success = self._capture_pyautogui(path)

        if not success:
            return {
                "success": False,
                "path": None,
                "base64": None,
                "symbol": symbol,
                "timeframe": timeframe,
                "error": "Screenshot capture failed",
            }

        # Base64 encode
        b64 = self._to_base64(path)
        size = self._get_image_size(path)

        log.info(f"[ImageCapture] Chart captured ✅ → {path}  size={size}")

        return {
            "success": True,
            "path": path,
            "base64": b64,
            "symbol": symbol,
            "timeframe": timeframe,
            "timestamp": ts,
            "size": size,
            "filename": filename,
        }

    # ═══════════════════════════════════════════════════════════
    # PLAYWRIGHT CAPTURE
    # ═══════════════════════════════════════════════════════════

    def _capture_playwright(self, path: str, crop_chart_only: bool = True) -> bool:
        """Playwright page দিয়ে screenshot নাও।"""
        try:
            if crop_chart_only:
                # Chart area খোঁজো (toolbar/sidebar বাদ দিয়ে)
                chart_area = self._find_chart_element()
                if chart_area:
                    chart_area.screenshot(path=path)
                    return True

            # Fallback: full page screenshot
            self.page.screenshot(path=path, full_page=False)
            return True

        except Exception as e:
            log.error(f"[ImageCapture] Playwright capture error: {e}")
            return False

    def _find_chart_element(self):
        """TradingView-এর chart canvas element খোঁজো।"""
        selectors = [
            ".chart-container",
            "[data-name='pane-widget-renderer']",
            ".chart-gui-wrapper",
            "canvas.pane-canvas",
        ]
        for sel in selectors:
            try:
                el = self.page.locator(sel).first
                if el.is_visible(timeout=2000):
                    return el
            except Exception:
                continue
        return None

    # ═══════════════════════════════════════════════════════════
    # PYAUTOGUI FALLBACK
    # ═══════════════════════════════════════════════════════════

    def _capture_pyautogui(self, path: str) -> bool:
        """pyautogui দিয়ে full screen capture।"""
        try:
            import pyautogui
            img = pyautogui.screenshot()
            img.save(path)
            return True
        except ImportError:
            log.warning("[ImageCapture] pyautogui not installed — cannot capture")
            return False
        except Exception as e:
            log.error(f"[ImageCapture] pyautogui capture error: {e}")
            return False

    # ═══════════════════════════════════════════════════════════
    # SCREENSHOT HISTORY  ⭐⭐⭐⭐⭐
    # ═══════════════════════════════════════════════════════════

    def save_to_history(
        self,
        symbol: str,
        timeframe: str,
        stage: str,   # "before_trade" | "during_trade" | "after_trade"
        trade_id: str = None,
    ) -> dict:
        """
        Trade-এর আগে/মধ্যে/পরে chart save করো।
        AI পরে শিখবে: এই ধরনের chart আগে কী হয়েছিল।

        stage: "before_trade", "during_trade", "after_trade"
        """
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        trade_prefix = f"{trade_id}_" if trade_id else ""
        filename = f"{trade_prefix}{symbol}_{timeframe}_{stage}_{ts}.png"
        path = os.path.join(HISTORY_DIR, filename)

        result = self.capture_chart(symbol, timeframe, save_path=path)
        if result["success"]:
            log.info(f"[ImageCapture] History saved: {stage} → {filename}")

        return {**result, "stage": stage, "trade_id": trade_id}

    # ═══════════════════════════════════════════════════════════
    # UTILITIES
    # ═══════════════════════════════════════════════════════════

    def _to_base64(self, path: str) -> str:
        """Image file → base64 string (Vision API-র জন্য)।"""
        try:
            with open(path, "rb") as f:
                return base64.standard_b64encode(f.read()).decode("utf-8")
        except Exception as e:
            log.error(f"[ImageCapture] Base64 encode error: {e}")
            return ""

    def _get_image_size(self, path: str) -> tuple:
        """Image-এর (width, height) বের করো।"""
        try:
            from PIL import Image
            with Image.open(path) as img:
                return img.size
        except Exception:
            return (0, 0)

    def set_page(self, page) -> None:
        """Playwright page পরে set করার জন্য।"""
        self.page = page
        log.info("[ImageCapture] Playwright page set ✅")

    def list_history(self, symbol: str = None, limit: int = 20) -> list:
        """Saved chart history list করো।"""
        files = []
        for f in os.listdir(HISTORY_DIR):
            if f.endswith(".png"):
                if symbol is None or symbol in f:
                    files.append(f)
        files.sort(reverse=True)
        return files[:limit]

    def print_summary(self, result: dict) -> None:
        bar = "═" * 52
        print(f"\n{bar}")
        print("  📸  IMAGE CAPTURE  (Day 47)")
        print(bar)
        print(f"  Symbol     : {result.get('symbol')}")
        print(f"  Timeframe  : {result.get('timeframe')}")
        print(f"  Success    : {'✅' if result.get('success') else '❌'}")
        if result.get("path"):
            print(f"  Saved to   : {result['path']}")
        if result.get("size"):
            print(f"  Size       : {result['size'][0]}×{result['size'][1]} px")
        if result.get("stage"):
            print(f"  Stage      : {result['stage']}")
        if result.get("error"):
            print(f"  Error      : {result['error']}")
        print(bar + "\n")