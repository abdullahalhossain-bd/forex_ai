# computer_use/chart_drawer.py  —  Day 48 | Chart Drawing Automation (AI Hands Upgrade) ⭐
# ============================================================
# Day 45-47 শেষে AI-এর ছিল:
#   🧠 Brain  — Analysis (Day 1-44)
#   👁️ Eyes   — Chart vision (Day 47)
#   🖐️ Hands  — Browser + Mouse control (Day 45-46)
#
# Day 48-এ AI প্রথমবার নিজের analysis নিয়ে TradingView chart-এর উপর
# সরাসরি আঁকবে — মানুষ trader যেমন করে।
#
# Pipeline (doc অনুযায়ী):
#   AI analysis (price levels)
#         ↓
#   CoordinateMapper   — price → pixel  (coordinate_mapper.py)
#         ↓
#   DrawingTools        — tool select + mouse click/drag  (drawing_tools.py)
#         ↓
#   DrawingVerifier      — সত্যিই আঁকা হলো কিনা যাচাই  (drawing_verifier.py)
#         ↓
#   Mistake Recovery     — fail হলে undo → recalibrate → retry
#
# Bonus (10/10 checklist — সবগুলো এই ফাইলে আছে):
#   ⭐ Drawing Memory       — কোথায় কোথায় draw করেছে, history.json-এ save
#   ⭐ Auto Cleanup         — চার্ট clutter হলে পুরোনো drawing সরিয়ে দেয়
#   ⭐ Drawing Confidence   — প্রতিটা drawing-এর strength score (0-100)
#   ⭐ Human Confirmation   — AUTO_MODE (সরাসরি আঁকো) vs APPROVAL_MODE
#                             (আঁকার আগে human approval লাগবে)
#
# Day 46 (TradingViewAgent/BrowserController), Day 47 (ImageCapture/
# VisionAnalyzer) — সবকিছু reuse করা হয়েছে, নতুন browser engine বানানো
# হয়নি।
# ============================================================

import json
import os
import time
from datetime import datetime, timezone
from enum import Enum

from utils.logger import get_logger
from computer_use.coordinate_mapper import CoordinateMapper
from computer_use.drawing_tools import DrawingTools
from computer_use.drawing_verifier import DrawingVerifier

log = get_logger("computer_use.chart_drawer")

DRAWING_MEMORY_PATH = "memory/drawing_history.json"
MAX_DRAWINGS_BEFORE_CLEANUP = 12   # এর বেশি drawing হয়ে গেলে auto-cleanup trigger করবে


class DrawMode(str, Enum):
    """Bonus #4 — Human Confirmation Mode।"""
    AUTO = "AUTO"           # সরাসরি draw করে দেবে
    APPROVAL = "APPROVAL"   # draw করার আগে human approval লাগবে (callback/flag দিয়ে)


class ChartDrawer:
    """
    Day 48 Main Orchestrator।

    Usage:
        from computer_use.tradingview_agent import TradingViewAgent
        tv = TradingViewAgent()
        tv.start()
        tv.open_chart("EURUSD")

        drawer = ChartDrawer(tv_agent=tv, mode=DrawMode.AUTO)

        drawer.draw_support_resistance(
            symbol="EURUSD", timeframe="H1",
            support=1.0850, resistance=1.0900,
            current_price=1.0875,
        )

        drawer.draw_fibonacci(
            symbol="EURUSD", timeframe="H1",
            swing_high=1.1000, swing_low=1.0800,
            current_price=1.0875,
        )

        # Master Agent JSON command (doc Section 9):
        drawer.execute_command({
            "action": "DRAW",
            "objects": [
                {"type": "support", "price": 1.0850},
                {"type": "fibonacci", "high": 1.1000, "low": 1.0800},
            ],
        }, symbol="EURUSD", timeframe="H1", current_price=1.0875)
    """

    def __init__(self, tv_agent=None, controller=None, mode: DrawMode = DrawMode.AUTO,
                 approval_callback=None, memory_path: str = DRAWING_MEMORY_PATH):
        """
        tv_agent : Day 46 TradingViewAgent (preferred — already has safety + controller)
        controller: ঐচ্ছিক, tv_agent না দিলে সরাসরি BrowserController দাও
        mode     : DrawMode.AUTO | DrawMode.APPROVAL
        approval_callback: APPROVAL mode-এ call হবে — callback(plan: dict) -> bool
                            না দিলে APPROVAL mode-এ সবসময় False (draw হবে না, শুধু
                            pending plan জমা থাকবে — যাতে accidental live-drawing না হয়)
        """
        self.tv_agent = tv_agent
        self.controller = controller or (tv_agent.controller if tv_agent else None)
        if self.controller is None:
            raise ValueError("ChartDrawer-এর জন্য tv_agent বা controller — একটা লাগবেই")

        self.mode = mode
        self.approval_callback = approval_callback
        self.memory_path = memory_path

        self.mapper = CoordinateMapper(controller=self.controller)
        self.tools = DrawingTools(controller=self.controller)
        self.verifier = DrawingVerifier(controller=self.controller, mapper=self.mapper)

        self._pending_approvals: list = []   # APPROVAL mode-এ আটকে থাকা plan গুলো
        os.makedirs(os.path.dirname(self.memory_path) or ".", exist_ok=True)

    # ═══════════════════════════════════════════════════════
    # 1. SUPPORT & RESISTANCE  (doc Section 1)
    # ═══════════════════════════════════════════════════════

    def draw_support_resistance(
        self,
        symbol: str,
        timeframe: str,
        support: float = None,
        resistance: float = None,
        current_price: float = None,
    ) -> dict:
        """
        Doc flow:
            Python Analysis → Price Level → price→screen coordinate →
            mouse click+drag → Line drawn
        """
        results = []

        if not self._calibrate(current_price):
            return self._fail_result("calibration_failed")

        if support is not None:
            results.append(self._draw_single_level(
                symbol, timeframe, level_type="support", price=support,
                strength_factors={"zone_type": "support"},
            ))

        if resistance is not None:
            results.append(self._draw_single_level(
                symbol, timeframe, level_type="resistance", price=resistance,
                strength_factors={"zone_type": "resistance"},
            ))

        all_ok = all(r.get("success") for r in results) if results else False
        log.info(
            f"[ChartDrawer] S/R draw complete | support={'✅' if support else '—'} "
            f"resistance={'✅' if resistance else '—'} | all_ok={all_ok}"
        )
        return {"success": all_ok, "results": results}

    def _draw_single_level(
        self, symbol: str, timeframe: str, level_type: str,
        price: float, strength_factors: dict = None,
    ) -> dict:
        plan = {
            "type": level_type,
            "price": price,
            "symbol": symbol,
            "timeframe": timeframe,
        }

        # Bonus #4 — Approval gate
        approved, gate_result = self._approval_gate(plan)
        if not approved:
            return gate_result

        before_count = self.verifier.count_drawing_objects()

        def _attempt():
            x, y = self.mapper.price_to_pixel(price)
            return self.tools.draw_horizontal_line(x, y)

        draw_result = self._with_drawing_recovery(_attempt, action_name=f"draw_{level_type}")

        verify_result = self.verifier.verify(
            before_count=before_count, symbol=symbol, timeframe=timeframe,
            drawing_type=f"{level_type} horizontal line", expected_price=price,
        )

        confidence = self._calculate_drawing_confidence(
            draw_result=draw_result, verify_result=verify_result,
            strength_factors=strength_factors or {},
        )

        entry = self._record_drawing(
            symbol=symbol, timeframe=timeframe, draw_type=level_type,
            price=price, verified=verify_result.get("final_verified", False),
            confidence=confidence,
        )

        self._maybe_auto_cleanup(symbol, timeframe)

        result = {
            "success": draw_result.get("success", False) and verify_result.get("final_verified", False),
            "type": level_type, "price": price,
            "confidence": confidence, "verification": verify_result,
            "memory_entry": entry,
        }
        icon = "✅" if result["success"] else "⚠️"
        log.info(f"[ChartDrawer] {icon} {level_type} @ {price} | confidence={confidence}%")
        return result

    # ═══════════════════════════════════════════════════════
    # 2. TREND LINE  (doc Section 4)
    # ═══════════════════════════════════════════════════════

    def draw_trend_line(
        self,
        symbol: str,
        timeframe: str,
        point1: dict,   # {"price": float, "candles_back": int}
        point2: dict,   # {"price": float, "candles_back": int}
        current_price: float = None,
        structure: str = None,   # "higher_high_higher_low" | "lower_high_lower_low" ইত্যাদি
    ) -> dict:
        """
        Doc flow:
            Market structure (HH/HL) → point1=(candle1,time1),
            point2=(candle2,time2) → pixel coordinate → moveTo()/dragTo()
        """
        plan = {
            "type": "trend_line", "point1": point1, "point2": point2,
            "symbol": symbol, "timeframe": timeframe, "structure": structure,
        }
        approved, gate_result = self._approval_gate(plan)
        if not approved:
            return gate_result

        if not self._calibrate(current_price):
            return self._fail_result("calibration_failed")

        before_count = self.verifier.count_drawing_objects()

        def _attempt():
            x1, y1 = self.mapper.price_to_pixel(
                point1["price"], x=self.mapper.candle_index_to_x(point1.get("candles_back", 20))
            )
            x2, y2 = self.mapper.price_to_pixel(
                point2["price"], x=self.mapper.candle_index_to_x(point2.get("candles_back", 0))
            )
            return self.tools.draw_trend_line(x1, y1, x2, y2)

        draw_result = self._with_drawing_recovery(_attempt, action_name="draw_trend_line")

        verify_result = self.verifier.verify(
            before_count=before_count, symbol=symbol, timeframe=timeframe,
            drawing_type="trend line",
        )

        confidence = self._calculate_drawing_confidence(
            draw_result=draw_result, verify_result=verify_result,
            strength_factors={"structure": structure},
        )

        entry = self._record_drawing(
            symbol=symbol, timeframe=timeframe, draw_type="trend_line",
            price=None, verified=verify_result.get("final_verified", False),
            confidence=confidence, extra={"point1": point1, "point2": point2, "structure": structure},
        )

        self._maybe_auto_cleanup(symbol, timeframe)

        result = {
            "success": draw_result.get("success", False) and verify_result.get("final_verified", False),
            "type": "trend_line", "confidence": confidence,
            "verification": verify_result, "memory_entry": entry,
        }
        icon = "✅" if result["success"] else "⚠️"
        log.info(f"[ChartDrawer] {icon} Trend line drawn | confidence={confidence}%")
        return result

    # ═══════════════════════════════════════════════════════
    # 3. FIBONACCI RETRACEMENT  (doc Section 5)
    # ═══════════════════════════════════════════════════════

    FIB_LEVELS = [0.236, 0.382, 0.5, 0.618, 0.786]

    def draw_fibonacci(
        self,
        symbol: str,
        timeframe: str,
        swing_high: float,
        swing_low: float,
        current_price: float = None,
        candles_back_high: int = 30,
        candles_back_low: int = 0,
        confluence_with_sr: bool = None,
    ) -> dict:
        """
        Doc flow:
            Swing High + Swing Low → calculate 23.6/38.2/50/61.8/78.6% →
            select Fib tool → click swing high → drag to swing low → release
        """
        plan = {
            "type": "fibonacci", "high": swing_high, "low": swing_low,
            "symbol": symbol, "timeframe": timeframe,
        }
        approved, gate_result = self._approval_gate(plan)
        if not approved:
            return gate_result

        if not self._calibrate(current_price or swing_high):
            return self._fail_result("calibration_failed")

        fib_range = swing_high - swing_low
        fib_levels = {
            f"{int(level * 1000) / 10}%": round(swing_high - fib_range * level, 5)
            for level in self.FIB_LEVELS
        }

        before_count = self.verifier.count_drawing_objects()

        def _attempt():
            x_high, y_high = self.mapper.price_to_pixel(
                swing_high, x=self.mapper.candle_index_to_x(candles_back_high)
            )
            x_low, y_low = self.mapper.price_to_pixel(
                swing_low, x=self.mapper.candle_index_to_x(candles_back_low)
            )
            return self.tools.draw_fibonacci(x_high, y_high, x_low, y_low)

        draw_result = self._with_drawing_recovery(_attempt, action_name="draw_fibonacci")

        verify_result = self.verifier.verify(
            before_count=before_count, symbol=symbol, timeframe=timeframe,
            drawing_type="fibonacci retracement",
        )

        confidence = self._calculate_drawing_confidence(
            draw_result=draw_result, verify_result=verify_result,
            strength_factors={"confluence_with_sr": confluence_with_sr},
        )

        entry = self._record_drawing(
            symbol=symbol, timeframe=timeframe, draw_type="fibonacci",
            price=None, verified=verify_result.get("final_verified", False),
            confidence=confidence,
            extra={"swing_high": swing_high, "swing_low": swing_low, "levels": fib_levels},
        )

        self._maybe_auto_cleanup(symbol, timeframe)

        result = {
            "success": draw_result.get("success", False) and verify_result.get("final_verified", False),
            "type": "fibonacci", "levels": fib_levels, "confidence": confidence,
            "verification": verify_result, "memory_entry": entry,
        }
        icon = "✅" if result["success"] else "⚠️"
        log.info(f"[ChartDrawer] {icon} Fibonacci drawn {swing_high}→{swing_low} | confidence={confidence}%")
        return result

    # ═══════════════════════════════════════════════════════
    # 4. AI COMMAND INTERFACE  (doc Section 9) ⭐⭐⭐⭐⭐
    # ═══════════════════════════════════════════════════════

    def execute_command(self, command: dict, symbol: str, timeframe: str,
                         current_price: float = None) -> dict:
        """
        Master Agent থেকে আসা JSON command সরাসরি execute করো।

        Example (doc-এর হুবহু):
            {
              "action": "DRAW",
              "objects": [
                {"type": "support", "price": 1.0850},
                {"type": "fibonacci", "high": 1.1000, "low": 1.0800}
              ]
            }
        """
        action = (command.get("action") or "").upper()
        log.info(f"[ChartDrawer] Command received: {command}")

        if action != "DRAW":
            return {"success": False, "reason": f"Unknown action: {action}"}

        objects = command.get("objects", [])
        results = []

        for obj in objects:
            obj_type = (obj.get("type") or "").lower()

            if obj_type == "support":
                r = self.draw_support_resistance(
                    symbol, timeframe, support=obj["price"], current_price=current_price
                )
            elif obj_type == "resistance":
                r = self.draw_support_resistance(
                    symbol, timeframe, resistance=obj["price"], current_price=current_price
                )
            elif obj_type == "trend_line":
                r = self.draw_trend_line(
                    symbol, timeframe, point1=obj["point1"], point2=obj["point2"],
                    current_price=current_price,
                )
            elif obj_type == "fibonacci":
                r = self.draw_fibonacci(
                    symbol, timeframe, swing_high=obj["high"], swing_low=obj["low"],
                    current_price=current_price,
                )
            else:
                r = {"success": False, "reason": f"Unknown object type: {obj_type}"}

            results.append({"object": obj, "result": r})
            print(f"Executing...\n{obj_type.capitalize()} {'drawn ✅' if r.get('success') else 'failed ❌'}")

        all_ok = all(r["result"].get("success") for r in results) if results else False
        return {"success": all_ok, "objects_drawn": len(results), "results": results}

    # ═══════════════════════════════════════════════════════
    # 5. MISTAKE RECOVERY  (doc Section 8)
    # ═══════════════════════════════════════════════════════

    def _with_drawing_recovery(self, attempt_fn, action_name: str,
                                max_retries: int = 2, wait_seconds: float = 1.5) -> dict:
        """
        Doc flow: ভুল tool select / mouse position ভুল / chart move →
        Undo → Recalculate → Retry।
        """
        last_result = {"success": False}
        for attempt in range(1, max_retries + 2):
            try:
                last_result = attempt_fn()
                if last_result.get("success"):
                    if attempt > 1:
                        log.info(f"[ChartDrawer] '{action_name}' recovered on attempt {attempt}")
                    return last_result
            except Exception as e:
                log.warning(f"[ChartDrawer] '{action_name}' exception (attempt {attempt}): {e}")
                last_result = {"success": False, "reason": str(e)}

            log.warning(f"[ChartDrawer] '{action_name}' failed (attempt {attempt}) — recovering")
            self.tools.undo()
            self.tools.deselect_tool()
            time.sleep(wait_seconds)
            self.mapper.calibrate()   # chart move/scroll হয়ে থাকতে পারে — recalculate

        log.error(f"[ChartDrawer] 🚨 '{action_name}' permanently failed after recovery attempts")
        return last_result

    # ═══════════════════════════════════════════════════════
    # 6. CALIBRATION HELPER
    # ═══════════════════════════════════════════════════════

    def _calibrate(self, fallback_price: float = None) -> bool:
        cal = self.mapper.recalibrate_if_stale(fallback_price=fallback_price)
        if not cal.get("success"):
            log.error(f"[ChartDrawer] Calibration failed: {cal.get('reason')}")
            return False
        return True

    # ═══════════════════════════════════════════════════════
    # BONUS #1 — DRAWING MEMORY  ⭐
    # ═══════════════════════════════════════════════════════

    def _record_drawing(self, symbol, timeframe, draw_type, price,
                         verified, confidence, extra: dict = None) -> dict:
        """
        কোন zone-এ আগে draw করা হয়েছে — পরে duplicate draw এড়াতে ও
        AI-কে context দিতে save করা হয়।
        """
        entry = {
            "id": self._next_id(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "timeframe": timeframe,
            "type": draw_type,
            "price": price,
            "verified": verified,
            "confidence": confidence,
            "extra": extra or {},
        }
        history = self._load_memory()
        history.append(entry)
        self._save_memory(history)
        log.info(f"[ChartDrawer] 🧠 Drawing memory saved: #{entry['id']} {draw_type}@{price}")
        return entry

    def get_drawing_history(self, symbol: str = None, timeframe: str = None,
                             draw_type: str = None, limit: int = 50) -> list:
        history = self._load_memory()
        filtered = [
            h for h in history
            if (symbol is None or h["symbol"] == symbol)
            and (timeframe is None or h["timeframe"] == timeframe)
            and (draw_type is None or h["type"] == draw_type)
        ]
        return filtered[-limit:]

    def has_drawn_near(self, symbol: str, timeframe: str, price: float,
                        tolerance_pct: float = 0.001) -> bool:
        """
        একই zone-এ আগে draw করা হয়েছে কিনা — duplicate clutter এড়াতে
        ChartDrawer-এর caller (Master Agent) চাইলে এটা check করে skip
        করতে পারে drawing আগে।
        """
        history = self.get_drawing_history(symbol=symbol, timeframe=timeframe)
        for h in history:
            if h.get("price") is None:
                continue
            if abs(h["price"] - price) / price <= tolerance_pct:
                return True
        return False

    def _load_memory(self) -> list:
        if not os.path.exists(self.memory_path):
            return []
        try:
            with open(self.memory_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _save_memory(self, history: list) -> None:
        try:
            with open(self.memory_path, "w", encoding="utf-8") as f:
                json.dump(history[-500:], f, indent=2, default=str)   # শেষ ৫০০টা রাখো
        except Exception as e:
            log.error(f"[ChartDrawer] Could not save drawing memory: {e}")

    def _next_id(self) -> int:
        history = self._load_memory()
        return (history[-1]["id"] + 1) if history else 1

    # ═══════════════════════════════════════════════════════
    # BONUS #2 — AUTO CLEANUP  ⭐
    # ═══════════════════════════════════════════════════════

    def _maybe_auto_cleanup(self, symbol: str, timeframe: str) -> None:
        """
        Chart clutter হলে (একই pair/timeframe-এ অনেক drawing জমে গেলে)
        পুরোনো drawing গুলো সরিয়ে দাও।
        """
        recent = self.get_drawing_history(symbol=symbol, timeframe=timeframe)
        if len(recent) >= MAX_DRAWINGS_BEFORE_CLEANUP:
            log.info(
                f"[ChartDrawer] 🧹 Auto cleanup triggered — {len(recent)} drawings "
                f"on {symbol} {timeframe} (limit {MAX_DRAWINGS_BEFORE_CLEANUP})"
            )
            self.cleanup_chart(symbol, timeframe)

    def cleanup_chart(self, symbol: str = None, timeframe: str = None) -> dict:
        """
        Chart canvas থেকে সব drawing remove করো + memory-তে cleanup
        event log করো (history পুরোপুরি মুছে ফেলা হয় না — শুধু
        "active" track করা সহজ করার জন্য একটা cleanup marker যোগ হয়)।
        """
        ok = self.tools.remove_all_drawings()
        if ok:
            history = self._load_memory()
            history.append({
                "id": self._next_id(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "symbol": symbol, "timeframe": timeframe,
                "type": "cleanup_event", "price": None,
                "verified": True, "confidence": None, "extra": {},
            })
            self._save_memory(history)
        log.info(f"[ChartDrawer] Cleanup {'✅ done' if ok else '❌ failed'} for {symbol} {timeframe}")
        return {"success": ok}

    # ═══════════════════════════════════════════════════════
    # BONUS #3 — DRAWING CONFIDENCE  ⭐
    # ═══════════════════════════════════════════════════════

    def _calculate_drawing_confidence(self, draw_result: dict, verify_result: dict,
                                       strength_factors: dict = None) -> int:
        """
        Doc example:
            Support Zone: Strength 87% | Reason: Multiple rejection + Fib confluence

        এখানে confidence দুই ভাগে বিভক্ত:
          1. Execution confidence — draw + verify আসলে successful হলো কিনা
          2. Setup-strength bonus — confluence factor (S/R+Fib একসাথে,
             trend structure ইত্যাদি) caller থেকে strength_factors দিয়ে
             pass করলে bonus যুক্ত হয়
        """
        strength_factors = strength_factors or {}
        score = 0

        if draw_result.get("success"):
            score += 50
        if verify_result.get("final_verified"):
            score += 30
        elif verify_result.get("method") == "vision_fallback":
            score += 10   # vision দিয়ে partial confirm হলেও কিছুটা credit

        # Confluence bonuses
        if strength_factors.get("confluence_with_sr"):
            score += 15
        if strength_factors.get("structure") in (
            "higher_high_higher_low", "lower_high_lower_low"
        ):
            score += 10
        if strength_factors.get("zone_type") in ("support", "resistance"):
            score += 5   # basic S/R recognition bonus

        return max(0, min(99, score))

    # ═══════════════════════════════════════════════════════
    # BONUS #4 — HUMAN CONFIRMATION MODE  ⭐
    # ═══════════════════════════════════════════════════════

    def _approval_gate(self, plan: dict) -> tuple:
        """
        AUTO_MODE  → সরাসরি (True, None) — draw এগিয়ে যাবে।
        APPROVAL_MODE → approval_callback(plan) call করো:
            callback True ফেরালে  → draw এগিয়ে যাবে
            callback False/None   → pending list-এ রেখে blocked result ফেরাবে
        """
        if self.mode == DrawMode.AUTO:
            return True, None

        # APPROVAL_MODE
        approved = False
        if self.approval_callback:
            try:
                approved = bool(self.approval_callback(plan))
            except Exception as e:
                log.warning(f"[ChartDrawer] approval_callback error: {e}")
                approved = False

        if approved:
            log.info(f"[ChartDrawer] ✅ Approved by human: {plan}")
            return True, None

        self._pending_approvals.append(plan)
        log.info(f"[ChartDrawer] ⏸️  Awaiting human approval (queued): {plan}")
        return False, {
            "success": False, "reason": "awaiting_approval",
            "pending_plan": plan,
        }

    def get_pending_approvals(self) -> list:
        return list(self._pending_approvals)

    def set_mode(self, mode: DrawMode) -> None:
        self.mode = mode
        log.info(f"[ChartDrawer] Mode switched → {mode}")

    # ═══════════════════════════════════════════════════════
    # UTIL
    # ═══════════════════════════════════════════════════════

    def _fail_result(self, reason: str) -> dict:
        return {"success": False, "reason": reason}

    def print_summary(self, symbol: str = None, timeframe: str = None, limit: int = 10) -> None:
        bar = "═" * 58
        history = self.get_drawing_history(symbol=symbol, timeframe=timeframe, limit=limit)
        print(f"\n{bar}")
        print("  ✏️   CHART DRAWER  (Day 48)")
        print(bar)
        print(f"  Mode            : {self.mode}")
        print(f"  Pending approval: {len(self._pending_approvals)}")
        print(f"  Recent drawings : {len(history)}")
        for h in history[-limit:]:
            icon = "✅" if h.get("verified") else "❌"
            conf = f"{h.get('confidence')}%" if h.get("confidence") is not None else "—"
            price_str = f"@{h['price']}" if h.get("price") is not None else ""
            print(f"   {icon}  #{h['id']:<4} {h['type']:<12} {price_str:<10} conf={conf}")
        print(bar + "\n")


# ═══════════════════════════════════════════════════════════════
# QUICK RUN — Direct demo (mirrors run_day46_demo.py style)
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    from computer_use.tradingview_agent import TradingViewAgent
    from computer_use.browser_safety import BrowserSafetyLayer, BrowserSafetyConfig

    safety = BrowserSafetyLayer(BrowserSafetyConfig(
        allowed_brokers=["tradingview.com"],
        allowed_pairs=["EURUSD"],
        allowed_timeframes=["M15", "H1"],
    ))

    tv = TradingViewAgent(safety=safety)
    tv.start()
    tv.open_chart("EURUSD")
    tv.change_timeframe("H1")

    drawer = ChartDrawer(tv_agent=tv, mode=DrawMode.AUTO)

    # AI Command Interface demo — doc Section 9 এর হুবহু example
    result = drawer.execute_command({
        "action": "DRAW",
        "objects": [
            {"type": "support", "price": 1.0850},
            {"type": "fibonacci", "high": 1.1000, "low": 1.0800},
        ],
    }, symbol="EURUSD", timeframe="H1", current_price=1.0875)

    drawer.print_summary(symbol="EURUSD", timeframe="H1")
    print(result)

    tv.close()