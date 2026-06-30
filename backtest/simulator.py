from dataclasses import dataclass, asdict

from utils.logger import get_logger

log = get_logger("backtest_simulator")

PIP_SIZE = {
    "EURUSD": 0.0001,
    "GBPUSD": 0.0001,
    "USDJPY": 0.01,
    "USDCHF": 0.0001,
    "AUDUSD": 0.0001,
    "USDCAD": 0.0001,
    "DEFAULT": 0.0001,
}

SPREAD_PIPS = {
    "EURUSD": 1.2,
    "GBPUSD": 1.5,
    "USDJPY": 1.3,
    "USDCHF": 1.8,
    "AUDUSD": 1.4,
    "USDCAD": 1.7,
    "DEFAULT": 1.5,
}


@dataclass
class TradePosition:
    pair: str
    strategy: str
    strategy_version: str
    direction: str
    entry_time: str
    entry_index: int
    entry_requested: float
    entry_price: float
    sl: float
    tp: float
    lot: float
    confidence: int
    rr_ratio: float
    risk_usd: float
    stop_pips: float
    slippage_pips: float
    spread_pips: float
    commission_per_lot: float
    reason: str
    pattern: str
    regime: str
    session: str
    timeout_candles: int


class ForexSimulator:
    def __init__(
        self,
        commission_per_lot: float = 7.0,
        max_slippage_pips: float = 0.8,
        default_timeout_candles: int = 192,
    ):
        self.commission_per_lot = commission_per_lot
        self.max_slippage_pips = max_slippage_pips
        self.default_timeout_candles = default_timeout_candles

    def open_position(
        self,
        candle,
        signal: dict,
        pair: str,
        balance: float,
        risk_per_trade: float = 0.01,
        candle_index: int = 0,
    ) -> TradePosition:
        symbol = self._clean_pair(pair)
        direction = str(signal["signal"]).upper()
        pip = PIP_SIZE.get(symbol, PIP_SIZE["DEFAULT"])
        stop_pips = max(float(signal.get("stop_pips", 15)), 1.0)
        rr_ratio = max(float(signal.get("rr_ratio", 2.0)), 1.0)
        risk_usd = round(balance * risk_per_trade, 2)
        pip_value = 9.0 if "JPY" in symbol else 10.0
        lot = round(max(0.01, min(risk_usd / (stop_pips * pip_value), 100.0)), 2)

        requested = float(candle["open"])
        spread_pips = float(signal.get("spread_pips", SPREAD_PIPS.get(symbol, SPREAD_PIPS["DEFAULT"])))
        slippage_pips = min(self.max_slippage_pips, self._deterministic_slippage(candle, pip))

        fill_adjustment = (spread_pips / 2 + slippage_pips) * pip
        entry_price = requested + fill_adjustment if direction == "BUY" else requested - fill_adjustment

        stop_distance = stop_pips * pip
        tp_distance = stop_distance * rr_ratio
        sl = entry_price - stop_distance if direction == "BUY" else entry_price + stop_distance
        tp = entry_price + tp_distance if direction == "BUY" else entry_price - tp_distance

        position = TradePosition(
            pair=symbol,
            strategy=signal.get("strategy_name", "Unknown"),
            strategy_version=signal.get("strategy_version", "v1"),
            direction=direction,
            entry_time=str(getattr(candle, "name", candle_index)),
            entry_index=candle_index,
            entry_requested=round(requested, 5),
            entry_price=round(entry_price, 5),
            sl=round(sl, 5),
            tp=round(tp, 5),
            lot=lot,
            confidence=int(round(signal.get("confidence", 0))),
            rr_ratio=round(rr_ratio, 2),
            risk_usd=risk_usd,
            stop_pips=round(stop_pips, 1),
            slippage_pips=round(slippage_pips, 2),
            spread_pips=round(spread_pips, 2),
            commission_per_lot=self.commission_per_lot,
            reason=signal.get("reason", ""),
            pattern=signal.get("pattern", "none"),
            regime=signal.get("regime", "unknown"),
            session=signal.get("session", "unknown"),
            timeout_candles=int(signal.get("timeout_candles", self.default_timeout_candles)),
        )
        log.info(
            f"[Simulator] OPEN {position.strategy} | {position.direction} {position.pair} "
            f"@ {position.entry_price} | SL {position.sl} | TP {position.tp} | Lot {position.lot}"
        )
        return position

    def evaluate_exit(self, position: TradePosition, candle, candle_index: int) -> dict | None:
        high = float(candle["high"])
        low = float(candle["low"])

        if candle_index - position.entry_index >= position.timeout_candles:
            return self._close_trade(position, float(candle["close"]), "TIMEOUT", candle, candle_index)

        if position.direction == "BUY":
            sl_hit = low <= position.sl
            tp_hit = high >= position.tp
        else:
            sl_hit = high >= position.sl
            tp_hit = low <= position.tp

        if sl_hit:
            return self._close_trade(position, position.sl, "SL HIT", candle, candle_index)
        if tp_hit:
            return self._close_trade(position, position.tp, "TP HIT", candle, candle_index)
        return None

    def force_close(self, position: TradePosition, candle, candle_index: int, reason: str = "END OF DATA") -> dict:
        return self._close_trade(position, float(candle["close"]), reason, candle, candle_index)

    def _close_trade(self, position: TradePosition, raw_exit: float, reason: str, candle, candle_index: int) -> dict:
        pip = PIP_SIZE.get(position.pair, PIP_SIZE["DEFAULT"])
        spread_exit_adjustment = (position.spread_pips / 2) * pip
        exit_price = raw_exit - spread_exit_adjustment if position.direction == "BUY" else raw_exit + spread_exit_adjustment

        if position.direction == "BUY":
            pnl_pips = (exit_price - position.entry_price) / pip
        else:
            pnl_pips = (position.entry_price - exit_price) / pip

        pip_value = 9.0 if "JPY" in position.pair else 10.0
        gross_pnl = pnl_pips * pip_value * position.lot
        commission = round(position.commission_per_lot * position.lot, 2)
        net_pnl = round(gross_pnl - commission, 2)

        return {
            **asdict(position),
            "exit_price": round(exit_price, 5),
            "exit_time": str(getattr(candle, "name", candle_index)),
            "exit_index": candle_index,
            "close_reason": reason,
            "result": "WIN" if net_pnl > 0 else ("LOSS" if net_pnl < 0 else "BREAKEVEN"),
            "pnl": net_pnl,
            "pnl_pips": round(pnl_pips, 1),
            "commission": commission,
            "spread_cost": round(position.spread_pips * pip_value * position.lot, 2),
            "bars_held": candle_index - position.entry_index,
        }

    def _deterministic_slippage(self, candle, pip: float) -> float:
        candle_range_pips = abs(float(candle["high"]) - float(candle["low"])) / pip if pip else 0
        return round(min(self.max_slippage_pips, max(0.05, candle_range_pips * 0.02)), 2)

    def _clean_pair(self, pair: str) -> str:
        return str(pair).upper().replace("/", "").replace("=X", "").replace("USDT", "USD").strip()
