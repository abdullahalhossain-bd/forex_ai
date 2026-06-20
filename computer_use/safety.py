# computer_use/safety.py  —  Day 45 | Safety Layer (Computer Use)
# ============================================================
# Computer Use risky — ভুল window-এ click, ভুল symbol-এ order,
# বা ভুল lot size দিয়ে accidental action হয়ে যেতে পারে।
#
# এই layer প্রতিটা sensitive action (click/order)-এর আগে
# approve/reject করবে। screen_controller.py ও browser_control.py
# কোনো click করার আগে এই layer-কে জিজ্ঞেস করে।
#
# Rules checked (doc অনুযায়ী):
#   ✅ Correct window?
#   ✅ Correct symbol?
#   ✅ Correct account / order size (lot)?
#   ✅ SL exists? (trade action হলে)
#   ✅ Runaway click-rate protection (bonus)
# ============================================================

from dataclasses import dataclass, field

from utils.logger import get_logger

log = get_logger("computer_use.safety")


@dataclass
class SafetyConfig:
    expected_window_titles: list = field(default_factory=lambda: ["TradingView", "MetaTrader 5"])
    allowed_symbols: list = None          # None = সব symbol allowed
    max_lot_size: float = 1.0
    require_sl: bool = True
    max_clicks_per_minute: int = 20       # runaway-click/loop protection


class SafetyLayer:
    """
    Computer Use Layer-এর প্রতিটা sensitive action এখান দিয়ে pass করবে।

    Usage:
        safety = SafetyLayer(SafetyConfig(allowed_symbols=["EURUSD"], max_lot_size=0.1))
        decision = safety.check_before_click({
            "active_window": "TradingView - EURUSD",
            "symbol": "EURUSD",
            "lot": 0.01,
            "sl_exists": True,
            "action": "BUY",
        })
        if decision["approved"]:
            ... click করো ...
    """

    def __init__(self, config: SafetyConfig = None):
        self.config = config or SafetyConfig()
        self._click_timestamps: list = []

    # ─────────────────────────────────────────────
    # MAIN CHECK
    # ─────────────────────────────────────────────

    def check_before_click(self, context: dict) -> dict:
        """
        Click/action নেওয়ার আগে সব rule check করো।

        context-এ relevant key গুলো দাও (যেগুলো নেই সেগুলো skip হবে):
            active_window : str   — বর্তমানে focus করা window-এর title
            symbol        : str   — current chart/order symbol
            lot           : float
            sl_exists     : bool
            action        : str   — "BUY" / "SELL" / "CLICK" ইত্যাদি

        Returns:
            { "approved": bool, "checks": {...}, "reasons": [...] }
        """
        checks: dict = {}
        reasons: list = []

        # 1) Correct window?
        win_ok = self._check_window(context.get("active_window", ""))
        checks["correct_window"] = win_ok
        if not win_ok:
            reasons.append(
                f"Active window '{context.get('active_window')}' — expected one of "
                f"{self.config.expected_window_titles}"
            )

        # 2) Correct symbol?
        sym_ok = self._check_symbol(context.get("symbol"))
        checks["correct_symbol"] = sym_ok
        if not sym_ok:
            reasons.append(
                f"Symbol '{context.get('symbol')}' not in allowed list "
                f"{self.config.allowed_symbols}"
            )

        # 3) Correct order size (lot)?
        lot_ok = self._check_lot(context.get("lot"))
        checks["correct_order_size"] = lot_ok
        if not lot_ok:
            reasons.append(
                f"Lot size {context.get('lot')} invalid or exceeds max "
                f"{self.config.max_lot_size}"
            )

        # 4) SL exists? — শুধু BUY/SELL action-এর জন্য প্রযোজ্য
        if context.get("action") in ("BUY", "SELL"):
            sl_ok = (not self.config.require_sl) or bool(context.get("sl_exists"))
            checks["sl_exists"] = sl_ok
            if not sl_ok:
                reasons.append("No Stop Loss set — trade action blocked")
        else:
            checks["sl_exists"] = True

        # 5) Click-rate limiter (runaway automation protection)
        rate_ok = self._check_click_rate()
        checks["click_rate_ok"] = rate_ok
        if not rate_ok:
            reasons.append(
                f"Click rate exceeded {self.config.max_clicks_per_minute}/min — "
                f"possible runaway loop, action blocked"
            )

        approved = all(checks.values())
        if approved:
            self._click_timestamps.append(self._now())

        result = {"approved": approved, "checks": checks, "reasons": reasons}
        self._log_result(context, result)
        return result

    # ─────────────────────────────────────────────
    # INDIVIDUAL CHECKS
    # ─────────────────────────────────────────────

    def _check_window(self, active_window: str) -> bool:
        if not self.config.expected_window_titles:
            return True
        if not active_window:
            return False
        return any(
            expected.lower() in active_window.lower()
            for expected in self.config.expected_window_titles
        )

    def _check_symbol(self, symbol) -> bool:
        if self.config.allowed_symbols is None:
            return True
        if symbol is None:
            return False
        return symbol.upper().replace("/", "") in [
            s.upper().replace("/", "") for s in self.config.allowed_symbols
        ]

    def _check_lot(self, lot) -> bool:
        if lot is None:
            return True   # non-order actions (যেমন শুধু timeframe click)
        try:
            return 0 < float(lot) <= self.config.max_lot_size
        except (TypeError, ValueError):
            return False

    def _check_click_rate(self) -> bool:
        now = self._now()
        self._click_timestamps = [t for t in self._click_timestamps if now - t < 60]
        return len(self._click_timestamps) < self.config.max_clicks_per_minute

    @staticmethod
    def _now() -> float:
        import time
        return time.time()

    # ─────────────────────────────────────────────
    # LOGGING / SUMMARY
    # ─────────────────────────────────────────────

    def _log_result(self, context: dict, result: dict) -> None:
        icon = "✅" if result["approved"] else "⛔"
        log.info(
            f"[Safety] {icon} action={context.get('action', 'CLICK')} "
            f"symbol={context.get('symbol')} approved={result['approved']}"
        )
        for r in result["reasons"]:
            log.warning(f"[Safety]   ⚠ {r}")

    def print_summary(self, result: dict) -> None:
        bar = "═" * 46
        print(f"\n{bar}")
        print("  🛡️   SAFETY LAYER  (Day 45)")
        print(bar)
        for check, ok in result["checks"].items():
            print(f"  {'✅' if ok else '❌'}  {check}")
        print(f"\n  Decision: {'APPROVED ✅' if result['approved'] else 'BLOCKED ⛔'}")
        if result["reasons"]:
            print("\n  ── Reasons ──")
            for r in result["reasons"]:
                print(f"  • {r}")
        print(bar + "\n")