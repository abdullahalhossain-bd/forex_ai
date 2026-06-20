# computer_use/drawing_tools.py  —  Day 48 | TradingView Drawing Tool Actions
# ============================================================
# coordinate_mapper.py শুধু "কোথায়" বলে (pixel কোথায়)। এই ফাইল বলে
# "কীভাবে" — কোন TradingView tool select করতে হবে, কীভাবে click/drag
# করলে সেই tool দিয়ে আসলে drawing object তৈরি হয়।
#
# Day 46 BrowserController-এর উপর বসে কাজ করে (controller.click,
# controller.page.mouse, controller.press_key ইত্যাদি ব্যবহার করে) —
# নতুন browser engine বানানো হয়নি, existing infra reuse করা হয়েছে।
#
# Tool selection দুইভাবে সম্ভব (TradingView keyboard shortcut সবচেয়ে
# reliable, doc-এর Section 6 অনুযায়ী toolbar selector ব্যবহার করাও
# রাখা হলো fallback হিসেবে):
#
#   Horizontal Line  →  "Alt+H"  (keyboard)  /  data-name="horizontal-line"
#   Trend Line       →  "Alt+T"  (keyboard)  /  data-name="trend-line"
#   Fibonacci        →  "Alt+F"  (keyboard)  /  data-name="fib-retracement"
#
# ⚠️ TradingView shortcut/selector সময়ের সাথে বদলাতে পারে — bদলে গেলে
#    browser-এর Inspect Element দিয়ে নতুন data-name/shortcut বের করে
#    TOOL_SHORTCUTS / TOOL_SELECTORS dict আপডেট করো।
# ============================================================

import time

from utils.logger import get_logger

log = get_logger("computer_use.drawing_tools")

# Keyboard shortcut (TradingView default) — primary method
TOOL_SHORTCUTS = {
    "horizontal_line": "h",          # doc-এর own example shortcut-ও "h"
    "trend_line":      "alt+t",
    "fibonacci":       "alt+f",
}

# Toolbar button selector — keyboard shortcut কাজ না করলে fallback
TOOL_SELECTORS = {
    "horizontal_line": '[data-name="horizontal-line"]',
    "trend_line":      '[data-name="trend-line"]',
    "fibonacci":       '[data-name="fib-retracement"]',
}


class DrawingTools:
    """
    TradingView-এর drawing toolbar control করার লো-লেভেল layer।

    Usage:
        tools = DrawingTools(controller=browser_controller)
        tools.select_tool("horizontal_line")
        tools.click_point(x, y)
        tools.deselect_tool()
    """

    def __init__(self, controller):
        """controller: Day 46 BrowserController instance"""
        self.controller = controller
        self.page = controller.page

    # ═══════════════════════════════════════════════════════
    # 1. TOOL SELECTION  (doc Section 6)
    # ═══════════════════════════════════════════════════════

    def select_tool(self, tool_name: str, retries: int = 1) -> bool:
        """
        tool_name: "horizontal_line" | "trend_line" | "fibonacci"

        প্রথমে keyboard shortcut চেষ্টা করে (faster, more reliable),
        fail করলে toolbar selector click চেষ্টা করে।
        """
        if tool_name not in TOOL_SHORTCUTS:
            log.error(f"[DrawingTools] Unknown tool: {tool_name}")
            return False

        # Chart-এ focus আছে কিনা নিশ্চিত করো (নাহলে shortcut কাজ করবে না)
        self._ensure_chart_focus()

        for attempt in range(1, retries + 2):
            ok = self._select_via_shortcut(tool_name)
            if not ok:
                ok = self._select_via_toolbar(tool_name)

            if ok:
                log.info(f"[DrawingTools] Tool selected: {tool_name} ✅ (attempt {attempt})")
                return True

            log.warning(f"[DrawingTools] Tool select failed: {tool_name} (attempt {attempt})")
            time.sleep(0.6)

        return False

    def _select_via_shortcut(self, tool_name: str) -> bool:
        try:
            shortcut = TOOL_SHORTCUTS[tool_name]
            if "+" in shortcut:
                parts = [p.capitalize() if p != "alt" else "Alt" for p in shortcut.split("+")]
                self.page.keyboard.press("+".join(parts))
            else:
                self.page.keyboard.press(shortcut)
            time.sleep(0.5)
            return True
        except Exception as e:
            log.warning(f"[DrawingTools] Shortcut select error ({tool_name}): {e}")
            return False

    def _select_via_toolbar(self, tool_name: str) -> bool:
        try:
            selector = TOOL_SELECTORS[tool_name]
            el = self.page.locator(selector).first
            el.wait_for(timeout=3000)
            el.click()
            time.sleep(0.5)
            return True
        except Exception as e:
            log.warning(f"[DrawingTools] Toolbar select error ({tool_name}): {e}")
            return False

    def deselect_tool(self) -> None:
        """Drawing শেষ হলে Escape দিয়ে tool deselect করো (Cursor mode-এ ফেরা)।"""
        try:
            self.page.keyboard.press("Escape")
            time.sleep(0.3)
        except Exception as e:
            log.warning(f"[DrawingTools] deselect error: {e}")

    def _ensure_chart_focus(self) -> None:
        """Tool shortcut কাজ করার জন্য chart canvas-এ একটা harmless click দিয়ে focus আনো।"""
        try:
            from computer_use.coordinate_mapper import CHART_CONTAINER_SELECTORS
            for sel in CHART_CONTAINER_SELECTORS:
                el = self.page.locator(sel).first
                if el.is_visible(timeout=1000):
                    box = el.bounding_box()
                    if box:
                        # Chart-এর একদম মাঝখানে নিরীহ click (কোনো candle/object না ছুঁয়ে)
                        cx = box["x"] + box["width"] * 0.5
                        cy = box["y"] + box["height"] * 0.9
                        self.page.mouse.click(cx, cy)
                        time.sleep(0.2)
                        return
        except Exception as e:
            log.warning(f"[DrawingTools] chart focus error: {e}")

    # ═══════════════════════════════════════════════════════
    # 2. SINGLE-CLICK DRAW  (Horizontal Line)
    # ═══════════════════════════════════════════════════════

    def click_point(self, x: float, y: float) -> bool:
        """
        Horizontal line-এর জন্য একটাই click লাগে — TradingView পুরো
        chart width জুড়ে নিজেই line টেনে দেয়।
        """
        try:
            self.page.mouse.click(x, y)
            time.sleep(0.5)
            log.info(f"[DrawingTools] Click @ ({x}, {y})")
            return True
        except Exception as e:
            log.error(f"[DrawingTools] click_point error: {e}")
            return False

    # ═══════════════════════════════════════════════════════
    # 3. CLICK + DRAG  (Trend Line / Fibonacci — দুই প্রান্ত লাগে)
    # ═══════════════════════════════════════════════════════

    def drag_between(self, x1: float, y1: float, x2: float, y2: float,
                      steps: int = 12, hold_ms: float = 0.05) -> bool:
        """
        Doc flow (Trend Line ও Fibonacci দুটোর জন্যই একই pattern):
            moveTo(point1) → mouseDown → moveTo(point2) (multi-step) →
            mouseUp

        Multi-step move করা হয় কারণ TradingView কিছু drawing tool
        instant-jump দিয়ে drag detect করে না — মাঝের movement events
        দরকার হয়।
        """
        try:
            self.page.mouse.move(x1, y1)
            time.sleep(0.2)
            self.page.mouse.down()
            time.sleep(0.15)

            for i in range(1, steps + 1):
                t = i / steps
                ix = x1 + (x2 - x1) * t
                iy = y1 + (y2 - y1) * t
                self.page.mouse.move(ix, iy)
                time.sleep(hold_ms)

            self.page.mouse.up()
            time.sleep(0.5)

            log.info(
                f"[DrawingTools] Drag ({x1:.0f},{y1:.0f}) → ({x2:.0f},{y2:.0f}) ✅"
            )
            return True
        except Exception as e:
            log.error(f"[DrawingTools] drag_between error: {e}")
            return False

    # ═══════════════════════════════════════════════════════
    # 4. HIGH-LEVEL DRAW ACTIONS  (tool select + draw একসাথে)
    # ═══════════════════════════════════════════════════════

    def draw_horizontal_line(self, x: float, y: float) -> dict:
        """Support/Resistance horizontal line — single click।"""
        if not self.select_tool("horizontal_line"):
            return {"success": False, "reason": "tool_select_failed"}

        ok = self.click_point(x, y)
        self.deselect_tool()
        return {"success": ok, "point": (x, y)}

    def draw_trend_line(self, x1: float, y1: float, x2: float, y2: float) -> dict:
        """Uptrend/downtrend line — drag between two swing points।"""
        if not self.select_tool("trend_line"):
            return {"success": False, "reason": "tool_select_failed"}

        ok = self.drag_between(x1, y1, x2, y2)
        self.deselect_tool()
        return {"success": ok, "points": [(x1, y1), (x2, y2)]}

    def draw_fibonacci(self, x_high: float, y_high: float, x_low: float, y_low: float,
                        direction: str = "high_to_low") -> dict:
        """
        Fibonacci retracement — doc flow: swing high click → drag → swing
        low release (uptrend retracement) অথবা reverse (downtrend)।

        direction: "high_to_low" (uptrend-এর retracement আঁকার সময়
                    standard) | "low_to_high" (downtrend bounce)
        """
        if not self.select_tool("fibonacci"):
            return {"success": False, "reason": "tool_select_failed"}

        if direction == "high_to_low":
            ok = self.drag_between(x_high, y_high, x_low, y_low)
        else:
            ok = self.drag_between(x_low, y_low, x_high, y_high)

        self.deselect_tool()
        return {"success": ok, "high_point": (x_high, y_high), "low_point": (x_low, y_low)}

    # ═══════════════════════════════════════════════════════
    # 5. CLEANUP  (Auto Cleanup bonus-এ দরকার হবে)
    # ═══════════════════════════════════════════════════════

    def remove_all_drawings(self) -> bool:
        """
        TradingView toolbar-এর "Remove drawings" button / right-click
        menu ব্যবহার করে chart clean করো। Auto Cleanup bonus feature
        chart_drawer.py থেকে call করে।
        """
        try:
            # Toolbar trash icon (object-tree বা drawing-toolbar-এ থাকে)
            selectors = [
                '[data-name="remove-drawing-tools"]',
                'button[title="Remove Drawings"]',
                '[data-tooltip="Remove Drawings"]',
            ]
            for sel in selectors:
                el = self.page.locator(sel).first
                if el.is_visible(timeout=1500):
                    el.click()
                    time.sleep(0.5)
                    log.info("[DrawingTools] All drawings removed ✅")
                    return True

            log.warning("[DrawingTools] Remove-drawings button not found")
            return False
        except Exception as e:
            log.error(f"[DrawingTools] remove_all_drawings error: {e}")
            return False

    def undo(self) -> bool:
        """Mistake Recovery — ভুল drawing হলে Ctrl+Z দিয়ে undo করো।"""
        try:
            self.page.keyboard.press("Control+Z")
            time.sleep(0.4)
            log.info("[DrawingTools] Undo ✅")
            return True
        except Exception as e:
            log.error(f"[DrawingTools] undo error: {e}")
            return False