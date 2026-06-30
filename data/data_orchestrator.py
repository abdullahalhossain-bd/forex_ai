"""
data/data_orchestrator.py — Day 93 Unified Data Orchestrator
============================================================
Single entry point for ALL market data needs. Decides whether to
pull from MT5 (preferred — when running on Windows with MT5
terminal) or from external APIs (Twelve Data, yfinance, etc. —
fallback when MT5 unavailable, e.g. on Linux VPS).

PRINCIPLE (per user request):
    "যা যা সম্ভব MT5 থেকে নেবে, যা নেয়া যায় না তার জন্য API"

What MT5 provides (prefer MT5 for these):
  ✓ OHLCV candles (any timeframe, real-time + historical)
  ✓ Account info (balance, equity, margin, free margin)
  ✓ Open positions (ticket, symbol, lot, sl, tp, pnl)
  ✓ Pending orders
  ✓ Symbol info (spread, contract size, digits, tick value)
  ✓ Order execution (market buy/sell, modify SL/TP, close)
  ✓ Tick data (real-time bid/ask)

What MT5 does NOT provide (use external API for these):
  ✗ News sentiment          → NewsAPI.org + Forex Factory scraper
  ✗ Economic calendar       → Forex Factory scraper
  ✗ Intermarket data (DXY, Gold, Oil, VIX) → yfinance
  ✗ LLM brain               → OpenRouter / Groq / Cerebras
  ✗ Currency strength scores → computed from MT5 data ourselves
  ✗ Breaking news headlines → NewsAPI.org

USAGE:
    from data.data_orchestrator import get_data_orchestrator
    orch = get_data_orchestrator()

    # Candles — tries MT5 first, falls back to API
    df = orch.get_candles("EURUSD", "M15", limit=300)

    # Account info — MT5 only (returns None on Linux VPS)
    account = orch.get_account_info()

    # Open positions — MT5 only
    positions = orch.get_open_positions()

    # Symbol info (spread, digits) — MT5 preferred
    info = orch.get_symbol_info("EURUSD")

    # Where did the last candle come from?
    print(orch.last_source)  # "mt5" | "twelve_data" | "yfinance" | ...
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import pandas as pd

from utils.logger import get_logger

log = get_logger("data_orchestrator")


def _get_mt5_credentials():
    """Read MT5 credentials from environment."""
    login = int(os.getenv("MT5_LOGIN", 0))
    password = os.getenv("MT5_PASSWORD", "")
    server = os.getenv("MT5_SERVER", "")
    return login, password, server


class DataOrchestrator:
    """Unified data access layer — MT5 first, API fallback."""

    def __init__(self):
        self._fetcher = None
        self._mt5 = None
        self._mt5_initialized = False
        self.last_source: str = "unknown"

    # ─────────────────────────────────────────────────────────
    # LAZY INITIALIZERS
    # ─────────────────────────────────────────────────────────

    def _get_fetcher(self):
        """Lazy-init the DataFetcher (used for API fallback)."""
        if self._fetcher is None:
            from data.fetcher import DataFetcher
            self._fetcher = DataFetcher()
        return self._fetcher

    def _get_mt5(self):
        """Lazy-init MT5 connection. Returns MT5DataFeed or None."""
        if self._mt5_initialized:
            return self._mt5
        self._mt5_initialized = True
        try:
            from broker.mt5_connection import MT5_AVAILABLE
            if not MT5_AVAILABLE:
                log.debug("[Orchestrator] MT5 not available (Linux/Mac) — will use API fallback")
                return None
            from broker.mt5_data import MT5DataFeed
            from broker.mt5_connection import MT5Connection
            # FIX: pass credentials from environment
            login, password, server = _get_mt5_credentials()
            conn = MT5Connection(login=login, password=password, server=server)
            if not conn.connect():
                log.warning("[Orchestrator] MT5 connect failed — using API fallback")
                return None
            self._mt5 = MT5DataFeed()
            log.info("[Orchestrator] MT5 connected — using MT5 as primary data source")
        except Exception as e:
            log.warning(f"[Orchestrator] MT5 init failed: {e} — using API fallback")
            self._mt5 = None
        return self._mt5

    # ─────────────────────────────────────────────────────────
    # CANDLES (the most-used method)
    # ─────────────────────────────────────────────────────────

    def get_candles(
        self,
        symbol: str,
        timeframe: str = "M15",
        limit: int = 300,
    ) -> Optional[pd.DataFrame]:
        """Get OHLCV candles — MT5 first, API fallback."""
        mt5 = self._get_mt5()
        if mt5 is not None:
            try:
                df = mt5.get_candles(symbol, timeframe, count=limit)
                if df is not None and len(df) > 0:
                    df = self._normalize_mt5_candles(df)
                    self.last_source = "mt5"
                    log.debug(f"[Orchestrator] {symbol} {timeframe}: {len(df)} candles from mt5")
                    return df
            except Exception as e:
                log.warning(f"[Orchestrator] MT5 candle fetch failed: {e} — falling back to API")

        fetcher = self._get_fetcher()
        df = fetcher.fetch_ohlcv(symbol, timeframe, limit=limit)
        if df is not None and len(df) > 0:
            self.last_source = fetcher.source
            log.debug(f"[Orchestrator] {symbol} {timeframe}: {len(df)} candles from {fetcher.source}")
        else:
            self.last_source = "failed"
        return df

    @staticmethod
    def _normalize_mt5_candles(df: pd.DataFrame) -> pd.DataFrame:
        """Normalize MT5 candle DataFrame to match API format."""
        rename_map = {
            "tick_volume": "volume",
            "real_volume": "volume",
        }
        df = df.rename(columns=rename_map)
        if "volume" not in df.columns:
            df["volume"] = 0.0
        keep = [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]
        return df[keep]

    # ─────────────────────────────────────────────────────────
    # ACCOUNT INFO (MT5 only)
    # ─────────────────────────────────────────────────────────

    def get_account_info(self) -> Optional[Dict[str, Any]]:
        """Get account balance/equity/margin — MT5 only."""
        mt5 = self._get_mt5()
        if mt5 is None:
            log.debug("[Orchestrator] get_account_info: MT5 unavailable")
            return None
        try:
            from broker.mt5_connection import MT5Connection
            # FIX: pass credentials
            login, password, server = _get_mt5_credentials()
            conn = MT5Connection(login=login, password=password, server=server)
            return conn.get_account_info()
        except Exception as e:
            log.warning(f"[Orchestrator] get_account_info failed: {e}")
            return None

    # ─────────────────────────────────────────────────────────
    # OPEN POSITIONS (MT5 only)
    # ─────────────────────────────────────────────────────────

    def get_open_positions(self) -> List[Dict[str, Any]]:
        """Get list of currently-open positions — MT5 only."""
        mt5 = self._get_mt5()
        if mt5 is None:
            log.debug("[Orchestrator] get_open_positions: MT5 unavailable")
            return []
        try:
            import MetaTrader5 as mt5_lib
            positions = mt5_lib.positions_get()
            if positions is None:
                return []
            result = []
            for p in positions:
                result.append({
                    "ticket":        p.ticket,
                    "symbol":        p.symbol,
                    "type":          "buy" if p.type == 0 else "sell",
                    "volume":        p.volume,
                    "sl":            p.sl,
                    "tp":            p.tp,
                    "pnl":           p.profit,
                    "swap":          p.swap,
                    "open_time":     pd.Timestamp(p.time, unit="s"),
                    "price_open":    p.price_open,
                    "price_current": p.price_current,
                })
            return result
        except Exception as e:
            log.warning(f"[Orchestrator] get_open_positions failed: {e}")
            return []

    # ─────────────────────────────────────────────────────────
    # PENDING ORDERS (MT5 only)
    # ─────────────────────────────────────────────────────────

    def get_pending_orders(self) -> List[Dict[str, Any]]:
        """Get list of pending orders — MT5 only."""
        mt5 = self._get_mt5()
        if mt5 is None:
            return []
        try:
            import MetaTrader5 as mt5_lib
            orders = mt5_lib.orders_get()
            if orders is None:
                return []
            return [{
                "ticket":    o.ticket,
                "symbol":    o.symbol,
                "type":      o.type,
                "volume":    o.volume_current,
                "price":     o.price_open,
                "sl":        o.sl,
                "tp":        o.tp,
                "open_time": pd.Timestamp(o.time_setup, unit="s"),
            } for o in orders]
        except Exception as e:
            log.warning(f"[Orchestrator] get_pending_orders failed: {e}")
            return []

    # ─────────────────────────────────────────────────────────
    # SYMBOL INFO (MT5 preferred, API fallback)
    # ─────────────────────────────────────────────────────────

    def get_symbol_info(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get symbol metadata — spread, digits, contract size, etc."""
        mt5 = self._get_mt5()
        if mt5 is not None:
            try:
                import MetaTrader5 as mt5_lib
                info = mt5_lib.symbol_info(symbol)
                if info is not None:
                    return {
                        "symbol":        info.symbol,
                        "digits":        info.digits,
                        "spread":        info.spread,
                        "point":         info.point,
                        "contract_size": info.trade_contract_size,
                        "tick_value":    info.trade_tick_value,
                        "tick_size":     info.trade_tick_size,
                        "min_lot":       info.volume_min,
                        "max_lot":       info.volume_max,
                        "lot_step":      info.volume_step,
                        "source":        "mt5",
                    }
            except Exception as e:
                log.warning(f"[Orchestrator] MT5 symbol_info failed: {e}")

        return {
            "symbol":        symbol,
            "digits":        5,
            "spread":        10,
            "point":         0.00001,
            "contract_size": 100000,
            "tick_value":    1.0,
            "tick_size":     0.00001,
            "min_lot":       0.01,
            "max_lot":       100.0,
            "lot_step":      0.01,
            "source":        "fallback",
        }

    # ─────────────────────────────────────────────────────────
    # TICK DATA (real-time bid/ask — MT5 only)
    # ─────────────────────────────────────────────────────────

    def get_tick(self, symbol: str) -> Optional[Dict[str, float]]:
        """Get real-time bid/ask — MT5 only."""
        mt5 = self._get_mt5()
        if mt5 is None:
            return None
        try:
            return mt5.get_tick(symbol)
        except Exception as e:
            log.warning(f"[Orchestrator] get_tick failed: {e}")
            return None

    # ─────────────────────────────────────────────────────────
    # MULTI-TIMEFRAME CANDLES
    # ─────────────────────────────────────────────────────────

    def get_multi_timeframe(
        self,
        symbol: str,
        timeframes: List[str] = None,
        limit: int = 100,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch candles for multiple timeframes in one call."""
        if timeframes is None:
            timeframes = ["D1", "H4", "H1", "M15"]

        result = {}
        for tf in timeframes:
            df = self.get_candles(symbol, tf, limit=limit)
            if df is not None:
                result[tf] = df
            else:
                log.warning(f"[Orchestrator] {symbol} {tf}: no data")
        return result

    # ─────────────────────────────────────────────────────────
    # ORDER EXECUTION (MT5 only)
    # ─────────────────────────────────────────────────────────

    def place_market_order(
        self,
        symbol: str,
        direction: str,
        volume: float,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        deviation: int = 20,
        magic: int = 0,
        comment: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Place a market order via MT5."""
        mt5 = self._get_mt5()
        if mt5 is None:
            log.warning("[Orchestrator] place_market_order: MT5 unavailable — use SimulatedExecutor")
            return None
        try:
            import MetaTrader5 as mt5_lib
            from broker.mt5_connection import MT5Connection
            # FIX: pass credentials
            login, password, server = _get_mt5_credentials()
            conn = MT5Connection(login=login, password=password, server=server)
            if not conn.connect():
                return None

            tick = mt5_lib.symbol_info_tick(symbol)
            if tick is None:
                log.error(f"[Orchestrator] no tick for {symbol}")
                return None

            price = tick.ask if direction.lower() == "buy" else tick.bid
            order_type = mt5_lib.ORDER_TYPE_BUY if direction.lower() == "buy" else mt5_lib.ORDER_TYPE_SELL

            request = {
                "action":       mt5_lib.TRADE_ACTION_DEAL,
                "symbol":       symbol,
                "volume":       float(volume),
                "type":         order_type,
                "price":        price,
                "sl":           float(sl) if sl else 0.0,
                "tp":           float(tp) if tp else 0.0,
                "deviation":    deviation,
                "magic":        magic,
                "comment":      comment[:31],
                "type_time":    mt5_lib.ORDER_TIME_GTC,
                "type_filling": mt5_lib.ORDER_FILLING_IOC,
            }
            result = mt5_lib.order_send(request)
            if result is None:
                log.error("[Orchestrator] order_send returned None")
                return None
            return {
                "ticket":  result.order,
                "retcode": result.retcode,
                "comment": result.comment,
                "price":   result.price,
                "volume":  result.volume,
                "success": result.retcode == 10009,
            }
        except Exception as e:
            log.error(f"[Orchestrator] place_market_order failed: {e}")
            return None

    def close_position(self, ticket: int) -> bool:
        """Close an open position by ticket — MT5 only."""
        mt5 = self._get_mt5()
        if mt5 is None:
            return False
        try:
            import MetaTrader5 as mt5_lib
            position = mt5_lib.positions_get(ticket=ticket)
            if not position:
                log.error(f"[Orchestrator] position {ticket} not found")
                return False
            pos = position[0]
            tick = mt5_lib.symbol_info_tick(pos.symbol)
            if tick is None:
                return False
            close_type = mt5_lib.ORDER_TYPE_SELL if pos.type == 0 else mt5_lib.ORDER_TYPE_BUY
            close_price = tick.bid if close_type == mt5_lib.ORDER_TYPE_SELL else tick.ask

            request = {
                "action":       mt5_lib.TRADE_ACTION_DEAL,
                "symbol":       pos.symbol,
                "volume":       pos.volume,
                "type":         close_type,
                "position":     ticket,
                "price":        close_price,
                "deviation":    20,
                "magic":        0,
                "comment":      "close by bot",
                "type_time":    mt5_lib.ORDER_TIME_GTC,
                "type_filling": mt5_lib.ORDER_FILLING_IOC,
            }
            result = mt5_lib.order_send(request)
            return result is not None and result.retcode == 10009
        except Exception as e:
            log.error(f"[Orchestrator] close_position failed: {e}")
            return False

    # ─────────────────────────────────────────────────────────
    # STATUS / DIAGNOSTICS
    # ─────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Return diagnostic info about which data sources are active."""
        mt5 = self._get_mt5()
        fetcher_source = "unknown"
        try:
            fetcher_source = self._get_fetcher().source
        except Exception:
            pass
        return {
            "mt5_available":    mt5 is not None,
            "mt5_initialized":  self._mt5_initialized,
            "api_source":       fetcher_source,
            "last_source":      self.last_source,
            "preferred_source": os.getenv("PREFERRED_DATA_SOURCE", ""),
        }


# ── Singleton ─────────────────────────────────────────────────────

_ORCHESTRATOR: Optional[DataOrchestrator] = None


def get_data_orchestrator() -> DataOrchestrator:
    global _ORCHESTRATOR
    if _ORCHESTRATOR is None:
        _ORCHESTRATOR = DataOrchestrator()
    return _ORCHESTRATOR