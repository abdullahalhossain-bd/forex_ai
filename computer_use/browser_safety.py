# computer_use/browser_safety.py  —  Day 46 | Browser Safety Layer
# ============================================================
# Browser দিয়ে কোনো sensitive action (login / chart command / future
# WebTrader trade) নেওয়ার আগে যাচাই করো:
#   ✅ Correct broker?    (URL domain allowed list-এ আছে কিনা)
#   ✅ Correct account?   (login username allowed list-এ আছে কিনা)
#   ✅ Correct pair?
#   ✅ Correct timeframe?
#
# ⚠️ মনে রাখা ভালো (doc-এর own caveat): actual trade execution-এর জন্য
#    MT5 API-ই primary থাকা উচিত — browser automation মূলত chart
#    interaction/visual confirmation/backup-এর জন্য। তবু এই layer
#    futureproofing হিসেবে রাখা হলো, যদি কখনো WebTrader-ভিত্তিক
#    execution path যোগ করা হয়।
# ============================================================

from dataclasses import dataclass, field

from utils.logger import get_logger

log = get_logger("computer_use.browser_safety")


@dataclass
class BrowserSafetyConfig:
    allowed_brokers: list = field(default_factory=lambda: ["tradingview.com"])
    allowed_accounts: list = None        # None = check skip (verify করার দরকার নেই)
    allowed_pairs: list = None
    allowed_timeframes: list = None


class BrowserSafetyLayer:
    """
    Usage:
        safety = BrowserSafetyLayer(BrowserSafetyConfig(
            allowed_pairs=["EURUSD", "GBPUSD"],
            allowed_timeframes=["M15", "H1"],
        ))
        decision = safety.check_before_action({
            "action": "OPEN_CHART",
            "current_url": "https://www.tradingview.com/chart/",
            "pair": "EURUSD",
            "timeframe": "H1",
        })
        if decision["approved"]:
            ...
    """

    def __init__(self, config: BrowserSafetyConfig = None):
        self.config = config or BrowserSafetyConfig()

    def check_before_action(self, context: dict) -> dict:
        checks = {}
        reasons = []

        checks["correct_broker"] = self._check_broker(context.get("current_url", ""))
        if not checks["correct_broker"]:
            reasons.append(
                f"URL '{context.get('current_url')}' doesn't match allowed "
                f"brokers {self.config.allowed_brokers}"
            )

        checks["correct_account"] = self._check_in_list(
            context.get("account"), self.config.allowed_accounts
        )
        if not checks["correct_account"]:
            reasons.append(f"Account '{context.get('account')}' not in allowed list")

        checks["correct_pair"] = self._check_in_list(
            context.get("pair"), self.config.allowed_pairs
        )
        if not checks["correct_pair"]:
            reasons.append(f"Pair '{context.get('pair')}' not in allowed list")

        checks["correct_timeframe"] = self._check_in_list(
            context.get("timeframe"), self.config.allowed_timeframes
        )
        if not checks["correct_timeframe"]:
            reasons.append(f"Timeframe '{context.get('timeframe')}' not in allowed list")

        approved = all(checks.values())
        result = {"approved": approved, "checks": checks, "reasons": reasons}
        self._log(context, result)
        return result

    # ─────────────────────────────────────────────
    # INDIVIDUAL CHECKS
    # ─────────────────────────────────────────────

    def _check_broker(self, url: str) -> bool:
        if not self.config.allowed_brokers:
            return True
        if not url:
            return False
        return any(b.lower() in url.lower() for b in self.config.allowed_brokers)

    def _check_in_list(self, value, allowed_list) -> bool:
        if allowed_list is None:
            return True   # config না দিলে check skip — সব allow
        if value is None:
            return False
        return str(value).upper().replace("/", "") in [
            str(v).upper().replace("/", "") for v in allowed_list
        ]

    # ─────────────────────────────────────────────
    # LOGGING / SUMMARY
    # ─────────────────────────────────────────────

    def _log(self, context: dict, result: dict) -> None:
        icon = "✅" if result["approved"] else "⛔"
        log.info(
            f"[BrowserSafety] {icon} action={context.get('action')} "
            f"pair={context.get('pair')} approved={result['approved']}"
        )
        for r in result["reasons"]:
            log.warning(f"[BrowserSafety]   ⚠ {r}")

    def print_summary(self, result: dict) -> None:
        bar = "═" * 46
        print(f"\n{bar}")
        print("  🛡️   BROWSER SAFETY LAYER  (Day 46)")
        print(bar)
        for check, ok in result["checks"].items():
            print(f"  {'✅' if ok else '❌'}  {check}")
        print(f"\n  Decision: {'APPROVED ✅' if result['approved'] else 'BLOCKED ⛔'}")
        if result["reasons"]:
            print("\n  ── Reasons ──")
            for r in result["reasons"]:
                print(f"  • {r}")
        print(bar + "\n")