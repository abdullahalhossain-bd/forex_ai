# computer_use/computer_agent.py  —  Day 45 | Unified "Hands" Interface
# ============================================================
#         🧠 Brain  =  Analysis + Decision System  (Day 1-44, already built)
#         🖥️ Hands  =  Computer Use System  (Day 45, এই module)
#
# অন্য agent (যেমন future ExecutionRouter / DecisionAgent) এই একটাই
# class দিয়ে screen/mouse/keyboard/browser/vision/safety — সব ব্যবহার
# করতে পারবে, আলাদা আলাদা module import করার দরকার নেই।
# ============================================================

from utils.logger import get_logger
from computer_use.safety import SafetyLayer, SafetyConfig
from computer_use.mouse_agent import MouseAgent
from computer_use.vision import VisionAgent
from computer_use.browser_control import BrowserAgent

log = get_logger("computer_use.agent")


class ComputerAgent:
    """
    AI Trader-এর সম্পূর্ণ Computer Use Layer — একসাথে।

    Usage:
        hands = ComputerAgent(allowed_symbols=["EURUSD", "GBPUSD"], max_lot=0.5)
        result = hands.tradingview_test("EURUSD", "15")
        hands.stop_browser()
    """

    def __init__(self, allowed_symbols: list = None, max_lot: float = 1.0,
                 expected_windows: list = None, headless_browser: bool = False):
        self.safety = SafetyLayer(SafetyConfig(
            expected_window_titles=expected_windows or ["TradingView", "MetaTrader 5"],
            allowed_symbols=allowed_symbols,
            max_lot_size=max_lot,
        ))
        self.vision = VisionAgent()
        self.mouse = MouseAgent()
        self.browser = BrowserAgent(safety=self.safety, headless=headless_browser)

        self._screen = None   # lazy — শুধু GUI desktop থাকলে init হবে (pyautogui)

    # ── Desktop screen control — শুধু দরকার হলে lazy init করে ──
    @property
    def screen(self):
        if self._screen is None:
            from computer_use.screen_controller import ScreenController
            self._screen = ScreenController(safety=self.safety)
        return self._screen

    # ── Browser shortcuts ────────────────────────────────────
    def start_browser(self) -> bool:
        return self.browser.start()

    def stop_browser(self) -> None:
        self.browser.close()

    def tradingview_test(self, symbol: str = "EURUSD", timeframe: str = "15") -> dict:
        """Day 45 doc-এর শেষ test সরাসরি চালাও।"""
        return self.browser.run_tradingview_test(symbol, timeframe)

    # ── Vision shortcuts ─────────────────────────────────────
    def describe_chart(self, image_path: str) -> str:
        return self.vision.analyze_chart(image_path).get("analysis", "")

    def verify(self, expected_text: str) -> bool:
        return self.vision.verify_action(expected_text).get("verified", False)