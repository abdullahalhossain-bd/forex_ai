# computer_use/mouse_agent.py  —  Day 45 (Bonus #4) | Human-like Mouse Movement
# ============================================================
# Instant teleport mouse movement বটের মতো লাগে এবং anti-bot
# detection-এ ধরা পড়ার ঝুঁকি বাড়ায়। এই module Bezier-curve path +
# variable speed + micro-jitter দিয়ে human-like movement করে।
#
# Requirements: pip install pyautogui numpy
# ============================================================

import random
import time

import numpy as np

from utils.logger import get_logger

log = get_logger("computer_use.mouse_agent")

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except Exception:
    PYAUTOGUI_AVAILABLE = False


class MouseAgent:
    """
    Human-like mouse movement + click wrapper।

    Usage:
        mouse = MouseAgent()
        mouse.move_human(800, 450)
        mouse.click_human(800, 450)
    """

    def __init__(self, base_speed: float = 1.0):
        self.base_speed = base_speed   # >1 = ধীরে, <1 = দ্রুত

    # ─────────────────────────────────────────────
    # BEZIER PATH GENERATOR
    # ─────────────────────────────────────────────

    def _bezier_path(self, start: tuple, end: tuple, steps: int = 30) -> list:
        """
        Quadratic Bezier curve — start → randomized control point → end।
        সরাসরি সরলরেখায় না গিয়ে সামান্য বাঁক নিয়ে যাবে, ঠিক মানুষের মতো।
        """
        x0, y0 = start
        x2, y2 = end

        mid_x, mid_y = (x0 + x2) / 2, (y0 + y2) / 2
        dist = max(1.0, ((x2 - x0) ** 2 + (y2 - y0) ** 2) ** 0.5)
        offset = random.uniform(-0.15, 0.15) * dist
        x1 = mid_x + offset
        y1 = mid_y - offset

        path = []
        for t in np.linspace(0, 1, steps):
            x = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * x1 + t ** 2 * x2
            y = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * y1 + t ** 2 * y2
            path.append((x, y))
        return path

    # ─────────────────────────────────────────────
    # MOVE
    # ─────────────────────────────────────────────

    def move_human(self, x: int, y: int, duration_range: tuple = (0.35, 0.9)) -> None:
        """Bezier curve বরাবর variable speed-এ mouse move করো।"""
        if not PYAUTOGUI_AVAILABLE:
            log.warning("[MouseAgent] pyautogui unavailable")
            return

        start = pyautogui.position()
        steps = random.randint(20, 35)
        path = self._bezier_path(start, (x, y), steps=steps)

        total_duration = random.uniform(*duration_range) * self.base_speed
        per_step = total_duration / steps

        for px, py in path:
            jitter_x = random.uniform(-1, 1)
            jitter_y = random.uniform(-1, 1)
            pyautogui.moveTo(px + jitter_x, py + jitter_y, duration=0)
            time.sleep(max(0, per_step + random.uniform(-per_step * 0.3, per_step * 0.3)))

        pyautogui.moveTo(x, y, duration=0)   # final snap — exact target

    # ─────────────────────────────────────────────
    # CLICK
    # ─────────────────────────────────────────────

    def click_human(self, x: int = None, y: int = None, button: str = "left") -> None:
        if not PYAUTOGUI_AVAILABLE:
            return
        if x is not None and y is not None:
            self.move_human(x, y)
        self.random_delay(0.08, 0.25)
        pyautogui.click(button=button)
        log.info(f"[MouseAgent] Human click @ ({x}, {y})")

    def double_click_human(self, x: int = None, y: int = None) -> None:
        if not PYAUTOGUI_AVAILABLE:
            return
        if x is not None and y is not None:
            self.move_human(x, y)
        self.random_delay(0.05, 0.15)
        pyautogui.doubleClick()

    def drag_human(self, x1: int, y1: int, x2: int, y2: int, button: str = "left") -> None:
        if not PYAUTOGUI_AVAILABLE:
            return
        self.move_human(x1, y1)
        pyautogui.mouseDown(button=button)
        self.move_human(x2, y2, duration_range=(0.4, 1.0))
        pyautogui.mouseUp(button=button)
        log.info(f"[MouseAgent] Human drag ({x1},{y1}) -> ({x2},{y2})")

    # ─────────────────────────────────────────────
    # DELAY
    # ─────────────────────────────────────────────

    @staticmethod
    def random_delay(min_s: float = 0.2, max_s: float = 0.6) -> None:
        time.sleep(random.uniform(min_s, max_s))