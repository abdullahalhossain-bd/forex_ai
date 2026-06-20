# computer_use/stability_manager.py  —  Day 50 | Automation Stability Layer ⭐
# ============================================================
# মূল লক্ষ্য: screen automation কখনো silent crash না করা। কিছু ভুল
# হলে নিজে detect করে recover করবে, আর recovery-ও fail করলে MT5
# (broker/mt5_data.py) API data-তে fallback করবে — পুরো trading loop
# একটা browser glitch-এর জন্য বন্ধ হয়ে যাবে না।
#
# doc-এর monitor() loop হুবহু রাখা হয়েছে (try → 5টা check → except হলে
# recover() → 5 সেকেন্ড sleep → loop)। কিন্তু ভিতরের প্রতিটা check এখন
# তোমার আসল Day 46-48 infrastructure দিয়ে কাজ করে — কোনো fictional
# browser.exists("popup")-ধরনের string lookup নেই।
#
# Wiring:
#   ScreenDetector    → popup/session/page/chart/screenshot detect
#   RecoveryEngine    → refresh/restart/aliveness
#   TradingViewAgent  → login() (Day 46, .env credential)
#   ImageCapture      → screenshot নেওয়া (Day 47)
#   MT5DataFeed       → browser পুরো dead হলে market data fallback (Day 32)
# ============================================================

import os
import time
from datetime import datetime, timezone

from utils.logger import get_logger
from computer_use.screen_detector import ScreenDetector
from computer_use.recovery_engine import RecoveryEngine

log = get_logger("computer_use.stability_manager")

STABILITY_LOG_PATH = "logs/stability.log"
MAX_FALLBACK_CYCLES_BEFORE_ALERT = 5   # এর বেশি ধরে fallback mode-এ থাকলে হার্ড alert


class StabilityManager:
    """
    Usage:
        sm = StabilityManager(
            tv_agent=tv,                       # Day 46 TradingViewAgent
            mt5_data_feed=mt5_feed,             # Day 32 MT5DataFeed (API fallback)
            expected_symbol="EURUSD",
            expected_timeframe="H1",
        )

        sm.check_once()          # একবার সব check + recovery
        sm.monitor(stop_flag=...)  # blocking loop, doc-এর monitor()

        # FlowController (Day 49) প্রতি cycle-এর আগে এটা call করতে পারে:
        if sm.is_browser_mode_healthy():
            ... screen automation/vision চালাও ...
        else:
            data = sm.get_fallback_data(symbol, timeframe)
    """

    CHECK_INTERVAL_SEC = 5   # doc-এর monitor() loop interval

    def __init__(
        self,
        tv_agent,
        mt5_data_feed=None,
        expected_symbol: str = None,
        expected_timeframe: str = None,
        log_path: str = STABILITY_LOG_PATH,
    ):
        self.tv_agent = tv_agent
        self.detector = ScreenDetector(controller=tv_agent.controller)
        self.recovery = RecoveryEngine(tv_agent=tv_agent)
        self.mt5_feed = mt5_data_feed

        self.expected_symbol = expected_symbol
        self.expected_timeframe = expected_timeframe

        self._fallback_mode = False
        self._fallback_cycles = 0
        self._last_check_at = None
        self._issue_log: list = []   # সব detected issue + action record

        os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
        self.log_path = log_path

    # ═══════════════════════════════════════════════════════
    # MAIN LOOP  (doc-এর monitor() — হুবহু structure)
    # ═══════════════════════════════════════════════════════

    def monitor(self, stop_flag=None, max_cycles: int = None) -> None:
        """
        doc flow:
            while True:
                try: check_popup → check_session → check_page →
                     check_chart → check_screen
                except: recover()
                sleep(5)
        """
        log.info("[StabilityManager] 🛡️ Starting stability monitor loop")
        cycles = 0
        while True:
            if stop_flag and stop_flag():
                log.info("[StabilityManager] Stop flag set — exiting monitor loop")
                break
            if max_cycles is not None and cycles >= max_cycles:
                break

            try:
                self.check_once()
            except Exception as e:
                self._log_issue("MONITOR_EXCEPTION", str(e))
                log.error(f"[StabilityManager] Stability error: {e}")
                self.recover()

            cycles += 1
            time.sleep(self.CHECK_INTERVAL_SEC)

    # ═══════════════════════════════════════════════════════
    # SINGLE CHECK PASS  (doc-এর ৫টা check, এক জায়গায়)
    # ═══════════════════════════════════════════════════════

    def check_once(self) -> dict:
        """একবার সব stability check চালায়। প্রতিটা ধাপ স্বাধীন — একটা fail
        করলেও পরের গুলো এড়িয়ে যাওয়া হয় না, কারণ একই cycle-এ একাধিক ছোট
        সমস্যা একসাথে থাকতে পারে (যেমন popup + session expired একসাথে)।"""
        self._last_check_at = datetime.now(timezone.utc).isoformat()
        report = {"timestamp": self._last_check_at, "issues": [], "actions": []}

        try:
            self._check_popup(report)
            self._check_session(report)
            self._check_page(report)
            self._check_chart(report)
            self._check_screen(report)
        except Exception as e:
            self._log_issue("CHECK_ONCE_EXCEPTION", str(e))
            log.error(f"[StabilityManager] check_once exception: {e}")
            self.recover()
            report["issues"].append("check_once_exception")

        if not report["issues"]:
            # সব ঠিক থাকলে fallback mode থেকে বের হওয়ার সুযোগ
            if self._fallback_mode:
                self._exit_fallback_mode()
        return report

    # ═══════════════════════════════════════════════════════
    # 1. POPUP CHECK  (doc Section 2)
    # ═══════════════════════════════════════════════════════

    def _check_popup(self, report: dict) -> None:
        if self.detector.has_popup():
            self._log_issue("POPUP_DETECTED", "Popup blocking automation")
            report["issues"].append("popup")
            closed = self.detector.close_popup()
            report["actions"].append(f"close_popup={'ok' if closed else 'failed'}")
            if not closed:
                log.warning("[StabilityManager] ⚠️ Popup close failed — will retry next cycle")

    # ═══════════════════════════════════════════════════════
    # 2. SESSION CHECK  (doc Section 3 — re-login uses tradingview_agent.login())
    # ═══════════════════════════════════════════════════════

    def _check_session(self, report: dict) -> None:
        if self.detector.is_logged_out():
            self._log_issue("SESSION_EXPIRED", "Logged out — re-authenticating")
            report["issues"].append("session_expired")
            login_result = self.tv_agent.login()   # .env থেকে credential, Day 46-এ already built
            ok = login_result.get("success", False)
            report["actions"].append(f"re_login={'ok' if ok else 'failed'}")
            if not ok:
                log.error(
                    f"[StabilityManager] ❌ Re-login failed: {login_result.get('reason')} — "
                    "captcha/2FA হলে manual intervention লাগবে"
                )

    # ═══════════════════════════════════════════════════════
    # 3. PAGE IDENTITY CHECK  (doc Section 5)
    # ═══════════════════════════════════════════════════════

    def _check_page(self, report: dict) -> None:
        if not self.expected_symbol:
            return
        if not self.detector.is_correct_page(self.expected_symbol):
            self._log_issue(
                "WRONG_PAGE",
                f"Expected {self.expected_symbol}, got title='{self.tv_agent.controller.current_title()}'",
            )
            report["issues"].append("wrong_page")
            result = self.tv_agent.open_chart(self.expected_symbol)
            if self.expected_timeframe:
                self.tv_agent.change_timeframe(self.expected_timeframe)
            report["actions"].append(f"navigate_back={'ok' if result.get('success') else 'failed'}")

    # ═══════════════════════════════════════════════════════
    # 4. CHART LOAD CHECK  (doc Section 4 — retry then API fallback)
    # ═══════════════════════════════════════════════════════

    def _check_chart(self, report: dict) -> None:
        if self.detector.is_chart_loaded():
            return

        self._log_issue("CHART_MISSING", "Chart not visible — attempting refresh-retry")
        report["issues"].append("chart_missing")

        recovered = self.recovery.retry_with_refresh(
            check_fn=self.detector.is_chart_loaded, max_attempts=3, wait_sec=5.0
        )
        if recovered:
            report["actions"].append("chart_refresh_recovered")
            log.info("[StabilityManager] ✅ Chart recovered after refresh retry")
        else:
            report["actions"].append("chart_refresh_failed → api_fallback")
            log.warning("[StabilityManager] ⚠️ Chart still missing after retries — switching to API fallback")
            self._enter_fallback_mode("chart_load_failure")

    # ═══════════════════════════════════════════════════════
    # 5. SCREENSHOT QUALITY CHECK  (doc Section 6)
    # ═══════════════════════════════════════════════════════

    def _check_screen(self, report: dict) -> None:
        try:
            from computer_use.image_capture import ImageCapture
            capture = ImageCapture(page=self.tv_agent.controller.page)
            result = capture.capture_chart(
                self.expected_symbol or "UNKNOWN", self.expected_timeframe or "UNKNOWN"
            )
            if not result.get("success"):
                self._log_issue("SCREENSHOT_FAILED", "Could not capture screenshot")
                report["issues"].append("screenshot_failed")
                return

            quality = self.detector.check_screenshot_quality(result["path"])
            if not quality["ok"]:
                self._log_issue("BAD_SCREENSHOT", quality["reason"])
                report["issues"].append("bad_screenshot")
                # doc-এর "capture_again" — একবার retry করে দেখা
                retry_result = capture.capture_chart(
                    self.expected_symbol or "UNKNOWN", self.expected_timeframe or "UNKNOWN"
                )
                retry_quality = (
                    self.detector.check_screenshot_quality(retry_result["path"])
                    if retry_result.get("success") else {"ok": False}
                )
                report["actions"].append(f"recapture={'ok' if retry_quality.get('ok') else 'still_bad'}")
        except Exception as e:
            log.warning(f"[StabilityManager] Screenshot quality check error (non-fatal): {e}")

    # ═══════════════════════════════════════════════════════
    # RECOVERY ENGINE HOOK  (doc Section 8)
    # ═══════════════════════════════════════════════════════

    def recover(self) -> None:
        """doc-এর recover() — refresh, dead হলে restart।"""
        log.info("[StabilityManager] Starting recovery")
        self.recovery.refresh_page()
        time.sleep(5)   # doc অনুযায়ী 10s বলা আছে recover()-এ, কিন্তু refresh_page() নিজেই
                          # ৩s wait করে — তাই মোট wait কাছাকাছি রাখা হলো

        if not self.recovery.is_browser_alive():
            restarted = self.recovery.restart_browser(
                symbol=self.expected_symbol, timeframe=self.expected_timeframe
            )
            if not restarted:
                self._enter_fallback_mode("browser_restart_failed")

        log.info("[StabilityManager] Recovery completed")

    # ═══════════════════════════════════════════════════════
    # API FALLBACK  (doc Section 7)
    # ═══════════════════════════════════════════════════════

    def _enter_fallback_mode(self, reason: str) -> None:
        self._fallback_mode = True
        self._fallback_cycles += 1
        log.warning(f"[StabilityManager] 🔀 Entering API fallback mode — {reason}")

        if self._fallback_cycles >= MAX_FALLBACK_CYCLES_BEFORE_ALERT:
            log.error(
                f"[StabilityManager] 🚨 ALERT — stuck in fallback mode for "
                f"{self._fallback_cycles} cycles, browser automation likely broken"
            )

    def _exit_fallback_mode(self) -> None:
        if self._fallback_mode:
            log.info("[StabilityManager] ✅ Browser healthy again — exiting API fallback mode")
        self._fallback_mode = False
        self._fallback_cycles = 0

    def is_browser_mode_healthy(self) -> bool:
        """FlowController/ChartReader call করার আগে চেক করতে পারে — False হলে
        vision/drawing automation skip করে শুধু quant data-র উপর নির্ভর করা উচিত।"""
        return not self._fallback_mode

    def get_fallback_data(self, symbol: str, timeframe: str = "M15", count: int = 100) -> dict:
        """
        doc-এর api_fallback() — browser broken থাকলেও MT5DataFeed থেকে
        candle data এনে দেয়, যাতে FlowController (Day 49)-এর quant pipeline
        চলতেই থাকে, শুধু vision/drawing অংশটা skip হয়।
        """
        if not self.mt5_feed:
            log.error("[StabilityManager] No MT5DataFeed wired — cannot fallback")
            return {"success": False, "reason": "no_mt5_feed_configured"}

        log.info(f"[StabilityManager] Switching to API mode — {symbol} {timeframe}")
        candles = self.mt5_feed.get_candles(symbol, timeframe, count=count)
        tick = self.mt5_feed.get_tick(symbol)

        return {
            "success": bool(candles),
            "source": "mt5_api_fallback",
            "candles": candles,
            "tick": tick,
        }

    # ═══════════════════════════════════════════════════════
    # ISSUE LOG  (logs/stability.log — doc-এর logging.basicConfig target)
    # ═══════════════════════════════════════════════════════

    def _log_issue(self, issue_type: str, detail: str) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": issue_type,
            "detail": detail,
        }
        self._issue_log.append(entry)
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(f"{entry['timestamp']} | {issue_type} | {detail}\n")
        except Exception as e:
            log.warning(f"[StabilityManager] Could not write stability log: {e}")

    def get_issue_log(self, limit: int = 50) -> list:
        return self._issue_log[-limit:]

    # ═══════════════════════════════════════════════════════
    # PRINT SUMMARY
    # ═══════════════════════════════════════════════════════

    def print_status(self) -> None:
        bar = "═" * 54
        print(f"\n{bar}")
        print("  🛡️   STABILITY MANAGER  (Day 50)")
        print(bar)
        print(f"  Last check       : {self._last_check_at}")
        print(f"  Fallback mode    : {'🔀 ACTIVE (' + str(self._fallback_cycles) + ' cycles)' if self._fallback_mode else '✅ Browser mode'}")
        print(f"  Issues logged    : {len(self._issue_log)}")
        for issue in self._issue_log[-10:]:
            print(f"   • {issue['timestamp']}  {issue['type']:<20} {issue['detail'][:50]}")
        print(bar + "\n")