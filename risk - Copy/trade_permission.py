# risk/trade_permission.py  —  Day 13 | Final Trade Permission Gate

from utils.logger import get_logger

log = get_logger("trade_permission")


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

    MIN_CONFIDENCE = 55   # কমপক্ষে এই confidence হলে trade

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
        if session_ctx:
            quality = session_ctx.get("quality", "LOW")
            ok      = quality in ("HIGH", "MEDIUM")
            checks.append({
                "check":  "Session quality",
                "passed": ok,
                "detail": quality,
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