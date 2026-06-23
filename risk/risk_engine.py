# risk/risk_engine.py  —  Day 13 | Risk Engine
# ============================================================
# Uses core.constants for PIP_SIZE and CORRELATION_GROUPS —
# no local duplicates. Key naming follows project convention:
# "lot" (not "lot_size"), "risk_pc" (not "risk_percent").
# ============================================================

from utils.logger import get_logger
from core.constants import PIP_SIZE, CORRELATION_GROUPS, get_pip_size, get_pip_value_usd, clean_symbol
import json, os
from datetime import datetime, date, timezone

log = get_logger("risk_engine")

DAILY_LOG_PATH = "memory/daily_risk.json"


class RiskEngine:

    # Day 76c: Increased risk limits to allow more active trading
    MAX_RISK_PC      = 2.0      # was 1.0, now 2% per trade (Day 76c)
    MIN_RR           = 1.5      # was 2.0, now 1.5:1 (Day 76c)
    DAILY_LOSS_LIMIT = 7.0      # was 3.0, now 7% daily (Day 76c)
    MAX_OPEN_TRADES  = 10       # was 3, now 10 concurrent (Day 76c)
    ATR_SL_MULT      = 1.5

    def __init__(self, balance: float = 1000.0, symbol: str = "EURUSD"):
        self.balance = balance
        self.symbol  = clean_symbol(symbol)
        self.pip     = get_pip_size(self.symbol)
        self._daily  = self._load_daily()

    def evaluate(self, signal: str, entry: float, atr: float, regime: dict | None = None) -> dict:
        if signal == "NO TRADE":
            return self._reject("Signal is NO TRADE")

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

        sl_distance = round(atr * vol_mult, 5)
        sl_pips     = round(sl_distance / self.pip)

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
        lot      = round(max(0.01, min(lot_raw, 100.0)), 2)

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
        open_pairs = set(self._daily.get("open_pairs", []))
        for group in CORRELATION_GROUPS:
            group_set = set(group)
            if self.symbol in group_set and open_pairs & group_set:
                return {"allowed": False, "reason": f"Correlation conflict with {open_pairs & group_set}"}
        return {"allowed": True, "reason": "OK"}

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

    def sync_open_positions(self, open_pairs: list[str]) -> None:
        """Sync daily risk state with actual open positions after restart/recovery."""
        clean_pairs = sorted({clean_symbol(pair) for pair in open_pairs if pair})
        self._daily["open_pairs"] = clean_pairs
        self._daily["open_trades"] = len(clean_pairs)
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
