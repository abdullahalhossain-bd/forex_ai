# computer_use/screen_controller.py  —  Day 45 | Screen Automation Foundation
# ============================================================
# AI Trader-এর "চোখ ও হাত"। এই module দিয়ে AI:
#   1. Screen দেখতে পারবে (screenshot)
#   2. নির্দিষ্ট window focus করতে পারবে
#   3. Mouse control করতে পারবে
#   4. Keyboard control করতে পারবে
#   5. Image matching দিয়ে button/element খুঁজে বের করতে পারবে (OpenCV)
#   6. Error হলে gracefully handle করবে (retry → screenshot → alert → stop)
#   7. SafetyLayer দিয়ে প্রতিটা click approve করিয়ে নেবে
#
# Requirements:
#   pip install pyautogui pygetwindow opencv-python pillow numpy
#
# ⚠️  এই module শুধুমাত্র একটা real desktop (GUI/display আছে এমন)
#     machine-এ কাজ করবে — headless server/container-এ চলবে না।
# ============================================================

import os
import time
from datetime import datetime, timezone

import numpy as np

from utils.logger import get_logger
from computer_use.safety import SafetyLayer

log = get_logger("computer_use.screen")

try:
    import pyautogui
    pyautogui.FAILSAFE = True       # mouse কে top-left corner-এ নিলে emergency stop
    PYAUTOGUI_AVAILABLE = True
except Exception as e:
    PYAUTOGUI_AVAILABLE = False
    log.warning(f"[ScreenController] pyautogui unavailable: {e}")

try:
    import pygetwindow as gw
    PYGETWINDOW_AVAILABLE = True
except Exception as e:
    PYGETWINDOW_AVAILABLE = False
    log.warning(f"[ScreenController] pygetwindow unavailable: {e}")

try:
    import cv2
    CV2_AVAILABLE = True
except Exception as e:
    CV2_AVAILABLE = False
    log.warning(f"[ScreenController] opencv-python unavailable: {e}")


ERROR_DIR = "computer_use/errors"


class ScreenController:
    """
    Day 45 core file। Screen দেখা, window control, mouse/keyboard,
    image matching, error handling — সব একসাথে।

    Usage:
        sc = ScreenController()
        sc.focus_window("TradingView")
        sc.screenshot("screen.png")
        match = sc.find_element("images/buy_button.png")
        if match:
            sc.click(match["x"], match["y"])
    """

    def __init__(self, safety: SafetyLayer = None, error_dir: str = ERROR_DIR):
        self.safety = safety
        self.error_dir = error_dir
        os.makedirs(self.error_dir, exist_ok=True)
        self._require_pyautogui()

    def _require_pyautogui(self):
        if not PYAUTOGUI_AVAILABLE:
            raise RuntimeError(
                "pyautogui না থাকলে ScreenController কাজ করবে না। "
                "`pip install pyautogui` করো এবং একটা GUI/display থাকা "
                "machine-এ run করো।"
            )

    # ═══════════════════════════════════════════════════════
    # 1. SCREENSHOT SYSTEM  ⭐⭐⭐⭐⭐
    # ═══════════════════════════════════════════════════════

    def screenshot(self, save_path: str = "screen.png", region: tuple = None):
        """
        Screen capture করো। region=(left, top, width, height) দিলে শুধু
        ওই অংশটুকু capture হবে।
        """
        img = pyautogui.screenshot(region=region)
        img.save(save_path)
        log.info(f"[ScreenController] Screenshot saved -> {save_path}")
        return img

    # ═══════════════════════════════════════════════════════
    # 2. WINDOW CONTROL  ⭐⭐⭐⭐⭐
    # ═══════════════════════════════════════════════════════

    def get_active_window_title(self) -> str:
        if not PYGETWINDOW_AVAILABLE:
            return ""
        try:
            win = gw.getActiveWindow()
            return win.title if win else ""
        except Exception as e:
            log.warning(f"[ScreenController] get_active_window_title error: {e}")
            return ""

    def focus_window(self, title_substring: str, retries: int = 3) -> bool:
        """
        Title-এ substring match করা প্রথম window focus করো।
        না পেলে retry করে, শেষে False return করবে + error screenshot save করে।
        """
        if not PYGETWINDOW_AVAILABLE:
            log.warning("[ScreenController] pygetwindow unavailable — cannot focus window")
            return False

        for attempt in range(1, retries + 1):
            windows = gw.getWindowsWithTitle(title_substring)
            if windows:
                try:
                    windows[0].activate()
                    time.sleep(0.5)
                    log.info(f"[ScreenController] Focused window: {windows[0].title} ✅")
                    return True
                except Exception as e:
                    log.warning(f"[ScreenController] activate() failed: {e}")
            log.info(
                f"[ScreenController] Window '{title_substring}' not found "
                f"(attempt {attempt}/{retries})"
            )
            time.sleep(1)

        self._save_error(f"window_not_found_{title_substring}")
        return False

    def list_windows(self) -> list:
        if not PYGETWINDOW_AVAILABLE:
            return []
        return [w.title for w in gw.getAllWindows() if w.title.strip()]

    # ═══════════════════════════════════════════════════════
    # 3. MOUSE CONTROL
    # ═══════════════════════════════════════════════════════

    def move_to(self, x: int, y: int, duration: float = 0.4) -> None:
        pyautogui.moveTo(x, y, duration=duration)

    def click(self, x: int = None, y: int = None, button: str = "left",
              safety_context: dict = None) -> bool:
        if not self._safety_approved("CLICK", safety_context):
            return False
        if x is not None and y is not None:
            pyautogui.click(x, y, button=button)
        else:
            pyautogui.click(button=button)
        log.info(f"[ScreenController] Click @ ({x}, {y}) button={button}")
        return True

    def double_click(self, x: int = None, y: int = None,
                      safety_context: dict = None) -> bool:
        if not self._safety_approved("DOUBLE_CLICK", safety_context):
            return False
        if x is not None and y is not None:
            pyautogui.doubleClick(x, y)
        else:
            pyautogui.doubleClick()
        log.info(f"[ScreenController] Double-click @ ({x}, {y})")
        return True

    def right_click(self, x: int = None, y: int = None,
                     safety_context: dict = None) -> bool:
        if not self._safety_approved("RIGHT_CLICK", safety_context):
            return False
        if x is not None and y is not None:
            pyautogui.rightClick(x, y)
        else:
            pyautogui.rightClick()
        return True

    def scroll(self, amount: int) -> None:
        pyautogui.scroll(amount)

    # ═══════════════════════════════════════════════════════
    # 4. KEYBOARD CONTROL
    # ═══════════════════════════════════════════════════════

    def press_key(self, key: str) -> None:
        pyautogui.press(key)
        log.info(f"[ScreenController] Key pressed: {key}")

    def hotkey(self, *keys) -> None:
        pyautogui.hotkey(*keys)
        log.info(f"[ScreenController] Hotkey: {'+'.join(keys)}")

    def write(self, text: str, interval: float = 0.03) -> None:
        pyautogui.write(text, interval=interval)
        log.info(f"[ScreenController] Typed: {text}")

    # ═══════════════════════════════════════════════════════
    # 5. IMAGE MATCHING  ⭐⭐⭐⭐⭐  (OpenCV template matching)
    # ═══════════════════════════════════════════════════════

    def find_element(
        self,
        template_path: str,
        confidence: float = 0.85,
        region: tuple = None,
        screenshot_path: str = None,
    ):
        """
        OpenCV template matching দিয়ে screen-এ একটা element (button/icon)
        খুঁজে বের করো। template_path-এ আগে থেকে crop করে save করা একটা
        button-এর ছবি (যেমন images/buy_button.png) দিতে হবে।

        Returns:
            { "found": True, "x": int, "y": int, "w": int, "h": int,
              "confidence": float }  অথবা  None  যদি না পাওয়া যায়
        """
        if not CV2_AVAILABLE:
            log.warning("[ScreenController] opencv unavailable — image matching skipped")
            return None

        if not os.path.exists(template_path):
            log.error(f"[ScreenController] Template not found: {template_path}")
            return None

        shot = pyautogui.screenshot(region=region)
        if screenshot_path:
            shot.save(screenshot_path)

        haystack = cv2.cvtColor(np.array(shot), cv2.COLOR_RGB2BGR)
        needle = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if needle is None:
            log.error(f"[ScreenController] Could not read template: {template_path}")
            return None

        result = cv2.matchTemplate(haystack, needle, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val < confidence:
            log.info(
                f"[ScreenController] '{os.path.basename(template_path)}' not found "
                f"(best match {max_val:.2f} < {confidence})"
            )
            return None

        h, w = needle.shape[:2]
        offset_x, offset_y = (region[0], region[1]) if region else (0, 0)
        center_x = offset_x + max_loc[0] + w // 2
        center_y = offset_y + max_loc[1] + h // 2

        log.info(
            f"[ScreenController] '{os.path.basename(template_path)}' FOUND "
            f"@ ({center_x},{center_y})  confidence={max_val:.2f}"
        )
        return {
            "found": True, "x": center_x, "y": center_y,
            "w": w, "h": h, "confidence": round(float(max_val), 3),
        }

    def find_all_elements(
        self, template_path: str, confidence: float = 0.85, region: tuple = None,
    ) -> list:
        """একই template-এর একাধিক instance থাকলে সবগুলো খুঁজে বের করো।"""
        if not CV2_AVAILABLE or not os.path.exists(template_path):
            return []

        shot = pyautogui.screenshot(region=region)
        haystack = cv2.cvtColor(np.array(shot), cv2.COLOR_RGB2BGR)
        needle = cv2.imread(template_path, cv2.IMREAD_COLOR)
        if needle is None:
            return []

        h, w = needle.shape[:2]
        result = cv2.matchTemplate(haystack, needle, cv2.TM_CCOEFF_NORMED)
        locations = np.where(result >= confidence)

        offset_x, offset_y = (region[0], region[1]) if region else (0, 0)
        matches = []
        for pt in zip(*locations[::-1]):
            matches.append({
                "x": offset_x + pt[0] + w // 2,
                "y": offset_y + pt[1] + h // 2,
                "w": w, "h": h,
                "confidence": round(float(result[pt[1], pt[0]]), 3),
            })

        # খুব কাছাকাছি duplicate matches বাদ দাও
        deduped = []
        for m in sorted(matches, key=lambda m: -m["confidence"]):
            if all(abs(m["x"] - d["x"]) > w / 2 or abs(m["y"] - d["y"]) > h / 2 for d in deduped):
                deduped.append(m)
        return deduped

    def click_element(
        self,
        template_path: str,
        confidence: float = 0.85,
        retries: int = 2,
        region: tuple = None,
        safety_context: dict = None,
    ) -> dict:
        """
        find_element() + click() একসাথে — retry ও error handling সহ।
        এটাই doc-এর "Buy button কোথায়?" সমস্যার সমাধান।

        Returns:
            { "success": bool, "match": dict|None, "reason": str|None }
        """
        last_reason = None
        for attempt in range(1, retries + 2):
            match = self.find_element(template_path, confidence=confidence, region=region)
            if match:
                ctx = dict(safety_context or {})
                if self.click(match["x"], match["y"], safety_context=ctx):
                    return {"success": True, "match": match, "reason": None}
                last_reason = "Blocked by SafetyLayer"
                break   # safety block হলে retry করার দরকার নেই

            last_reason = f"Element not found (attempt {attempt}/{retries + 1})"
            log.warning(f"[ScreenController] {last_reason}")
            time.sleep(0.8)

        # ── Error Handling: retry শেষে → screenshot → alert → stop ──
        self._save_error(
            f"element_not_found_{os.path.basename(template_path)}",
            reason=last_reason,
        )
        return {"success": False, "match": None, "reason": last_reason}

    # ═══════════════════════════════════════════════════════
    # 6. ERROR HANDLING  ⭐⭐⭐⭐⭐
    # ═══════════════════════════════════════════════════════

    def _save_error(self, tag: str, reason: str = None) -> str:
        """
        Element না পাওয়া গেলে / action fail করলে:
        screenshot save করো + log করো (alert hook এখানে যোগ করা যাবে)।
        """
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.error_dir, f"{ts}_{tag}.png")
        try:
            pyautogui.screenshot().save(path)
        except Exception as e:
            log.error(f"[ScreenController] Could not save error screenshot: {e}")
            path = None

        log.error(f"[ScreenController] ❌ ERROR — {tag} | reason={reason} | screenshot={path}")
        return path

    # ═══════════════════════════════════════════════════════
    # SAFETY HOOK
    # ═══════════════════════════════════════════════════════

    def _safety_approved(self, action: str, safety_context: dict) -> bool:
        if not self.safety:
            return True   # SafetyLayer attach করা না থাকলে block করবে না
        ctx = dict(safety_context or {})
        ctx.setdefault("action", action)
        ctx.setdefault("active_window", self.get_active_window_title())
        decision = self.safety.check_before_click(ctx)
        if not decision["approved"]:
            self._save_error(f"safety_blocked_{action}", reason="; ".join(decision["reasons"]))
        return decision["approved"]