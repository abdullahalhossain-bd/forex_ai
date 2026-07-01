# risk/trade_permission.py  —  Day 13 | Final Trade Permission Gate

from utils.logger import get_logger

log = get_logger("trade_permission")


def _test_mode() -> bool:
    """Lazy check — avoids importing config at module load (which would
    crash unit tests on systems without a .env file)."""
    try:
        from config import TEST_MODE
        return bool(TEST_MODE)
    except Exception:
        return False


class TradePermission:
    """
    সব check পার হলে ALLOW, না হলে DENY।
    RiskEngine এর পরে final gate।

    Checklist:
        1. Signal valid?
        2. Risk approved?
        3. News safe?
        4. Session active?
        5. Confluence enough?
    """

    # Day 96 bugfix: comment said 60 but the constant was left at 40 —
    # the gate was never actually enforcing the documented production
    # threshold, which is how single-indicator 42%-confidence trades
    # (e.g. lone RSI oversold) kept reaching MT5.
    MIN_CONFIDENCE_PROD  = 60
    MIN_CONFIDENCE_TEST  = 10

    @property
    def MIN_CONFIDENCE(self) -> int:
        return self.MIN_CONFIDENCE_TEST if _test_mode() else self.MIN_CONFIDENCE_PROD

    def check(
        self,
        decision_out: dict,
        risk_out:     dict,
        news_ctx:     dict,
        session_ctx:  dict | None = None,
    ) -> dict:

        checks = []
        passed = 0

        # 1. Signal
        sig = decision_out.get("decision", "WAIT")
        ok  = sig in ("BUY", "SELL")
        checks.append({"check": "Valid signal", "passed": ok, "detail": sig})
        if ok: passed += 1

        # 2. Risk approved
        ok = risk_out.get("approved", False)
        checks.append({
            "check":  "Risk approved",
            "passed": ok,
            "detail": risk_out.get("reject_reason", "OK"),
        })
        if ok: passed += 1

        # 3. News safe
        ok = news_ctx.get("news_trade_allowed", True)
        checks.append({
            "check":  "News safe",
            "passed": ok,
            "detail": news_ctx.get("news_reason", "OK"),
        })
        if ok: passed += 1

        # 4. Confidence
        conf = decision_out.get("confidence", 0)
        ok   = conf >= self.MIN_CONFIDENCE
        checks.append({
            "check":  "Min confidence",
            "passed": ok,
            "detail": f"{conf}% (min {self.MIN_CONFIDENCE}%)",
        })
        if ok: passed += 1

        # 5. Session quality (optional)
        # In TEST_MODE: session quality is just a logged warning, NOT a
        # trade blocker. This lets the system place trades during off-hours
        # (Sydney/Tokyo only) so you can verify MT5 execution end-to-end.
        # In production: LOW quality sessions block the trade.
        if session_ctx:
            quality = session_ctx.get("quality", "LOW")
            if _test_mode():
                ok = True   # always pass in test mode
                detail = f"{quality} (TEST_MODE: allowed)"
            else:
                ok = quality in ("HIGH", "MEDIUM")
                detail = quality
            checks.append({
                "check":  "Session quality",
                "passed": ok,
                "detail": detail,
            })
            if ok: passed += 1
            total = 5
        else:
            total = 4

        allowed = passed == total   # সব check pass করতে হবে

        result = {
            "allowed":       allowed,
            "passed":        passed,
            "total":         total,
            "checks":        checks,
            "final_action":  decision_out.get("decision") if allowed else "NO TRADE",
            "entry":         risk_out.get("entry"),
            "sl":            risk_out.get("sl_price"),
            "tp":            risk_out.get("tp_price"),
            "lot":           risk_out.get("lot", 0),
            "rr":            risk_out.get("rr_ratio", 0),
        }

        log.info(
            f"[TradePermission] {'ALLOWED' if allowed else 'DENIED'} "
            f"({passed}/{total} checks passed)"
        )
        return result

    def print_summary(self, result: dict) -> None:
        bar  = "═" * 44
        icon = "✅" if result["allowed"] else "⛔"
        log.info(bar)
        log.info(f"  {icon}  TRADE PERMISSION  ({result['passed']}/{result['total']})")
        log.info(bar)
        for c in result["checks"]:
            tick = "✓" if c["passed"] else "✗"
            log.info(f"  {tick}  {c['check']:<22} {c['detail']}")
        log.info(f"  ──")
        log.info(f"  Final action : {result['final_action']}")
        if result["allowed"]:
            log.info(f"  Entry        : {result['entry']}")
            log.info(f"  SL / TP      : {result['sl']} / {result['tp']}")
            log.info(f"  Lot          : {result['lot']}   R:R 1:{result['rr']}")
        log.info(bar)