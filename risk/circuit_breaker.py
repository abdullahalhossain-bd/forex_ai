# risk/circuit_breaker.py  —  Week 3 Upgrade | AI Kill Switch
# ============================================================
# Consecutive loss tracker + auto trading pause
# AI নিজেকে রক্ষা করতে শিখবে
# ============================================================

import json
import os
from datetime import datetime, date
from utils.logger import get_logger

log = get_logger("circuit_breaker")

CB_STATE_PATH = "memory/circuit_breaker_state.json"


class CircuitBreaker:
    """
    AI-এর automatic protection system।

    Triggers:
      1. Consecutive losses >= threshold → pause trading
      2. Daily loss % >= limit → pause trading
      3. Abnormal volatility detected → pause trading
      4. Win rate drops severely → learning mode

    Modes after trigger:
      - TRADING   : Normal operation
      - PAUSED    : No new trades, existing managed
      - LEARNING  : Analyze mistakes, no trading
      - COOLDOWN  : Wait N hours before resume

    Usage:
        cb = CircuitBreaker()
        if cb.allow_trade():
            ... take trade ...
        cb.record_result("LOSS")
    """

    # Thresholds
    MAX_CONSECUTIVE_LOSSES = 3      # ৩টা loss → pause
    # Day 81+ hotfix: load MAX_DAILY_LOSS_PCT from config (default 20.0).
    # Was hard-coded 3.0 — user wants 20.0.
    try:
        from config import DAILY_LOSS_LIMIT_PCT as _CFG_DLL
        MAX_DAILY_LOSS_PCT = float(_CFG_DLL)
    except Exception:
        MAX_DAILY_LOSS_PCT = 20.0
    MIN_WIN_RATE_THRESHOLD = 30.0   # ৩০% এর নিচে → learning mode
    COOLDOWN_HOURS         = 4      # pause এর পরে কত ঘণ্টা wait
    LOOKBACK_TRADES        = 10     # win rate চেক করার জন্য কতটা পিছনে

    def __init__(self, balance: float = 1000.0):
        self.balance = balance
        self._state  = self._load_state()

    # ── Main Gate ──────────────────────────────────────────────

    def allow_trade(self) -> dict:
        """
        Trade নেওয়ার আগে এটা call করো।

        Returns:
            {
                "allowed": True/False,
                "mode":    "TRADING" | "PAUSED" | "LEARNING" | "COOLDOWN",
                "reason":  str,
                "stats":   dict,
            }
        """
        mode   = self._state.get("mode", "TRADING")
        reason = ""

        # Cooldown check
        if mode == "COOLDOWN":
            cooldown_until = self._state.get("cooldown_until")
            if cooldown_until:
                until_dt = datetime.fromisoformat(cooldown_until)
                if datetime.utcnow() < until_dt:
                    remaining = (until_dt - datetime.utcnow()).seconds // 60
                    return self._response(
                        False, "COOLDOWN",
                        f"Cooldown active — {remaining} min remaining. "
                        f"Resume after {until_dt.strftime('%H:%M UTC')}",
                    )
                else:
                    # Cooldown expired → resume
                    self._set_mode("TRADING", "Cooldown expired — resuming")

        if mode in ("PAUSED", "LEARNING"):
            reason = self._state.get("pause_reason", "Circuit breaker active")
            return self._response(False, mode, reason)

        # Real-time checks
        consec = self._state.get("consecutive_losses", 0)
        if consec >= self.MAX_CONSECUTIVE_LOSSES:
            self._trigger_pause(
                f"🛑 {consec} consecutive losses — entering cooldown"
            )
            return self._response(
                False, "PAUSED",
                f"{consec} consecutive losses hit threshold ({self.MAX_CONSECUTIVE_LOSSES})"
            )

        recent  = self._state.get("recent_results", [])[-self.LOOKBACK_TRADES:]
        if len(recent) >= 5:
            wr = recent.count("WIN") / len(recent) * 100
            if wr < self.MIN_WIN_RATE_THRESHOLD:
                self._trigger_learning(
                    f"Win rate dropped to {wr:.1f}% — entering learning mode"
                )
                return self._response(
                    False, "LEARNING",
                    f"Win rate {wr:.1f}% below minimum {self.MIN_WIN_RATE_THRESHOLD}%"
                )

        return self._response(True, "TRADING", "All checks passed")

    # ── Record Result ──────────────────────────────────────────

    def record_result(self, result: str, pnl_usd: float = 0.0):
        """
        Trade close হওয়ার পরে call করো।
        result: 'WIN' | 'LOSS'

        Day 81+ hotfix: sync daily_loss_usd with daily_risk.json so CB
        and RiskEngine always agree on the day's loss total.  Previously
        CB tracked its own running sum (incremental `+= abs(pnl_usd)`)
        while RiskEngine tracked a separate `total_loss_usd` in
        daily_risk.json — they drifted, and CB could trigger at $435
        while RiskEngine thought loss was only $128.
        """
        recent = self._state.get("recent_results", [])
        recent.append(result)
        self._state["recent_results"] = recent[-50:]  # শেষ ৫০টা রাখো

        if result == "LOSS":
            self._state["consecutive_losses"] = \
                self._state.get("consecutive_losses", 0) + 1
            # Day 81+ hotfix: do NOT incrementally track daily_loss_usd
            # here — instead sync from daily_risk.json (single source of
            # truth).  RiskEngine._save_daily() is called by the same
            # trade-close path and writes the authoritative total.
            self._sync_daily_loss_from_risk_engine()
            log.info(
                f"[CB] LOSS recorded | consecutive={self._state['consecutive_losses']} "
                f"| daily_loss=${self._state['daily_loss_usd']:.2f}"
            )
        else:
            self._state["consecutive_losses"] = 0
            log.info(f"[CB] WIN recorded | streak reset")

        # Daily loss check
        daily_loss_pct = self._state.get("daily_loss_usd", 0) / self.balance * 100
        if daily_loss_pct >= self.MAX_DAILY_LOSS_PCT:
            self._trigger_pause(
                f"Daily loss limit reached: {daily_loss_pct:.1f}%"
            )

        self._save_state()

    # ── Manual Controls ────────────────────────────────────────

    def manual_resume(self, reason: str = "Manual override") -> dict:
        """Human manually resume করলে।"""
        self._set_mode("TRADING", reason)
        self._state["consecutive_losses"] = 0
        self._save_state()
        log.info(f"[CB] Manually resumed: {reason}")
        return {"mode": "TRADING", "reason": reason}

    def force_learning_mode(self) -> dict:
        """Human manually learning mode-এ পাঠালে।"""
        self._trigger_learning("Manual learning mode activation")
        return {"mode": "LEARNING"}

    def reset_daily(self):
        """নতুন দিনে daily counters reset করো।"""
        today = date.today().isoformat()
        if self._state.get("date") != today:
            self._state["date"]           = today
            self._state["daily_loss_usd"] = 0.0
            log.info("[CB] Daily reset — new trading day")
            self._save_state()

    # ── Status ─────────────────────────────────────────────────

    def get_status(self) -> dict:
        recent = self._state.get("recent_results", [])[-10:]
        wr     = (
            recent.count("WIN") / len(recent) * 100
            if recent else 0
        )
        return {
            "mode":               self._state.get("mode", "TRADING"),
            "consecutive_losses": self._state.get("consecutive_losses", 0),
            "recent_win_rate":    round(wr, 1),
            "daily_loss_usd":     self._state.get("daily_loss_usd", 0),
            "daily_loss_pct":     round(
                self._state.get("daily_loss_usd", 0) / self.balance * 100, 2
            ),
            "pause_reason":       self._state.get("pause_reason", ""),
            "total_trades":       len(self._state.get("recent_results", [])),
        }

    def print_status(self):
        s    = self.get_status()
        icon = {"TRADING": "🟢", "PAUSED": "🔴", "LEARNING": "🧠", "COOLDOWN": "⏳"}
        bar  = "═" * 46
        print(f"\n{bar}")
        print(f"  {icon.get(s['mode'], '⚪')}  CIRCUIT BREAKER STATUS")
        print(bar)
        print(f"  Mode              : {s['mode']}")
        print(f"  Consecutive Loss  : {s['consecutive_losses']} / {self.MAX_CONSECUTIVE_LOSSES}")
        print(f"  Recent Win Rate   : {s['recent_win_rate']}%  (last 10 trades)")
        print(f"  Daily Loss        : ${s['daily_loss_usd']:.2f}  ({s['daily_loss_pct']}%)")
        if s["pause_reason"]:
            print(f"  Pause Reason      : {s['pause_reason']}")
        print(bar + "\n")

    # ── Internal ───────────────────────────────────────────────

    def _trigger_pause(self, reason: str):
        from datetime import timedelta
        cooldown_until = (
            datetime.utcnow() + timedelta(hours=self.COOLDOWN_HOURS)
        ).isoformat()
        self._state["mode"]           = "COOLDOWN"
        self._state["pause_reason"]   = reason
        self._state["cooldown_until"] = cooldown_until
        self._save_state()
        log.warning(f"[CB] ⛔ TRADING PAUSED: {reason}")
        log.warning(f"[CB] Cooldown until: {cooldown_until}")

    def _trigger_learning(self, reason: str):
        self._state["mode"]         = "LEARNING"
        self._state["pause_reason"] = reason
        self._save_state()
        log.warning(f"[CB] 🧠 LEARNING MODE: {reason}")

    def _set_mode(self, mode: str, reason: str):
        self._state["mode"]         = mode
        self._state["pause_reason"] = reason
        self._state.pop("cooldown_until", None)
        self._save_state()

    def _response(self, allowed: bool, mode: str, reason: str) -> dict:
        return {
            "allowed": allowed,
            "mode":    mode,
            "reason":  reason,
            "stats":   self.get_status(),
        }

    def _load_state(self) -> dict:
        os.makedirs("memory", exist_ok=True)
        if os.path.exists(CB_STATE_PATH):
            try:
                with open(CB_STATE_PATH) as f:
                    state = json.load(f)
                # Daily reset check
                if state.get("date") != date.today().isoformat():
                    state["daily_loss_usd"] = 0.0
                    state["date"]           = date.today().isoformat()
                return state
            except Exception:
                pass
        return {
            "mode":               "TRADING",
            "consecutive_losses": 0,
            "daily_loss_usd":     0.0,
            "date":               date.today().isoformat(),
            "recent_results":     [],
            "pause_reason":       "",
        }

    def _save_state(self):
        with open(CB_STATE_PATH, "w") as f:
            json.dump(self._state, f, indent=2)

    def _sync_daily_loss_from_risk_engine(self):
        """Day 81+ hotfix: read daily_loss_usd from daily_risk.json
        (the RiskEngine's authoritative state file) so CB and RiskEngine
        always agree on the day's loss total.

        Previously CB tracked its own running sum which drifted from
        RiskEngine's total — CB could trigger at $435 while RiskEngine
        thought loss was only $128.  Now both read from the same file.
        """
        try:
            risk_path = "memory/daily_risk.json"
            with open(risk_path) as f:
                risk_state = json.load(f)
            # Only sync if the date matches today (RiskEngine resets on
            # date rollover; CB should follow the same convention).
            today = date.today().isoformat()
            if risk_state.get("date") == today:
                self._state["daily_loss_usd"] = float(
                    risk_state.get("total_loss_usd", 0)
                )
        except Exception as e:
            log.debug(f"[CB] sync from daily_risk.json failed: {e}")