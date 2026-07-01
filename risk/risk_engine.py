# risk/risk_engine.py  —  Day 13 | Risk Engine
# ============================================================
# Uses core.constants for PIP_SIZE and CORRELATION_GROUPS —
# no local duplicates. Key naming follows project convention:
# "lot" (not "lot_size"), "risk_pc" (not "risk_percent").
# ============================================================

from utils.logger import get_logger
from core.constants import PIP_SIZE, CORRELATION_GROUPS, get_pip_size, get_pip_value_usd, clean_symbol, pips_to_price
import json, os
from datetime import datetime, date, timezone

log = get_logger("risk_engine")

DAILY_LOG_PATH = "memory/daily_risk.json"


class RiskEngine:

    MAX_RISK_PC      = 1.0
    MIN_RR           = 2.0
    MAX_RR           = 5.0   # Day 81+ — masterclass: don't take trades with RR > 1:5
    DAILY_LOSS_LIMIT = 3.0  # default — overridden by config.DAILY_LOSS_LIMIT_PCT below
    MAX_OPEN_TRADES  = 3    # default — overridden by config.MAX_OPEN_TRADES below
    ATR_SL_MULT      = 1.5
    # Day 81+ hotfix: load MAX_LOT from config (default 0.20).
    # Was hardcoded 100.0 — way too high, allowed lot explosion.
    try:
        from config import MAX_LOT as _CFG_MAX_LOT
        MAX_LOT = float(_CFG_MAX_LOT)
    except Exception:
        MAX_LOT = 0.20
    # Day 81+ hotfix: load DAILY_LOSS_LIMIT from config (single source
    # of truth, default 20.0%).  Was hard-coded 3.0 — user wants 20.0.
    try:
        from config import DAILY_LOSS_LIMIT_PCT as _CFG_DLL
        DAILY_LOSS_LIMIT = float(_CFG_DLL)
    except Exception:
        DAILY_LOSS_LIMIT = 20.0
    # Day 81+ hotfix: load MAX_OPEN_TRADES from config (default 20).
    # Was hard-coded 3 — too restrictive, blocked trades when only 3
    # were open.  User wants 20 concurrent positions allowed.
    try:
        from config import MAX_OPEN_TRADES as _CFG_MOT
        MAX_OPEN_TRADES = int(_CFG_MOT)
    except Exception:
        MAX_OPEN_TRADES = 20

    def __init__(self, balance: float = 1000.0, symbol: str = "EURUSD"):
        self.balance = balance
        self.symbol  = clean_symbol(symbol)
        self.pip     = get_pip_size(self.symbol)
        self._daily  = self._load_daily()
        # Day 90 bugfix: _live_open_pairs MUST be initialized in __init__
        # so _correlation_check() always finds it.  Previously this attribute
        # was only set inside sync_open_positions() — which itself was broken
        # because Python silently kept the SECOND of two same-named methods
        # (the one that only updated daily_risk.json, not _live_open_pairs).
        # As a result _live_open_pairs was NEVER set and the correlation check
        # always fell back to the potentially-stale daily_risk.json file.
        # Initialize to empty set here; trader.py sync_open_positions() will
        # overwrite it each cycle with the authoritative PaperTrader state.
        self._live_open_pairs: set = set()
        # Track sync health so silent failures become visible
        self._sync_call_count: int = 0
        self._sync_fail_count: int = 0
        self._last_sync_at: float = 0.0

    def evaluate(self, signal: str, entry: float, atr: float, regime: dict | None = None) -> dict:
        # Day 81+ hotfix: WAIT signal should also be rejected (not just NO TRADE).
        # Previously WAIT fell through to the `else` branch (SELL) and got
        # approved with SL/TP — but WAIT means "no trade", so it must reject.
        if signal in ("NO TRADE", "WAIT", "HOLD", ""):
            return self._reject(f"Signal is {signal or 'EMPTY'} — no trade")

        # Day 81+ crash fix: entry can be None or 0 when LLM is unavailable
        # and the fallback chain didn't catch it. Force it to a safe default
        # so SL/TP calculation doesn't produce garbage values.
        if not entry or entry == 0:
            log.warning(f"[RiskEngine] entry={entry} (None/0) — using fallback 1.0")
            entry = 1.0

        daily_loss_usd = self._daily.get("total_loss_usd", 0)
        daily_loss_pc  = daily_loss_usd / self.balance * 100
        open_trades    = self._daily.get("open_trades", 0)

        if daily_loss_pc >= self.DAILY_LOSS_LIMIT:
            return self._reject(f"Daily loss limit hit ({daily_loss_pc:.1f}%)")

        if open_trades >= self.MAX_OPEN_TRADES:
            return self._reject(f"Max open trades ({open_trades}/{self.MAX_OPEN_TRADES})")

        corr = self._correlation_check()
        if not corr["allowed"]:
            return self._reject(corr["reason"])

        vol_mult = {
            "LOW_VOLATILITY":  1.0,
            "NORMAL":          self.ATR_SL_MULT,
            "HIGH_VOLATILITY": 2.2,
        }.get(regime.get("volatility", "NORMAL") if regime else "NORMAL", self.ATR_SL_MULT)

        # Day 81+ hotfix: ATR can be None/0/NaN — force a safe default
        if not atr or atr != atr:  # NaN check
            log.warning(f"[RiskEngine] atr={atr} (invalid) — using 0.0010")
            atr = 0.0010

        sl_distance = round(atr * vol_mult, 5)

        # Day 96 bugfix: in LOW_VOLATILITY regime (vol_mult=1.0) ATR can be
        # as low as 6-7 pips on majors during Sydney/Tokyo sessions, giving
        # an SL of just 6-7 pips — easily hit by spread + normal noise
        # before any real move develops (this matched the production
        # journal: EURUSD 6.6 pip SL, GBPUSD 6.4 pip SL, both stopped out).
        # Enforce a hard floor of 10 pips regardless of regime/ATR.
        min_sl_distance = pips_to_price(self.symbol, 10)
        if sl_distance < min_sl_distance:
            log.info(
                f"[RiskEngine] sl_distance={sl_distance} below 10-pip floor "
                f"({min_sl_distance}) — flooring to avoid noise stop-out"
            )
            sl_distance = round(min_sl_distance, 5)

        sl_pips     = round(sl_distance / self.pip) if self.pip > 0 else 10

        if signal == "BUY":
            sl_price = round(entry - sl_distance, 5)
            tp_price = round(entry + sl_distance * self.MIN_RR, 5)
        else:
            sl_price = round(entry + sl_distance, 5)
            tp_price = round(entry - sl_distance * self.MIN_RR, 5)

        tp_pips  = round(sl_pips * self.MIN_RR)
        rr_ratio = round(tp_pips / sl_pips, 2) if sl_pips > 0 else 0

        risk_usd = round(self.balance * self.MAX_RISK_PC / 100, 2)
        pip_val  = get_pip_value_usd(self.symbol)
        lot_raw  = risk_usd / (sl_pips * pip_val) if sl_pips > 0 else 0.01
        # Day 81+ hotfix: cap at self.MAX_LOT (0.20 default), not 100.0.
        lot      = round(max(0.01, min(lot_raw, self.MAX_LOT)), 2)
        if lot_raw > self.MAX_LOT:
            log.warning(
                f"[RiskEngine] lot_raw={lot_raw:.2f} capped to MAX_LOT={self.MAX_LOT} "
                f"(risk_usd=${risk_usd} sl_pips={sl_pips} pip_val=${pip_val})"
            )

        margin_needed = lot * 1000
        if margin_needed > self.balance * 0.5:
            return self._reject(f"Insufficient margin (need ~${margin_needed:.0f})")

        return {
            "approved":      True,
            "signal":        signal,
            "symbol":        self.symbol,
            "entry":         entry,
            "sl_price":      sl_price,
            "tp_price":      tp_price,
            "sl_pips":       sl_pips,
            "tp_pips":       tp_pips,
            "lot":           lot,
            "risk_usd":      risk_usd,
            "risk_pc":       self.MAX_RISK_PC,
            "rr_ratio":      rr_ratio,
            "daily_loss_pc": round(daily_loss_pc, 2),
            "open_trades":   open_trades,
            "reject_reason": None,
        }

    def _correlation_check(self) -> dict:
        # Day 90 bugfix: _live_open_pairs is now ALWAYS set in __init__
        # (empty set) and updated by sync_open_positions() each cycle.
        # Use it directly — no hasattr / isinstance checks needed.
        # If sync_open_positions was never called (e.g. fresh boot before
        # first cycle), this falls back to daily_risk.json state.
        live_pairs = getattr(self, "_live_open_pairs", None)
        if isinstance(live_pairs, set):
            open_pairs = live_pairs
        else:
            # Fallback: stale daily_risk.json state (only on very first cycle)
            open_pairs = set(self._daily.get("open_pairs", []))
        for group in CORRELATION_GROUPS:
            group_set = set(group)
            if self.symbol in group_set and open_pairs & group_set:
                return {"allowed": False, "reason": f"Correlation conflict with {open_pairs & group_set}"}
        return {"allowed": True, "reason": "OK"}

    def sync_open_positions(self, open_pairs) -> None:
        """Day 81+ hotfix (Day 90 bugfix): called by trader.py before
        evaluate() to inject the authoritative live open-pair list.

        This is the SINGLE source of truth for correlation checks — it
        overrides the potentially-stale open_pairs in daily_risk.json.

        Day 90 bugfix history:
          - There used to be TWO `sync_open_positions` methods in this
            class (line 159 + line 214). Python silently kept the second
            one, which only updated daily_risk.json and never set
            _live_open_pairs. Result: _correlation_check() always fell
            back to the stale file. The two methods are now merged here:
            we both update _live_open_pairs (in-memory authoritative
            state used by _correlation_check) AND sync daily_risk.json
            (for persistence across restarts).

        Args:
            open_pairs: list/set of pair symbols currently open
                        (e.g. ['USDJPY', 'EURUSD']).
        """
        import time as _time
        self._sync_call_count += 1
        self._last_sync_at = _time.time()
        try:
            # Clean + deduplicate symbols
            clean_pairs = sorted({clean_symbol(p) for p in (open_pairs or []) if p})
            # In-memory authoritative state (used by _correlation_check)
            self._live_open_pairs = set(clean_pairs)
            # Persisted state (used after restart, before first sync)
            self._daily["open_pairs"]   = clean_pairs
            self._daily["open_trades"]  = len(clean_pairs)
            self._save_daily(self._daily)
            log.debug(
                f"[RiskEngine] sync_open_positions OK | "
                f"pairs={clean_pairs} | calls={self._sync_call_count}"
            )
        except Exception as e:
            # Day 90 bugfix: log at WARNING (not debug) so silent failures
            # are visible in production logs. Increment fail counter so
            # health checks can detect recurring problems.
            self._sync_fail_count += 1
            log.warning(
                f"[RiskEngine] sync_open_positions FAILED "
                f"(call #{self._sync_call_count}, fail #{self._sync_fail_count}): {e}"
            )
            # Still try to set _live_open_pairs defensively so correlation
            # check doesn't silently use stale state. If even this raises,
            # we leave the previous value in place (better stale than none).
            try:
                self._live_open_pairs = set(open_pairs or [])
            except Exception:
                pass

    def _load_daily(self) -> dict:
        os.makedirs("memory", exist_ok=True)
        today = date.today().isoformat()
        if not os.path.exists(DAILY_LOG_PATH):
            return self._fresh_day(today)
        try:
            with open(DAILY_LOG_PATH) as f:
                data = json.load(f)
            return data if data.get("date") == today else self._fresh_day(today)
        except Exception:
            return self._fresh_day(today)

    def _fresh_day(self, today: str) -> dict:
        data = {"date": today, "total_loss_usd": 0, "total_win_usd": 0,
                "open_trades": 0, "open_pairs": [], "trades": []}
        self._save_daily(data)
        return data

    def _save_daily(self, data: dict) -> None:
        with open(DAILY_LOG_PATH, "w") as f:
            json.dump(data, f, indent=2)

    def record_trade_open(self, symbol: str) -> None:
        self._daily["open_trades"] = self._daily.get("open_trades", 0) + 1
        pairs = self._daily.get("open_pairs", [])
        if symbol not in pairs:
            pairs.append(symbol)
        self._daily["open_pairs"] = pairs
        self._save_daily(self._daily)

    def record_trade_close(self, symbol: str, pnl_usd: float) -> None:
        self._daily["open_trades"] = max(0, self._daily.get("open_trades", 1) - 1)
        pairs = self._daily.get("open_pairs", [])
        if symbol in pairs:
            pairs.remove(symbol)
        self._daily["open_pairs"] = pairs
        if pnl_usd < 0:
            self._daily["total_loss_usd"] = self._daily.get("total_loss_usd", 0) + abs(pnl_usd)
        else:
            self._daily["total_win_usd"] = self._daily.get("total_win_usd", 0) + pnl_usd
        self._daily.setdefault("trades", []).append(
            {"symbol": symbol, "pnl_usd": round(pnl_usd, 2), "time": datetime.now(timezone.utc).isoformat()}
        )
        self._save_daily(self._daily)

    def get_daily_summary(self) -> dict:
        d = self._daily
        net = d.get("total_win_usd", 0) - d.get("total_loss_usd", 0)
        return {
            "date":               d.get("date"),
            "net_usd":            round(net, 2),
            "total_win_usd":      d.get("total_win_usd", 0),
            "total_loss_usd":     d.get("total_loss_usd", 0),
            "open_trades":        d.get("open_trades", 0),
            "open_pairs":         d.get("open_pairs", []),
            "daily_loss_pc":      round(d.get("total_loss_usd", 0) / self.balance * 100, 2),
            "limit_remaining_pc": round(self.DAILY_LOSS_LIMIT - d.get("total_loss_usd", 0) / self.balance * 100, 2),
        }

    def get_sync_health(self) -> dict:
        """Day 90 bugfix: surface sync_open_positions health metrics so
        dashboard / health monitors can detect when the sync chain is
        broken. Returns dict with:
          - sync_call_count  : total calls since boot
          - sync_fail_count  : total failures since boot
          - last_sync_ago_s  : seconds since last successful sync
          - live_open_pairs  : current authoritative open-pairs set
          - file_open_pairs  : what daily_risk.json says (should match)
          - in_sync          : True if live state matches file state
        """
        import time as _time
        ago = _time.time() - self._last_sync_at if self._last_sync_at > 0 else None
        live = getattr(self, "_live_open_pairs", set())
        file_pairs = set(self._daily.get("open_pairs", []))
        return {
            "sync_call_count": self._sync_call_count,
            "sync_fail_count": self._sync_fail_count,
            "last_sync_ago_s": round(ago, 1) if ago is not None else None,
            "live_open_pairs": sorted(live),
            "file_open_pairs": sorted(file_pairs),
            "in_sync": live == file_pairs,
        }

    def _reject(self, reason: str) -> dict:
        log.info(f"[RiskEngine] REJECTED — {reason}")
        return {"approved": False, "signal": "NO TRADE", "reject_reason": reason,
                "lot": 0, "sl_pips": 0, "tp_pips": 0, "rr_ratio": 0}

    def _clean(self, symbol: str) -> str:
        return clean_symbol(symbol)

    def print_summary(self, result: dict) -> None:
        bar  = "═" * 44
        icon = "✅" if result["approved"] else "⛔"
        log.info(bar)
        log.info(f"  {icon}  RISK ENGINE")
        log.info(bar)
        if not result["approved"]:
            log.info(f"  Rejected    : {result['reject_reason']}")
        else:
            log.info(f"  Signal      : {result['signal']} {result['symbol']}")
            log.info(f"  Entry       : {result['entry']}")
            log.info(f"  SL          : {result['sl_price']}  ({result['sl_pips']} pips)")
            log.info(f"  TP          : {result['tp_price']}  ({result['tp_pips']} pips)")
            log.info(f"  Lot         : {result['lot']}")
            log.info(f"  Risk        : {result['risk_pc']}%  (${result['risk_usd']})")
            log.info(f"  R:R         : 1:{result['rr_ratio']}")
            log.info(f"  Daily loss  : {result['daily_loss_pc']}%  (limit {self.DAILY_LOSS_LIMIT}%)")
        log.info(bar)

    def get_ai_context(self, result: dict) -> dict:
        return {
            "risk_approved": result["approved"],
            "risk_lot":      result.get("lot", 0),
            "risk_sl_pips":  result.get("sl_pips", 0),
            "risk_tp_pips":  result.get("tp_pips", 0),
            "risk_rr":       result.get("rr_ratio", 0),
            "risk_reject":   result.get("reject_reason"),
            "risk_sl_price": result.get("sl_price"),
            "risk_tp_price": result.get("tp_price"),
        }