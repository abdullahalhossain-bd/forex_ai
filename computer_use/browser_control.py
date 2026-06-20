# computer_use/browser_control.py  —  Day 45 | Browser Automation (Computer Use Layer)
# ============================================================
# AI যেন মানুষের মতো ব্রাউজার খুলে TradingView browse করতে পারে,
# symbol/timeframe পাল্টাতে পারে — Playwright দিয়ে।
#
# screen_controller.py (pyautogui) পুরো OS desktop control করে, কিন্তু
# browser-এর ভেতরের element খোঁজার জন্য CSS selector অনেক বেশি
# reliable। তাই browser-based কাজের জন্য আলাদাভাবে Playwright ব্যবহার
# করা হলো — element selector fail করলে computer_use/vision.py-এর
# OCR দিয়ে action verify করা যায়।
#
# Requirements:
#   pip install playwright
#   playwright install chromium
# ============================================================

import os
import time
from datetime import datetime, timezone

from utils.logger import get_logger
from computer_use.safety import SafetyLayer

log = get_logger("computer_use.browser")

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except Exception as e:
    PLAYWRIGHT_AVAILABLE = False
    log.warning(f"[BrowserAgent] playwright unavailable: {e}")


class BrowserAgent:
    """
    Computer Use Layer-এর browser hand। Generic navigation + retry/error
    handling + safety check + TradingView-specific helper methods।

    Usage:
        agent = BrowserAgent(safety=SafetyLayer())
        result = agent.run_tradingview_test("EURUSD", "15")
        agent.close()
    """

    def __init__(self, safety: SafetyLayer = None, headless: bool = False,
                 error_dir: str = "computer_use/errors"):
        self.safety = safety
        self.headless = headless
        self.error_dir = error_dir
        self.playwright = None
        self.browser = None
        self.page = None
        os.makedirs(self.error_dir, exist_ok=True)

    # ═══════════════════════════════════════════════════════
    # LIFECYCLE
    # ═══════════════════════════════════════════════════════

    def start(self) -> bool:
        if not PLAYWRIGHT_AVAILABLE:
            log.error("[BrowserAgent] Playwright not installed")
            return False
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(
            headless=self.headless, args=["--start-maximized"]
        )
        self.page = self.browser.new_page(viewport={"width": 1600, "height": 900})
        log.info("[BrowserAgent] Browser started ✅")
        return True

    def close(self) -> None:
        try:
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
            log.info("[BrowserAgent] Browser closed 🔴")
        except Exception as e:
            log.warning(f"[BrowserAgent] close() error: {e}")

    # ═══════════════════════════════════════════════════════
    # GENERIC NAVIGATION  (with retry + error handling)
    # ═══════════════════════════════════════════════════════

    def goto(self, url: str, retries: int = 2, wait_after: float = 3.0) -> bool:
        for attempt in range(1, retries + 2):
            try:
                self.page.goto(url, wait_until="domcontentloaded", timeout=20000)
                time.sleep(wait_after)
                log.info(f"[BrowserAgent] Navigated -> {url}")
                return True
            except Exception as e:
                log.warning(f"[BrowserAgent] goto failed (attempt {attempt}): {e}")
                time.sleep(1.5)
        self._save_error("goto_failed")
        return False

    def click_selector(self, selector: str, retries: int = 2, timeout: int = 5000,
                       safety_context: dict = None) -> bool:
        """CSS/role selector দিয়ে click করো — retry ও safety check সহ।"""
        if not self._safety_approved("CLICK", safety_context):
            return False
        for attempt in range(1, retries + 2):
            try:
                el = self.page.locator(selector).first
                el.wait_for(timeout=timeout)
                el.click()
                log.info(f"[BrowserAgent] Clicked: {selector}")
                return True
            except Exception as e:
                log.warning(f"[BrowserAgent] click failed '{selector}' (attempt {attempt}): {e}")
                time.sleep(1)
        self._save_error(f"click_failed_{selector[:20]}")
        return False

    # ═══════════════════════════════════════════════════════
    # TRADINGVIEW HELPERS
    # ═══════════════════════════════════════════════════════

    def open_tradingview(self, symbol: str = "EURUSD") -> bool:
        url = f"https://www.tradingview.com/chart/?symbol=FX:{symbol}"
        ok = self.goto(url, wait_after=7.0)
        if ok:
            self.page.keyboard.press("Escape")
            time.sleep(1)
            log.info(f"[BrowserAgent] TradingView loaded ✅ ({symbol})")
        return ok

    def search_symbol(self, symbol: str) -> bool:
        """'/' shortcut দিয়ে symbol search box খুলে নতুন symbol লোড করো।"""
        try:
            self.page.keyboard.press("/")
            time.sleep(1)
            self.page.keyboard.type(symbol, delay=80)
            time.sleep(1.5)
            self.page.keyboard.press("Enter")
            time.sleep(2)
            log.info(f"[BrowserAgent] Symbol searched: {symbol}")
            return True
        except Exception as e:
            log.warning(f"[BrowserAgent] search_symbol failed: {e}")
            self._save_error("search_symbol_failed")
            return False

    def change_timeframe(self, timeframe: str = "15") -> bool:
        """TradingView-এর রিলায়েবল কিবোর্ড শর্টকাট দিয়ে timeframe পরিবর্তন করো।"""
        try:
            # চার্ট এরিয়ার বডিতে ক্লিক করে ফোকাস নিশ্চিত করা
            self.page.click("body")
            time.sleep(0.5)
            
            # সরাসরি টাইমফ্রেমের সংখ্যাটি টাইপ করা (যেমন: 15)
            self.page.keyboard.type(timeframe, delay=100)
            time.sleep(1)
            
            # Enter প্রেস করে টাইমফ্রেম অ্যাপ্লাই করা
            self.page.keyboard.press("Enter")
            time.sleep(3)  # চার্ট লোড হওয়ার জন্য একটু সময় দেওয়া
            
            log.info(f"[BrowserAgent] Timeframe changed via Keyboard -> {timeframe}")
            return True
        except Exception as e:
            log.warning(f"[BrowserAgent] change_timeframe failed: {e}")
            self._save_error(f"timeframe_failed_{timeframe}")
            return False

    def screenshot(self, path: str = "browser_screen.png") -> str:
        self.page.screenshot(path=path)
        return path

    # ═══════════════════════════════════════════════════════
    # DAY 45 — STEP 8 TEST  ⭐
    # ═══════════════════════════════════════════════════════

    def run_tradingview_test(self, symbol: str = "EURUSD", timeframe: str = "15") -> dict:
        """
        Day 45 doc-এর শেষ test:
          1. Browser open
          2. TradingView open
          3. Symbol search (= chart select)
          4. Timeframe change

        Returns dict matching doc-এর expected output format।
        """
        steps = {}

        steps["browser_started"] = self.start()
        if not steps["browser_started"]:
            return self._test_result(steps, success=False)

        steps["tradingview_opened"] = self.open_tradingview(symbol)
        steps["symbol_loaded"] = self.search_symbol(symbol) if steps["tradingview_opened"] else False
        steps["timeframe_selected"] = self.change_timeframe(timeframe) if steps["symbol_loaded"] else False

        success = all(steps.values())
        return self._test_result(steps, success=success, symbol=symbol, timeframe=timeframe)

    def _test_result(self, steps: dict, success: bool, symbol: str = "", timeframe: str = "") -> dict:
        result = {"success": success, "steps": steps, "symbol": symbol, "timeframe": timeframe}
        self.print_test_summary(result)
        return result

    def print_test_summary(self, result: dict) -> None:
        print("\n🤖 Computer Agent\n")
        labels = {
            "browser_started": "Browser opened",
            "tradingview_opened": "TradingView opened",
            "symbol_loaded": f"{result.get('symbol', '')} loaded",
            "timeframe_selected": (
                f"M{result.get('timeframe', '')} selected" if result.get("timeframe") else "Timeframe selected"
            ),
        }
        for key, label in labels.items():
            ok = result["steps"].get(key, False)
            print(f"{label} {'✅' if ok else '❌'}")
        print()

    # ═══════════════════════════════════════════════════════
    # ERROR HANDLING + SAFETY
    # ═══════════════════════════════════════════════════════

    def _save_error(self, tag: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.error_dir, f"{ts}_{tag}.png")
        try:
            if self.page:
                self.page.screenshot(path=path)
                log.error(f"[BrowserAgent] ❌ ERROR — {tag} | screenshot={path}")
        except Exception as e:
            log.error(f"[BrowserAgent] Could not save error screenshot: {e}")

    def _safety_approved(self, action: str, safety_context: dict) -> bool:
        if not self.safety:
            return True
        ctx = dict(safety_context or {})
        ctx.setdefault("action", action)
        ctx.setdefault("active_window", "Browser (TradingView)")
        decision = self.safety.check_before_click(ctx)
        if not decision["approved"]:
            self._save_error(f"safety_blocked_{action}")
        return decision["approved"]