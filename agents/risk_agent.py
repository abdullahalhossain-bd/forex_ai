# agents/risk_agent.py  —  Day 12 | Risk Management Agent
# Production-hardened: fixed JPY pip value, ZeroDivision, _no_trade consistency

from utils.logger import get_logger

log = get_logger("risk_agent")

PIP_VALUE = {
    "EURUSD": 0.0001,
    "GBPUSD": 0.0001,
    "USDJPY": 0.01,
    "GBPJPY": 0.01,
    "EURJPY": 0.01,
    "AUDJPY": 0.01,
    "DEFAULT": 0.0001,
}

# Per-standard-lot pip value in USD (approximate)
PIP_VALUE_USD = {
    "EURUSD": 10.0,
    "GBPUSD": 10.0,
    "USDJPY": 6.50,   # varies with rate; approximate
    "GBPJPY": 6.50,
    "EURJPY": 6.50,
    "AUDJPY": 6.50,
    "DEFAULT": 10.0,
}


class RiskAgent:
    """
    Signal + market data থেকে lot size, SL, TP calculate করে।
    1% risk rule enforce করে।
    Daily loss limit track করে।
    """

    MAX_RISK_PERCENT    = 1.0    # account এর সর্বোচ্চ 1% risk
    DAILY_LOSS_LIMIT    = 3.0    # দিনে সর্বোচ্চ 3% loss হলে trading বন্ধ
    MIN_RR              = 1.5    # minimum risk:reward ratio
    ATR_SL_MULTIPLIER   = 1.5   # SL = ATR × 1.5

    def __init__(self, account_balance: float = 1000.0):
        self.balance       = account_balance
        self.daily_loss_pc = 0.0   # Day 13 backtester এ track হবে

    def calculate(
        self,
        signal:   str,
        entry:    float,
        ind_ctx:  dict,
        regime:   dict,
        symbol:   str = "EURUSD",
    ) -> dict:
        """
        Signal + entry + ATR থেকে full risk parameters বের করে।
        """

        if signal == "NO TRADE":
            return self._no_trade("Signal is NO TRADE")

        if self.daily_loss_pc >= self.DAILY_LOSS_LIMIT:
            return self._no_trade(
                f"Daily loss limit hit ({self.daily_loss_pc:.1f}%)"
            )

        atr     = ind_ctx.get("atr", 0.0005)
        clean_symbol = symbol.replace("/", "").replace("=X", "").upper()[:6]
        pip = PIP_VALUE.get(
            clean_symbol,
            PIP_VALUE["DEFAULT"]
        )
        pip_val_std = PIP_VALUE_USD.get(
            clean_symbol,
            PIP_VALUE_USD["DEFAULT"]
        )

        # Regime-based SL multiplier
        volatility = regime.get("volatility", "NORMAL")
        sl_mult = {
            "LOW_VOLATILITY":  1.2,
            "NORMAL":          self.ATR_SL_MULTIPLIER,
            "HIGH_VOLATILITY": 2.0,
        }.get(volatility, self.ATR_SL_MULTIPLIER)

        sl_distance = round(atr * sl_mult, 5)
        sl_pips     = round(sl_distance / pip) if pip > 0 else 10

        # Guard: if sl_pips is 0 or sl_distance is too small, use defaults
        if sl_pips < 1:
            sl_pips = 10
            sl_distance = sl_pips * pip

        # TP = SL × min RR
        tp_distance = round(sl_distance * self.MIN_RR, 5)
        tp_pips     = round(tp_distance / pip)

        # SL/TP price levels
        if signal == "BUY":
            sl_price = round(entry - sl_distance, 5)
            tp_price = round(entry + tp_distance, 5)
        else:   # SELL
            sl_price = round(entry + sl_distance, 5)
            tp_price = round(entry - tp_distance, 5)

        # Lot size — 1% risk rule
        # risk_amount = balance × 1%
        # lot = risk_amount / (sl_pips × pip_value_per_lot)
        # Standard lot pip value ≈ $10 (EURUSD), micro = $0.10
        risk_amount      = self.balance * (self.MAX_RISK_PERCENT / 100)
        lot_raw          = risk_amount / (sl_pips * pip_val_std) if sl_pips > 0 else 0
        lot_size         = round(max(0.01, min(lot_raw, 10.0)), 2)

        rr_ratio         = round(tp_pips / sl_pips, 2) if sl_pips > 0 else 0

        result = {
            "approved":       True,
            "signal":         signal,
            "entry":          entry,
            "sl_price":       sl_price,
            "tp_price":       tp_price,
            "sl_pips":        sl_pips,
            "tp_pips":        tp_pips,
            "lot_size":       lot_size,
            "risk_percent":   self.MAX_RISK_PERCENT,
            "risk_amount_usd": round(risk_amount, 2),
            "rr_ratio":       rr_ratio,
            "balance":        self.balance,
            "reject_reason":  None,
        }

        # Final RR check
        if rr_ratio < self.MIN_RR:
            result["approved"]      = False
            result["reject_reason"] = f"RR {rr_ratio} < min {self.MIN_RR}"

        log.info(
            f"[RiskAgent] {signal} | Entry: {entry} | "
            f"SL: {sl_price} ({sl_pips}p) | "
            f"TP: {tp_price} ({tp_pips}p) | "
            f"Lot: {lot_size} | RR: {rr_ratio} | "
            f"Approved: {result['approved']}"
        )
        return result

    def _no_trade(self, reason: str) -> dict:
        log.info(f"[RiskAgent] No trade — {reason}")
        return {
            "approved":        False,
            "signal":          "NO TRADE",
            "reject_reason":   reason,
            "entry":           None,
            "sl_price":        None,
            "tp_price":        None,
            "lot_size":        0,
            "sl_pips":         0,
            "tp_pips":         0,
            "rr_ratio":        0,
            "risk_amount_usd": 0,
        }

    def print_summary(self, result: dict) -> None:
        bar  = "═" * 44
        icon = "✅" if result["approved"] else "⛔"
        log.info(bar)
        log.info(f"  {icon}  RISK AGENT")
        log.info(bar)
        log.info(f"  Approved    : {result['approved']}")
        if result.get("reject_reason"):
            log.info(f"  Rejected    : {result['reject_reason']}")
        if result["approved"]:
            log.info(f"  Signal      : {result['signal']}")
            log.info(f"  Entry       : {result['entry']}")
            log.info(f"  SL          : {result['sl_price']}  ({result['sl_pips']} pips)")
            log.info(f"  TP          : {result['tp_price']}  ({result['tp_pips']} pips)")
            log.info(f"  Lot size    : {result['lot_size']}")
            log.info(f"  Risk        : {result['risk_percent']}%  (${result.get('risk_amount_usd')})")
            log.info(f"  R:R         : 1:{result['rr_ratio']}")
        log.info(bar)

    def get_ai_context(self, result: dict) -> dict:
        return {
            "risk_approved":  result["approved"],
            "risk_lot":       result.get("lot_size", 0),
            "risk_sl_pips":   result.get("sl_pips", 0),
            "risk_tp_pips":   result.get("tp_pips", 0),
            "risk_rr":        result.get("rr_ratio", 0),
            "risk_reject":    result.get("reject_reason"),
        }