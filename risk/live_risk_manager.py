"""
risk/live_risk_manager.py — Live Risk Manager (Day 75)
========================================================

The central risk controller. Every trade MUST pass through this
before execution. It coordinates:

  1. Capital Tier System (Tier 1/2/3 — gradual risk increase)
  2. Kill Switch (3-level emergency brake)
  3. Drawdown Monitor (Capital Preservation Mode)
  4. Position Sizer (dynamic lot sizing)
  5. Exposure Manager (correlation + direction limits)
  6. Risk Reporter (event logging + Telegram alerts)

Permission flow:
  Signal → Confidence Check → Kill Switch → Drawdown Mode
         → Exposure Check → Position Size → Spread Check → Execute

Usage:
    mgr = get_live_risk_manager()
    permission = mgr.check_trade_permission(
        pair="EURUSD", direction="BUY", confidence=75,
        sl_pips=20, atr=0.001, balance=10000,
    )
    if permission.allowed:
        execute_trade(permission.lot, permission.sl, permission.tp)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

from risk.position_sizer import PositionSizer, PositionSizeResult, get_position_sizer
from risk.kill_switch import KillSwitch, get_kill_switch
from risk.exposure_manager import ExposureManager, get_exposure_manager
from risk.drawdown_monitor import DrawdownMonitor, DrawdownStatus, get_drawdown_monitor
from risk.risk_reporter import RiskReporter, get_risk_reporter

log = get_logger("live_risk_manager")


# ── Capital Tier System ─────────────────────────────────────────────

@dataclass
class CapitalTier:
    """One tier of the capital progression system."""
    tier: int
    name: str
    risk_per_trade: float        # 0.005 = 0.5%
    daily_loss_limit: float      # 0.015 = 1.5%
    max_trades_per_day: int
    min_confidence: float
    approval_mode: str           # manual / semi_auto / fully_auto
    tier_mult: float             # position size multiplier

TIERS = {
    1: CapitalTier(1, "Initial Live", 0.005, 0.015, 3, 80.0, "manual", 0.5),
    2: CapitalTier(2, "Controlled Automation", 0.01, 0.03, 5, 70.0, "semi_auto", 0.8),
    3: CapitalTier(3, "Mature System", 0.01, 0.03, 7, 55.0, "fully_auto", 1.0),
}


@dataclass
class TradePermission:
    """Result of trade permission check."""
    allowed: bool = False
    lot: float = 0.0
    risk_amount_usd: float = 0.0
    risk_pct: float = 0.0
    sl_pips: float = 0.0
    tp_pips: float = 0.0
    reject_reason: str = ""
    tier: int = 1
    mode: str = "NORMAL"
    checks: List[Dict[str, Any]] = field(default_factory=list)
    position_sizing: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class LiveRiskManager:
    """Central risk controller — every trade passes through here."""

    def __init__(self, initial_balance: float = 10000.0, tier: int = 3):
        self.initial_balance = initial_balance
        self.current_tier = TIERS.get(tier, TIERS[3])
        self.position_sizer = get_position_sizer()
        self.kill_switch = get_kill_switch()
        self.exposure_mgr = get_exposure_manager()
        self.drawdown_monitor = get_drawdown_monitor()
        self.risk_reporter = get_risk_reporter()
        self._trades_today = 0
        self._consecutive_losses = 0

    def set_tier(self, tier: int) -> None:
        """Set the capital tier (1, 2, or 3)."""
        if tier in TIERS:
            self.current_tier = TIERS[tier]
            log.info(f"[LiveRiskManager] Tier set to {tier} ({self.current_tier.name})")

    def record_trade_result(self, won: bool) -> None:
        """Record a trade outcome for streak tracking."""
        if won:
            self._consecutive_losses = 0
        else:
            self._consecutive_losses += 1
            if self._consecutive_losses >= 3:
                self.risk_reporter.record_event(
                    "LOSS_STREAK_WARNING",
                    trigger_value=f"{self._consecutive_losses} consecutive losses",
                    action_taken="Position size reduced",
                )

    def reset_daily(self) -> None:
        """Reset daily counters (called at start of each trading day)."""
        self._trades_today = 0

    def check_trade_permission(
        self,
        pair: str,
        direction: str,
        confidence: float,
        sl_pips: float,
        tp_pips: float,
        balance: float,
        atr: float = 0.001,
        atr_median: float = 0.001,
        spread_pips: float = 1.5,
        open_positions: Optional[List[Dict]] = None,
        daily_pnl: float = 0.0,
        weekly_pnl: float = 0.0,
    ) -> TradePermission:
        """Run ALL risk checks before allowing a trade.

        This is the FINAL gate before MT5 execution.

        Args:
            pair: Trading pair.
            direction: BUY or SELL.
            confidence: Master Decision confidence (0-100).
            sl_pips: Stop loss in pips.
            tp_pips: Take profit in pips.
            balance: Current account balance.
            atr: Current ATR.
            atr_median: Median ATR (for volatility comparison).
            spread_pips: Current spread in pips.
            open_positions: List of currently open positions.
            daily_pnl: Today's PnL (negative = loss).
            weekly_pnl: This week's PnL.

        Returns:
            TradePermission with allowed + lot + reject_reason.
        """
        perm = TradePermission(sl_pips=sl_pips, tp_pips=tp_pips)
        tier = self.current_tier

        # Update exposure manager
        self.exposure_mgr.update_positions(open_positions or [])

        # Update drawdown monitor
        dd_status = self.drawdown_monitor.update(balance, self.initial_balance)
        perm.mode = dd_status.mode

        # ── Check 1: Kill Switch ────────────────────────────────────
        ks = self.kill_switch.check(balance, self.initial_balance, daily_pnl, weekly_pnl)
        perm.checks.append({"check": "kill_switch", "passed": ks["trading_allowed"], "detail": ks["reason"]})
        if not ks["trading_allowed"]:
            perm.reject_reason = f"Kill Switch L{ks['level']}: {ks['reason']}"
            self.risk_reporter.record_event(
                f"KILL_SWITCH_L{ks['level']}",
                trigger_value=ks["reason"],
                action_taken="Trade blocked",
            )
            return perm

        # ── Check 2: Confidence floor (tier + drawdown adjusted) ────
        min_conf = max(tier.min_confidence, dd_status.min_confidence_required)
        if confidence < min_conf:
            perm.reject_reason = f"Confidence {confidence:.0f}% < {min_conf:.0f}% (tier={tier.tier}, mode={dd_status.mode})"
            perm.checks.append({"check": "confidence", "passed": False, "detail": perm.reject_reason})
            return perm
        perm.checks.append({"check": "confidence", "passed": True, "detail": f"{confidence:.0f}% ≥ {min_conf:.0f}%"})

        # ── Check 3: Daily trade count ──────────────────────────────
        if self._trades_today >= tier.max_trades_per_day:
            perm.reject_reason = f"Max trades/day reached ({self._trades_today}/{tier.max_trades_per_day})"
            perm.checks.append({"check": "daily_trades", "passed": False, "detail": perm.reject_reason})
            return perm
        perm.checks.append({"check": "daily_trades", "passed": True, "detail": f"{self._trades_today}/{tier.max_trades_per_day}"})

        # ── Check 4: Spread check ───────────────────────────────────
        max_spread = 5.0  # max 5 pips spread
        if spread_pips > max_spread:
            perm.reject_reason = f"Spread too high: {spread_pips:.1f} > {max_spread}"
            perm.checks.append({"check": "spread", "passed": False, "detail": perm.reject_reason})
            return perm
        perm.checks.append({"check": "spread", "passed": True, "detail": f"{spread_pips:.1f} pips"})

        # ── Check 5: Exposure / correlation ─────────────────────────
        # Estimate risk_usd for exposure check
        est_risk = balance * tier.risk_per_trade * tier.tier_mult
        exp = self.exposure_mgr.check(pair, direction, lot=0.1, risk_usd=est_risk, balance=balance)
        perm.checks.append({"check": "exposure", "passed": exp.allowed, "detail": exp.reason})
        if not exp.allowed:
            perm.reject_reason = f"Exposure: {exp.reason}"
            self.risk_reporter.record_event("EXPOSURE_REJECTED", trigger_value=exp.reason, action_taken="Trade blocked")
            return perm

        # ── Check 6: Position sizing ────────────────────────────────
        pip_value = 10.0 if not pair.endswith("JPY") else 9.0
        sizing = self.position_sizer.calculate(
            balance=balance,
            risk_pct=tier.risk_per_trade,
            sl_pips=sl_pips,
            pip_value_per_lot=pip_value,
            confidence=confidence,
            atr=atr,
            atr_median=atr_median,
            consecutive_losses=self._consecutive_losses,
            tier_mult=tier.tier_mult * dd_status.position_multiplier,
        )
        perm.position_sizing = sizing.to_dict()

        if sizing.lot <= 0:
            perm.reject_reason = f"Position sizing: {sizing.reason}"
            perm.checks.append({"check": "position_size", "passed": False, "detail": sizing.reason})
            return perm

        perm.checks.append({"check": "position_size", "passed": True, "detail": f"lot={sizing.lot}, risk=${sizing.risk_amount_usd}"})

        # ── ALL CHECKS PASSED ───────────────────────────────────────
        perm.allowed = True
        perm.lot = sizing.lot
        perm.risk_amount_usd = sizing.risk_amount_usd
        perm.risk_pct = sizing.risk_pct
        perm.tier = tier.tier
        self._trades_today += 1

        # Report capital preservation mode if active
        if dd_status.mode != "NORMAL":
            self.risk_reporter.record_event(
                "CAPITAL_PRESERVATION_ACTIVATED",
                trigger_value=f"DD={dd_status.current_drawdown_pct:.1%}, mode={dd_status.mode}",
                action_taken=f"min_conf={dd_status.min_confidence_required}, pos_mult={dd_status.position_multiplier}",
                send_telegram=False,
            )

        log.info(
            f"[LiveRiskManager] APPROVED {pair} {direction} | "
            f"lot={perm.lot} | risk=${perm.risk_amount_usd} ({perm.risk_pct:.2f}%) | "
            f"tier={perm.tier} | mode={perm.mode} | conf={confidence:.0f}%"
        )
        return perm

    def status(self) -> Dict[str, Any]:
        """Return full risk status for dashboard."""
        return {
            "tier": self.current_tier.tier,
            "tier_name": self.current_tier.name,
            "risk_per_trade": self.current_tier.risk_per_trade,
            "daily_loss_limit": self.current_tier.daily_loss_limit,
            "max_trades_day": self.current_tier.max_trades_per_day,
            "trades_today": self._trades_today,
            "consecutive_losses": self._consecutive_losses,
            "kill_switch": self.kill_switch.status(),
            "drawdown": self.drawdown_monitor.status(),
            "exposure": self.exposure_mgr.status(),
            "risk_events": self.risk_reporter.stats(),
        }


# ── Singleton ───────────────────────────────────────────────────────

_MANAGER: Optional[LiveRiskManager] = None


def get_live_risk_manager() -> LiveRiskManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = LiveRiskManager()
    return _MANAGER
