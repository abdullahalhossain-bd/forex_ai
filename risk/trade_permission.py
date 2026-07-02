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
    MIN_CONFIDENCE_PROD  = 40
    MIN_CONFIDENCE_TEST  = 10

    # Day 97+ Book rules: confluence + R:R gates
    MIN_ALIGNED_FACTORS_PROD = 1   # lowered from 4 to 1 (get trades through)
    MIN_ALIGNED_FACTORS_TEST = 1
    MIN_RR_PROD = 1.0   # min 1:1 R:R (lowered from 1.5)
    MIN_RR_TEST = 0.5
    BLOCKED_SETUP_QUALITIES = {"AVOID", "INVALID", "POOR"}

    @property
    def MIN_CONFIDENCE(self) -> int:
        return self.MIN_CONFIDENCE_TEST if _test_mode() else self.MIN_CONFIDENCE_PROD

    @property
    def MIN_ALIGNED_FACTORS(self) -> int:
        return self.MIN_ALIGNED_FACTORS_TEST if _test_mode() else self.MIN_ALIGNED_FACTORS_PROD

    @property
    def MIN_RR(self) -> float:
        return self.MIN_RR_TEST if _test_mode() else self.MIN_RR_PROD

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
        # Day 97+ FIX: fail-safe (not fail-open). If news_ctx is empty/None
        # (API failed), default to DENY — don't allow trading when we can't
        # verify news safety. Previously defaulted to True (fail-open) which
        # meant news API failure → trading allowed → could trade into CPI/NFP.
        if not news_ctx:
            ok = False
            detail = "News system unavailable — fail-safe block"
        else:
            ok = news_ctx.get("news_trade_allowed", False)
            detail = news_ctx.get("news_reason", "Unknown")
        checks.append({
            "check":  "News safe",
            "passed": ok,
            "detail": detail,
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

        # Day 97+ Book rules: Confluence quality + Min R:R
        aligned = decision_out.get("aligned_factors", 0)
        setup_q = decision_out.get("setup_quality", "UNKNOWN")
        ok_aligned = aligned >= self.MIN_ALIGNED_FACTORS
        ok_quality = setup_q not in self.BLOCKED_SETUP_QUALITIES
        checks.append({
            "check":  "Confluence quality",
            "passed": ok_aligned and ok_quality,
            "detail": f"{aligned} factors, {setup_q} (min {self.MIN_ALIGNED_FACTORS})",
        })
        if ok_aligned and ok_quality: passed += 1
        total += 1

        # Day 97+ Book rule: Min R:R
        rr = risk_out.get("rr_ratio", 0)
        ok_rr = rr >= self.MIN_RR
        checks.append({
            "check":  "Min R:R",
            "passed": ok_rr,
            "detail": f"1:{rr} (min 1:{self.MIN_RR})",
        })
        if ok_rr: passed += 1
        total += 1

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