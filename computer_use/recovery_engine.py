# computer_use/recovery_engine.py  —  Day 50 | Recovery Engine ⭐
# ============================================================
# StabilityManager যখন কোনো check fail করে detect করে, এই module
# আসলে recovery action করে — refresh, restart, re-navigate।
#
# doc-এর pseudocode:
#     self.browser.refresh()
#     if not self.browser.is_alive(): self.browser.restart()
#
# তোমার আসল BrowserController (Day 46)-এ "is_alive"/"restart" নামে
# কিছু নেই — Playwright-এ page crash হলে page.* call করলে Exception
# ওঠে, তাই "is_alive" বলতে এখানে "একটা harmless call করে দেখা" বোঝানো
# হয়েছে, আর "restart" মানে controller.close() + নতুন start() + আগের
# chart/pair/timeframe state-এ ফিরে যাওয়া (TradingViewAgent দিয়ে)।
# ============================================================

import time

from utils.logger import get_logger

log = get_logger("computer_use.recovery_engine")


class RecoveryEngine:
    """
    Usage:
        recovery = RecoveryEngine(tv_agent=tv)
        recovery.refresh_page()
        if not recovery.is_browser_alive():
            recovery.restart_browser(symbol="EURUSD", timeframe="H1")
    """

    def __init__(self, tv_agent):
        """tv_agent: Day 46 TradingViewAgent — controller + login + open_chart সবই এর ভিতরে।"""
        self.tv_agent = tv_agent

    # ═══════════════════════════════════════════════════════
    # PAGE REFRESH
    # ═══════════════════════════════════════════════════════

    def refresh_page(self, wait_after: float = 3.0) -> bool:
        """বর্তমান URL-এই reload — doc-এর self.browser.refresh()।"""
        try:
            controller = self.tv_agent.controller
            controller.page.reload(wait_until="domcontentloaded", timeout=20000)
            time.sleep(wait_after)
            log.info("[RecoveryEngine] Page refreshed ✅")
            controller.log_activity("page_refresh", "SUCCESS")
            return True
        except Exception as e:
            log.error(f"[RecoveryEngine] Refresh failed: {e}")
            self.tv_agent.controller.log_activity("page_refresh", "FAILED", error=str(e))
            return False

    # ═══════════════════════════════════════════════════════
    # ALIVENESS CHECK
    # ═══════════════════════════════════════════════════════

    def is_browser_alive(self) -> bool:
        """
        Playwright page crash/disconnect হলে যেকোনো property access-ও
        exception ওঠায় — এটাই সবচেয়ে cheap aliveness probe (doc-এর
        is_alive())।
        """
        try:
            _ = self.tv_agent.controller.page.url
            return True
        except Exception as e:
            log.warning(f"[RecoveryEngine] Browser appears dead: {e}")
            return False

    # ═══════════════════════════════════════════════════════
    # FULL RESTART  (doc-এর restart())
    # ═══════════════════════════════════════════════════════

    def restart_browser(self, symbol: str = None, timeframe: str = None) -> bool:
        """
        Browser পুরো বন্ধ করে নতুন instance চালু করে, এবং (দেওয়া থাকলে)
        আগের pair/timeframe-এ ফিরে যায় — যাতে trading loop interrupt
        হলেও context হারিয়ে না যায়।
        """
        log.warning("[RecoveryEngine] 🔄 Full browser restart initiated")
        try:
            self.tv_agent.close()
        except Exception as e:
            log.warning(f"[RecoveryEngine] close() during restart raised (ignored): {e}")

        time.sleep(2)
        started = self.tv_agent.start()
        if not started:
            log.error("[RecoveryEngine] ❌ Restart failed — could not start browser")
            return False

        if symbol:
            self.tv_agent.open_chart(symbol)
            if timeframe:
                self.tv_agent.change_timeframe(timeframe)

        log.info("[RecoveryEngine] ✅ Browser restarted successfully")
        return True

    # ═══════════════════════════════════════════════════════
    # GENERIC RETRY WRAPPER  (refresh → wait → retry pattern, doc-এর সব
    # recovery section-এ বারবার আসা pattern-টা একবারই লেখা)
    # ═══════════════════════════════════════════════════════

    def retry_with_refresh(self, check_fn, max_attempts: int = 3, wait_sec: float = 5.0) -> bool:
        """
        check_fn: callable() -> bool, True হলে condition satisfied (যেমন
        chart loaded)। প্রতি attempt-এ refresh করে আবার check করে।
        """
        for attempt in range(1, max_attempts + 1):
            if check_fn():
                return True
            log.info(f"[RecoveryEngine] retry_with_refresh attempt {attempt}/{max_attempts}")
            self.refresh_page()
            time.sleep(wait_sec)

        return check_fn()   # শেষ চেষ্টা