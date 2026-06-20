# computer_use/computer_agent.py  —  Day 45-46 | Unified "Hands" Interface
# ============================================================
#         🧠 Brain  =  Analysis + Decision System  (Day 1-44, already built)
#         🖥️ Hands  =  Computer Use System  (Day 45 screen/mouse + Day 46 browser DOM)
#
# অন্য agent (যেমন future ExecutionRouter / DecisionAgent) এই একটাই
# class দিয়ে screen/mouse/keyboard/browser/vision/safety — সব ব্যবহার
# করতে পারবে, আলাদা আলাদা module import করার দরকার নেই।
#
# Day 45 vs Day 46 browser engine — দুটোই রাখা হয়েছে, ভিন্ন কাজে:
#   .browser       (Day 45, browser_control.py)     — quick screenshot-based test
#   .tradingview   (Day 46, tradingview_agent.py)   — DOM-direct, verification,
#                                                       session persistence,
#                                                       AI command interface
#   নতুন কাজের জন্য .tradingview ব্যবহার করাই recommended (বেশি reliable)।
# ============================================================

from utils.logger import get_logger
from computer_use.safety import SafetyLayer, SafetyConfig
from computer_use.mouse_agent import MouseAgent
from computer_use.vision import VisionAgent
from computer_use.browser_control import BrowserAgent                       # Day 45
from computer_use.browser_controller import BrowserController               # Day 46
from computer_use.browser_safety import BrowserSafetyLayer, BrowserSafetyConfig  # Day 46
from computer_use.tradingview_agent import TradingViewAgent                  # Day 46

log = get_logger("computer_use.agent")


class ComputerAgent:
    """
    AI Trader-এর সম্পূর্ণ Computer Use Layer — একসাথে।

    Usage:
        hands = ComputerAgent(allowed_symbols=["EURUSD", "GBPUSD"],
                               allowed_timeframes=["M15", "H1"], max_lot=0.5)

        # Day 46 — DOM-direct, recommended:
        result = hands.run_chart_command({"action": "OPEN_CHART", "pair": "EURUSD", "timeframe": "H1"})

        # Day 45 — quick screenshot-based test:
        result = hands.tradingview_test("EURUSD", "15")

        hands.stop_browser()
    """

    def __init__(self, allowed_symbols: list = None, allowed_timeframes: list = None,
                 max_lot: float = 1.0, expected_windows: list = None,
                 headless_browser: bool = False):
        # Day 45 — desktop-level safety (window/lot/SL)
        self.safety = SafetyLayer(SafetyConfig(
            expected_window_titles=expected_windows or ["TradingView", "MetaTrader 5"],
            allowed_symbols=allowed_symbols,
            max_lot_size=max_lot,
        ))
        # Day 46 — browser-level safety (broker domain/account/pair/timeframe)
        self.browser_safety = BrowserSafetyLayer(BrowserSafetyConfig(
            allowed_pairs=allowed_symbols,
            allowed_timeframes=allowed_timeframes,
        ))

        self.vision = VisionAgent()
        self.mouse = MouseAgent()
        self.headless_browser = headless_browser

        self.browser = BrowserAgent(safety=self.safety, headless=headless_browser)   # Day 45

        self._screen = None         # lazy — শুধু GUI desktop থাকলে init হবে (pyautogui)
        self._tradingview = None    # lazy — Day 46 DOM-direct agent

    # ── Desktop screen control — শুধু দরকার হলে lazy init করে ──
    @property
    def screen(self):
        if self._screen is None:
            from computer_use.screen_controller import ScreenController
            self._screen = ScreenController(safety=self.safety)
        return self._screen

    # ── Day 46 — DOM-direct TradingView control (lazy + auto-start) ──
    @property
    def tradingview(self) -> TradingViewAgent:
        if self._tradingview is None:
            controller = BrowserController(headless=self.headless_browser)
            self._tradingview = TradingViewAgent(controller=controller, safety=self.browser_safety)
            self._tradingview.start()
        return self._tradingview

    def run_chart_command(self, command: dict) -> dict:
        """Day 46 AI Command Interface শর্টকাট — {"action": "OPEN_CHART", "pair": "EURUSD", ...}"""
        return self.tradingview.execute_command(command)

    # ── Day 45 — Browser shortcuts (quick screenshot-based) ──────────
    def start_browser(self) -> bool:
        return self.browser.start()

    def stop_browser(self) -> None:
        self.browser.close()
        if self._tradingview is not None:
            self._tradingview.close()
            self._tradingview = None

    def tradingview_test(self, symbol: str = "EURUSD", timeframe: str = "15") -> dict:
        """Day 45 doc-এর শেষ test সরাসরি চালাও।"""
        return self.browser.run_tradingview_test(symbol, timeframe)

    # ── Vision shortcuts ─────────────────────────────────────
    def describe_chart(self, image_path: str) -> str:
        return self.vision.analyze_chart(image_path).get("analysis", "")

    def verify(self, expected_text: str) -> bool:
        return self.vision.verify_action(expected_text).get("verified", False)