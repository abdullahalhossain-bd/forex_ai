# computer_use/vision.py  —  Day 45 (Bonus #1, #2, #3) | Vision Layer
# ============================================================
# 1) OCR Layer (Tesseract)   — screen-এর text পড়া (symbol/price/button label)
# 2) Vision-Language Agent   — screenshot Claude-কে পাঠিয়ে chart বুঝিয়ে নেওয়া
# 3) Action Verification     — কোনো action নেওয়ার পর সফল হলো কিনা OCR দিয়ে যাচাই
#
# Requirements:
#   pip install pytesseract pillow anthropic
#   Tesseract OCR engine আলাদাভাবে install করতে হবে:
#     - Ubuntu/Debian : sudo apt install tesseract-ocr
#     - Windows       : https://github.com/UB-Mannheim/tesseract/wiki
#     - macOS         : brew install tesseract
#   ANTHROPIC_API_KEY env var সেট থাকতে হবে chart-vision-এর জন্য।
# ============================================================

import base64
import os
import time

from utils.logger import get_logger

log = get_logger("computer_use.vision")

try:
    import pytesseract
    from PIL import Image
    OCR_AVAILABLE = True
except Exception as e:
    OCR_AVAILABLE = False
    log.warning(f"[Vision] pytesseract/PIL unavailable: {e}")

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except Exception:
    PYAUTOGUI_AVAILABLE = False

try:
    import anthropic
    _client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    LLM_AVAILABLE = True
except Exception:
    LLM_AVAILABLE = False
    log.warning("[Vision] anthropic package not found — Vision-LLM disabled")

MODEL = "claude-sonnet-4-6"


class VisionAgent:
    """
    Screen-এর pixel data থেকে অর্থবহ তথ্য বের করার layer।

    Usage:
        vision = VisionAgent()
        text   = vision.read_screen_text()
        found  = vision.find_text("BUY")
        ok     = vision.verify_action("M15")
        story  = vision.analyze_chart("screen.png")
    """

    # ═══════════════════════════════════════════════════════
    # 1. OCR — RAW TEXT READ
    # ═══════════════════════════════════════════════════════

    def read_screen_text(self, region: tuple = None) -> str:
        """বর্তমান screen (বা region) -এর সব text OCR দিয়ে পড়ো।"""
        if not OCR_AVAILABLE:
            log.warning("[Vision] OCR unavailable")
            return ""
        img = self._capture(region)
        text = pytesseract.image_to_string(img)
        return text.strip()

    def read_image_text(self, image_path: str) -> str:
        if not OCR_AVAILABLE:
            return ""
        img = Image.open(image_path)
        return pytesseract.image_to_string(img).strip()

    # ═══════════════════════════════════════════════════════
    # 2. FIND TEXT ON SCREEN  (location সহ)
    # ═══════════════════════════════════════════════════════

    def find_text(self, target: str, region: tuple = None, case_sensitive: bool = False):
        """
        Screen-এ একটা নির্দিষ্ট text খুঁজে তার approximate (x, y) দাও।
        Tesseract-এর image_to_data() দিয়ে word-level bounding box বের করে।
        """
        if not OCR_AVAILABLE:
            return None

        img = self._capture(region)
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

        offset_x, offset_y = (region[0], region[1]) if region else (0, 0)
        needle = target if case_sensitive else target.lower()

        for i, word in enumerate(data["text"]):
            haystack = word if case_sensitive else word.lower()
            if needle and needle in haystack:
                x = offset_x + data["left"][i] + data["width"][i] // 2
                y = offset_y + data["top"][i] + data["height"][i] // 2
                conf = float(data.get("conf", [0])[i]) if data.get("conf") else 0.0
                log.info(f"[Vision] Found text '{target}' @ ({x},{y}) conf={conf}")
                return {"found": True, "x": x, "y": y, "text": word, "confidence": conf}

        log.info(f"[Vision] Text '{target}' not found on screen")
        return None

    # ═══════════════════════════════════════════════════════
    # 3. ACTION VERIFICATION SYSTEM  ⭐⭐⭐⭐⭐
    # ═══════════════════════════════════════════════════════

    def verify_action(self, expected_text: str, region: tuple = None,
                       retries: int = 3, delay: float = 0.6) -> dict:
        """
        কোনো action (যেমন timeframe change) নেওয়ার পর সেটা সফল হলো কিনা যাচাই করো।

        Example (doc অনুযায়ী):
            AI: "Changed timeframe to H1"
            verify_action("H1") -> screen OCR করে "H1" আছে কিনা চেক করে।

        Returns:
            { "verified": bool, "attempts": int, "screen_text": str }
        """
        text = ""
        for attempt in range(1, retries + 1):
            text = self.read_screen_text(region=region)
            if expected_text.lower() in text.lower():
                log.info(f"[Vision] ✅ Verified '{expected_text}' (attempt {attempt})")
                return {"verified": True, "attempts": attempt, "screen_text": text}
            time.sleep(delay)

        log.warning(f"[Vision] ❌ Could not verify '{expected_text}' after {retries} attempts")
        return {"verified": False, "attempts": retries, "screen_text": text}

    # ═══════════════════════════════════════════════════════
    # 4. VISION-LANGUAGE MODEL — CHART UNDERSTANDING  ⭐⭐⭐⭐⭐
    # ═══════════════════════════════════════════════════════

    def analyze_chart(self, image_path: str, question: str = None) -> dict:
        """
        Screenshot/chart image Claude-কে পাঠিয়ে human-trader-এর মতো
        বিশ্লেষণ করিয়ে নাও — শুধু OpenCV/pixel matching না, প্রকৃত visual বোঝা।

        Returns:
            { "analysis": str, "error": str|None }
        """
        if not LLM_AVAILABLE:
            return {"analysis": "", "error": "anthropic package/API key unavailable"}

        if not os.path.exists(image_path):
            return {"analysis": "", "error": f"Image not found: {image_path}"}

        with open(image_path, "rb") as f:
            img_b64 = base64.standard_b64encode(f.read()).decode("utf-8")

        media_type = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"

        prompt = question or (
            "এই trading chart screenshot-টা একজন professional forex trader-এর "
            "চোখে দেখো। বলো: কোন pair/timeframe মনে হচ্ছে, current trend কী, "
            "কোনো visible support/resistance zone আছে কিনা, এবং chart-এ "
            "অস্বাভাবিক বা ঝুঁকিপূর্ণ কিছু দেখা যাচ্ছে কিনা। সংক্ষেপে ৩-৫ "
            "বাক্যে লেখো।"
        )

        try:
            response = _client.messages.create(
                model=MODEL,
                max_tokens=400,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {
                            "type": "base64", "media_type": media_type, "data": img_b64,
                        }},
                        {"type": "text", "text": prompt},
                    ],
                }],
            )
            analysis = response.content[0].text.strip()
            log.info(f"[Vision] Chart analysis received ({len(analysis)} chars)")
            return {"analysis": analysis, "error": None}
        except Exception as e:
            log.error(f"[Vision] analyze_chart error: {e}")
            return {"analysis": "", "error": str(e)}

    # ═══════════════════════════════════════════════════════
    # UTIL
    # ═══════════════════════════════════════════════════════

    def _capture(self, region: tuple = None):
        if PYAUTOGUI_AVAILABLE:
            return pyautogui.screenshot(region=region)
        raise RuntimeError("pyautogui unavailable — cannot capture screen")