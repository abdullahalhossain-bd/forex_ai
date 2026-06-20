# computer_use/browser_controller.py  —  Day 46 | Browser Automation (Direct Control Layer)
# ============================================================
# Day 45-এ pyautogui screenshot দেখে "আন্দাজ করে" button খোঁজে।
# Day 46-এ সরাসরি browser DOM control: selector দিয়ে exact element
# ধরা, attribute/text পড়ে state verify করা — screenshot লাগে না।
#
# Engine: Playwright
#   (doc নিজেই বলেছে "10/10 করতে Playwright consider করো" — Selenium-এর
#    চেয়ে faster, better auto-waiting, more reliable; আর Day 45-এর
#    browser_control.py-ও একই engine ব্যবহার করে, তাই নতুন dependency
#    লাগছে না।)
#
# Bonus (10/10 checklist থেকে) যা এই ফাইলে আছে:
#   ✅ Session management   — persistent browser profile (login টিকে থাকে)
#   ✅ Retry + Recovery     — fail → wait → reload → retry → alert
#   ✅ Activity log         — timestamp/action/result/error JSONL ফাইলে
#
# Requirements:
#   pip install playwright
#   playwright install chromium
# ============================================================

import json
import os
import time
from datetime import datetime, timezone

from utils.logger import get_logger

log = get_logger("computer_use.browser_controller")

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except Exception as e:
    PLAYWRIGHT_AVAILABLE = False
    log.warning(f"[BrowserController] playwright unavailable: {e}")

DEFAULT_PROFILE_DIR = "computer_use/browser_profile"      # session persistence
DEFAULT_ACTIVITY_LOG = "computer_use/logs/browser_activity.jsonl"
DEFAULT_ERROR_DIR = "computer_use/errors"


class BrowserController:
    """
    Day 46 core file। Chrome launch, navigation, DOM click/type/read,
    retry+recovery, persistent session, activity logging — সব এখানে।

    TradingView-specific উঁচু-স্তরের কাজ (open chart, change timeframe,
    verify ইত্যাদি) `tradingview_agent.py`-তে — এই class শুধু generic
    "direct control" engine।

    Usage:
        bc = BrowserController()
        bc.start()
        bc.goto_with_recovery("https://www.tradingview.com")
        text = bc.get_text(".some-selector")
        bc.close()
    """

    def __init__(
        self,
        headless: bool = False,
        profile_dir: str = DEFAULT_PROFILE_DIR,
        activity_log_path: str = DEFAULT_ACTIVITY_LOG,
        use_persistent_session: bool = True,
    ):
        self.headless = headless
        self.profile_dir = profile_dir
        self.activity_log_path = activity_log_path
        self.use_persistent_session = use_persistent_session

        self.playwright = None
        self.browser = None        # শুধু non-persistent mode-এ ব্যবহার হয়
        self.context = None
        self.page = None

        os.makedirs(os.path.dirname(self.activity_log_path) or ".", exist_ok=True)
        os.makedirs(DEFAULT_ERROR_DIR, exist_ok=True)

    # ═══════════════════════════════════════════════════════
    # 1. CHROME LAUNCH  (+ Session Management bonus ⭐⭐⭐)
    # ═══════════════════════════════════════════════════════

    def start(self) -> bool:
        if not PLAYWRIGHT_AVAILABLE:
            log.error("[BrowserController] Playwright not installed")
            self.log_activity("start", "FAILED", error="playwright_not_installed")
            return False

        self.playwright = sync_playwright().start()

        if self.use_persistent_session:
            # প্রতিবার নতুন করে login না করার জন্য — cookies/localStorage
            # একই profile_dir-এ save হয়ে থাকে, পরের রান-এও login state টিকে থাকে।
            os.makedirs(self.profile_dir, exist_ok=True)
            self.context = self.playwright.chromium.launch_persistent_context(
                self.profile_dir,
                headless=self.headless,
                viewport={"width": 1600, "height": 900},
                args=["--start-maximized"],
            )
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
            log.info(f"[BrowserController] Chrome started ✅ (persistent profile: {self.profile_dir})")
        else:
            self.browser = self.playwright.chromium.launch(
                headless=self.headless, args=["--start-maximized"]
            )
            self.context = self.browser.new_context(viewport={"width": 1600, "height": 900})
            self.page = self.context.new_page()
            log.info("[BrowserController] Chrome started ✅ (fresh session)")

        self.log_activity("start", "SUCCESS")
        return True

    def close(self) -> None:
        try:
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
            self.log_activity("close", "SUCCESS")
            log.info("[BrowserController] Browser closed 🔴")
        except Exception as e:
            self.log_activity("close", "FAILED", error=str(e))
            log.warning(f"[BrowserController] close() error: {e}")

    # ═══════════════════════════════════════════════════════
    # 2. NAVIGATION
    # ═══════════════════════════════════════════════════════

    def goto(self, url: str, wait_after: float = 2.0, timeout: int = 20000) -> None:
        """একবারের চেষ্টা — fail করলে exception raise হবে (retry চাইলে
        goto_with_recovery() ব্যবহার করো)।"""
        self.page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        time.sleep(wait_after)
        log.info(f"[BrowserController] Navigated -> {url}")

    def goto_with_recovery(self, url: str, action_name: str = None,
                            max_retries: int = 2, wait_seconds: int = 5) -> bool:
        """Retry + Recovery System — doc flow: load failed → wait → reload → retry → alert"""
        action_name = action_name or f"goto_{url}"
        return self.with_retry_recovery(
            lambda: self.goto(url), action_name, max_retries, wait_seconds
        )

    # ═══════════════════════════════════════════════════════
    # 3. DOM INTERACTION  (click / type / read)
    # ═══════════════════════════════════════════════════════

    def click(self, selector: str, timeout: int = 5000) -> None:
        el = self.page.locator(selector).first
        el.wait_for(timeout=timeout)
        el.click()
        log.info(f"[BrowserController] Clicked: {selector}")

    def click_with_recovery(self, selector: str, action_name: str = None,
                             max_retries: int = 2, wait_seconds: int = 3) -> bool:
        action_name = action_name or f"click_{selector[:30]}"
        return self.with_retry_recovery(
            lambda: self.click(selector), action_name, max_retries, wait_seconds
        )

    def type_text(self, selector: str, text: str, delay: int = 60) -> None:
        el = self.page.locator(selector).first
        el.wait_for(timeout=5000)
        el.fill("")
        el.type(text, delay=delay)
        log.info(f"[BrowserController] Typed '{text}' into {selector}")

    def press_key(self, key: str) -> None:
        self.page.keyboard.press(key)
        log.info(f"[BrowserController] Key pressed: {key}")

    def get_text(self, selector: str, timeout: int = 5000) -> str:
        try:
            el = self.page.locator(selector).first
            el.wait_for(timeout=timeout)
            return (el.text_content() or "").strip()
        except Exception as e:
            log.warning(f"[BrowserController] get_text failed '{selector}': {e}")
            return ""

    def get_attribute(self, selector: str, attr: str, timeout: int = 5000) -> str:
        try:
            el = self.page.locator(selector).first
            el.wait_for(timeout=timeout)
            return el.get_attribute(attr) or ""
        except Exception as e:
            log.warning(f"[BrowserController] get_attribute failed '{selector}': {e}")
            return ""

    def element_exists(self, selector: str, timeout: int = 3000) -> bool:
        try:
            self.page.locator(selector).first.wait_for(timeout=timeout)
            return True
        except Exception:
            return False

    def current_url(self) -> str:
        return self.page.url if self.page else ""

    def current_title(self) -> str:
        return self.page.title() if self.page else ""

    def screenshot(self, path: str = "browser_screen.png") -> str:
        self.page.screenshot(path=path)
        return path

    # ═══════════════════════════════════════════════════════
    # 4. RETRY + RECOVERY SYSTEM  ⭐⭐⭐⭐⭐
    # ═══════════════════════════════════════════════════════

    def with_retry_recovery(self, action_fn, action_name: str,
                             max_retries: int = 2, wait_seconds: int = 5) -> bool:
        """
        doc-এর flow হুবহু:
            action failed → wait N sec → reload → try again → ... → alert

        Returns True on success, False after exhausting retries (alert
        log করে এবং error screenshot save করে)।
        """
        last_error = None
        for attempt in range(1, max_retries + 2):
            try:
                action_fn()
                self.log_activity(action_name, "SUCCESS")
                return True
            except Exception as e:
                last_error = e
                log.warning(f"[BrowserController] '{action_name}' failed (attempt {attempt}): {e}")
                self.log_activity(action_name, "RETRY", error=str(e))
                if attempt <= max_retries:
                    time.sleep(wait_seconds)
                    try:
                        self.page.reload(wait_until="domcontentloaded", timeout=15000)
                        time.sleep(2)
                    except Exception as reload_err:
                        log.warning(f"[BrowserController] reload failed: {reload_err}")

        self._alert(action_name, last_error)
        self.log_activity(action_name, "FAILED", error=str(last_error))
        return False

    def _alert(self, action_name: str, error: Exception) -> None:
        """এখন শুধু critical log + error screenshot — পরে email/Telegram
        alert hook এখানে যোগ করা যাবে।"""
        log.error(f"[BrowserController] 🚨 ALERT — '{action_name}' permanently failed: {error}")
        try:
            self.screenshot(os.path.join(DEFAULT_ERROR_DIR, f"{action_name}_failed.png"))
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════
    # 5. ACTIVITY LOG  ⭐⭐⭐⭐
    # ═══════════════════════════════════════════════════════

    def log_activity(self, action: str, result: str, error: str = None) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "action": action,
            "result": result,
            "error": error,
        }
        try:
            with open(self.activity_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            log.warning(f"[BrowserController] Could not write activity log: {e}")

        icon = {"SUCCESS": "✅", "RETRY": "🔄", "FAILED": "❌"}.get(result, "•")
        log.info(f"[Activity] {icon} {action} -> {result}" + (f" | {error}" if error else ""))

    def get_activity_log(self, limit: int = 50) -> list:
        """পরে AI/human যাতে বুঝতে পারে কোথায় কোথায় সমস্যা হয়েছিল।"""
        if not os.path.exists(self.activity_log_path):
            return []
        with open(self.activity_log_path, encoding="utf-8") as f:
            lines = [json.loads(l) for l in f if l.strip()]
        return lines[-limit:]

    def print_activity_log(self, limit: int = 20) -> None:
        bar = "═" * 60
        print(f"\n{bar}")
        print("  📜  BROWSER ACTIVITY LOG  (Day 46)")
        print(bar)
        for entry in self.get_activity_log(limit):
            icon = {"SUCCESS": "✅", "RETRY": "🔄", "FAILED": "❌"}.get(entry["result"], "•")
            line = f"  {entry['timestamp']}  {icon}  {entry['action']:<28} {entry['result']}"
            if entry.get("error"):
                line += f"  | {entry['error'][:40]}"
            print(line)
        print(bar + "\n")