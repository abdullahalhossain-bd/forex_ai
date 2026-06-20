# computer_use/tradingview_agent.py  —  Day 46 | TradingView Agent Layer
# ============================================================
# browser_controller.py হলো generic DOM-control engine।
# TradingViewAgent তার উপর TradingView-specific domain logic বসায়:
#   - chart open + pair search
#   - timeframe change
#   - fullscreen
#   - login (credential .env থেকে, কখনো code-এ hardcode না)
#   - DOM-based verification (Section 8 — screenshot/OCR লাগে না)
#   - AI Command Interface (Section 10 — JSON command dispatch)
#
# ⚠️ TradingView নিয়মিত frontend selector বদলায়। এখানে দেওয়া selector
#    গুলো লেখার সময়কার best-effort selector — যদি কোনো একটা ভেঙে যায়,
#    browser-এর "Inspect Element" দিয়ে আসল selector বের করে এখানে
#    আপডেট করে দিও (login() ও fullscreen_chart() সবচেয়ে বেশি ঝুঁকিতে,
#    কারণ TradingView মাঝে মাঝে captcha/UI পাল্টায়)।
# ============================================================

import os
import time

from utils.logger import get_logger
from computer_use.browser_controller import BrowserController
from computer_use.browser_safety import BrowserSafetyLayer

log = get_logger("computer_use.tradingview_agent")

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass   # python-dotenv না থাকলেও os.environ থেকে credential পড়া যাবে


# মানুষের জন্য বোঝা সহজ timeframe label -> TradingView-এর internal data-value
TIMEFRAME_MAP = {
    "M1": "1", "M5": "5", "M15": "15", "M30": "30",
    "H1": "60", "H4": "240", "D1": "D", "W1": "W", "MN": "M",
}


class TradingViewAgent:
    """
    Day 46 — TradingView-এর জন্য high-level, intention-based interface।

    Usage:
        agent = TradingViewAgent()
        agent.start()
        agent.open_chart("EURUSD")
        agent.change_timeframe("H1")
        agent.fullscreen_chart()
        print(agent.verify_chart(expected_pair="EURUSD", expected_tf="H1"))
        agent.close()
    """

    def __init__(self, controller: BrowserController = None,
                 safety: BrowserSafetyLayer = None, headless: bool = False):
        self.controller = controller or BrowserController(headless=headless)
        self.safety = safety

    # ═══════════════════════════════════════════════════════
    # LIFECYCLE
    # ═══════════════════════════════════════════════════════

    def start(self) -> bool:
        return self.controller.start()

    def close(self) -> None:
        self.controller.close()

    # ═══════════════════════════════════════════════════════
    # 1+2. CHART OPEN / NAVIGATION
    # ═══════════════════════════════════════════════════════

    def open_chart(self, pair: str) -> dict:
        """নতুন TradingView chart page-এ একটা pair নিয়ে navigate করো।"""
        pair = pair.upper().replace("/", "")
        url = f"https://www.tradingview.com/chart/?symbol=FX:{pair}"

        ok = self.controller.goto_with_recovery(url, action_name=f"open_chart_{pair}")
        if not ok:
            return {"success": False, "pair": pair, "reason": "navigation_failed"}

        time.sleep(4)
        self.controller.press_key("Escape")   # popup/dialog বন্ধ করো
        time.sleep(1)

        verification = self.verify_chart(expected_pair=pair)
        log.info(f"[TradingViewAgent] Chart opened: {pair} | verified={verification.get('verified')}")
        return {"success": True, "pair": pair, "verification": verification}

    # ═══════════════════════════════════════════════════════
    # 3. LOGIN  (credential .env থেকে — কখনো hardcode না)
    # ═══════════════════════════════════════════════════════

    def login(self, username: str = None, password: str = None) -> dict:
        """
        .env-এ থাকা TRADINGVIEW_USER / TRADINGVIEW_PASSWORD ব্যবহার করে।
        TradingView প্রায়ই captcha/2FA দেখায় বলে পুরো automated login
        guarantee না — তাই session management (persistent profile) দিয়ে
        একবার manually login করে রাখাই সবচেয়ে reliable approach।
        """
        username = username or os.environ.get("TRADINGVIEW_USER")
        password = password or os.environ.get("TRADINGVIEW_PASSWORD")

        if not username or not password:
            log.warning(
                "[TradingViewAgent] Credentials missing — .env-এ "
                "TRADINGVIEW_USER ও TRADINGVIEW_PASSWORD সেট করো।"
            )
            return {"success": False, "reason": "missing_credentials"}

        if self.safety:
            decision = self.safety.check_before_action({
                "action": "LOGIN",
                "current_url": self.controller.current_url(),
                "account": username,
            })
            if not decision["approved"]:
                return {"success": False, "reason": "blocked_by_safety", "details": decision["reasons"]}

        try:
            self.controller.goto("https://www.tradingview.com/", wait_after=3)
            self.controller.click('button[id="header-user-menu-sign-in"]')
            time.sleep(1.5)

            # TradingView প্রথমে Google/Apple social login button দেখায় —
            # "Email" option আলাদা ক্লিক করতে হয়।
            if self.controller.element_exists('button[name="Email"]', timeout=3000):
                self.controller.click('button[name="Email"]')
                time.sleep(1)

            self.controller.type_text('input[name="id_username"]', username)
            self.controller.type_text('input[name="id_password"]', password)
            self.controller.click('button[type="submit"]')
            time.sleep(3)

            logged_in = self.controller.element_exists(
                '[data-name="header-user-menu-button"]', timeout=6000
            )
            self.controller.log_activity(
                "login", "SUCCESS" if logged_in else "FAILED",
                error=None if logged_in else "user_menu_not_found",
            )
            return {"success": logged_in}

        except Exception as e:
            log.error(f"[TradingViewAgent] login error: {e}")
            self.controller.log_activity("login", "FAILED", error=str(e))
            return {
                "success": False,
                "reason": str(e),
                "note": (
                    "Automated login captcha/2FA-তে আটকাতে পারে। একবার "
                    "headless=False দিয়ে manually login করে রাখলে persistent "
                    "profile (browser_profile/) সেই session মনে রাখবে — পরের "
                    "বার আর login() call করার দরকার পড়বে না।"
                ),
            }

    # ═══════════════════════════════════════════════════════
    # 4. PAIR SEARCH  (already-open chart-এ)
    # ═══════════════════════════════════════════════════════

    def search_pair(self, pair: str) -> dict:
        pair = pair.upper().replace("/", "")

        def _search():
            self.controller.press_key("/")
            time.sleep(1)
            self.controller.page.keyboard.type(pair, delay=80)
            time.sleep(1.5)
            self.controller.press_key("Enter")
            time.sleep(2)

        ok = self.controller.with_retry_recovery(
            _search, f"search_pair_{pair}", max_retries=1, wait_seconds=3
        )
        verification = self.verify_chart(expected_pair=pair) if ok else {}
        return {"success": ok, "pair": pair, "verification": verification}

    # ═══════════════════════════════════════════════════════
    # 5. TIMEFRAME CONTROL
    # ═══════════════════════════════════════════════════════

    def change_timeframe(self, tf: str) -> dict:
        tf_label = tf.upper()
        tf_value = TIMEFRAME_MAP.get(tf_label, tf_label)

        ok = self.controller.click_with_recovery(
            f'button[data-value="{tf_value}"]',
            action_name=f"change_timeframe_{tf_label}",
            max_retries=1, wait_seconds=3,
        )
        time.sleep(1.5)
        verification = self.verify_chart(expected_tf=tf_label) if ok else {}
        return {"success": ok, "timeframe": tf_label, "verification": verification}

    # ═══════════════════════════════════════════════════════
    # 6. FULLSCREEN CHART
    # ═══════════════════════════════════════════════════════

    def fullscreen_chart(self) -> dict:
        try:
            self.controller.page.keyboard.press("Shift+F")   # TradingView shortcut
            time.sleep(1.5)
            is_full = (
                self.controller.element_exists('[data-name="exit-fullscreen"]', timeout=3000)
                or self.controller.element_exists('.fullscreen', timeout=1000)
            )
            self.controller.log_activity("fullscreen", "SUCCESS" if is_full else "RETRY")
            log.info(f"[TradingViewAgent] Fullscreen mode {'enabled ✅' if is_full else '⚠️ unverified'}")
            return {"success": True, "verified": is_full}
        except Exception as e:
            log.warning(f"[TradingViewAgent] fullscreen_chart error: {e}")
            self.controller.log_activity("fullscreen", "FAILED", error=str(e))
            return {"success": False, "verified": False, "reason": str(e)}

    # ═══════════════════════════════════════════════════════
    # 7+8. STATE READ + VERIFICATION SYSTEM  ⭐⭐⭐⭐⭐
    # ═══════════════════════════════════════════════════════

    def get_current_symbol(self) -> str:
        """
        Screenshot/OCR লাগে না — TradingView-এর browser tab <title> সবসময়
        current symbol-সহ থাকে (যেমন: "EURUSD Chart — TradingView")। এটাই
        সবচেয়ে reliable, selector-independent verification source।
        """
        title = self.controller.current_title()
        return title.split(" ")[0].strip() if title else ""

    def get_current_timeframe(self) -> str:
        """Active timeframe button-এর aria-pressed attribute পড়ো।"""
        for label, value in TIMEFRAME_MAP.items():
            selector = f'button[data-value="{value}"]'
            pressed = self.controller.get_attribute(selector, "aria-pressed")
            if pressed == "true":
                return label
        return ""

    def verify_chart(self, expected_pair: str = None, expected_tf: str = None) -> dict:
        """
        Day 46 doc Section 8 — কোনো action নেওয়ার পর সত্যিই কাজ হলো কিনা
        DOM থেকে সরাসরি পড়ে verify করো (screenshot/OCR না — সরাসরি ডেটা)।
        """
        actual_symbol = self.get_current_symbol()
        actual_tf = self.get_current_timeframe()

        checks = {}
        if expected_pair:
            checks["symbol_match"] = expected_pair.upper() in actual_symbol.upper()
        if expected_tf:
            checks["timeframe_match"] = expected_tf.upper() == actual_tf.upper()

        verified = all(checks.values()) if checks else None
        result = {
            "actual_symbol": actual_symbol,
            "actual_timeframe": actual_tf,
            "checks": checks,
            "verified": verified,
        }
        icon = "✅" if verified else ("❓" if verified is None else "❌")
        log.info(f"[TradingViewAgent] Verify {icon} symbol={actual_symbol} tf={actual_tf}")
        return result

    # ═══════════════════════════════════════════════════════
    # 9. AI COMMAND INTERFACE  ⭐⭐⭐⭐⭐
    # ═══════════════════════════════════════════════════════

    def execute_command(self, command: dict) -> dict:
        """
        Master Analyst (বা অন্য কোনো decision layer) থেকে আসা JSON command
        সরাসরি execute করো।

        Example:
            agent.execute_command({"action": "OPEN_CHART", "pair": "EURUSD", "timeframe": "H1"})
            agent.execute_command({"action": "CHANGE_TIMEFRAME", "timeframe": "M15"})
            agent.execute_command({"action": "VERIFY", "pair": "EURUSD", "timeframe": "H1"})
        """
        action = (command.get("action") or "").upper()
        log.info(f"[TradingViewAgent] Command received: {command}")

        if self.safety:
            decision = self.safety.check_before_action({
                "action": action,
                "current_url": self.controller.current_url(),
                "pair": command.get("pair"),
                "timeframe": command.get("timeframe"),
            })
            if not decision["approved"]:
                return {"success": False, "reason": "blocked_by_safety", "details": decision["reasons"]}

        if action == "OPEN_CHART":
            result = self.open_chart(command["pair"])
            if command.get("timeframe"):
                result["timeframe_result"] = self.change_timeframe(command["timeframe"])
            return result

        if action == "CHANGE_TIMEFRAME":
            return self.change_timeframe(command["timeframe"])

        if action == "SEARCH_PAIR":
            return self.search_pair(command["pair"])

        if action == "LOGIN":
            return self.login(command.get("username"), command.get("password"))

        if action == "FULLSCREEN":
            return self.fullscreen_chart()

        if action == "VERIFY":
            return self.verify_chart(command.get("pair"), command.get("timeframe"))

        log.warning(f"[TradingViewAgent] Unknown action: {action}")
        return {"success": False, "reason": f"Unknown action: {action}"}