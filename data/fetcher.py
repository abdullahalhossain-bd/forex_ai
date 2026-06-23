# data/fetcher.py
# ============================================================
# Multi-Source Data Fetcher (MT5-first)
# Primary Source: MetaTrader5 (native forex data)
# Fallback Source: TradingView via tvdatafeed
# ============================================================

import pandas as pd
import numpy as np
import MetaTrader5 as mt5
from utils.logger import get_logger

log = get_logger(__name__)

# ─────────────────────────────────────────────────────────────
# MT5 TIMEFRAME MAPPING
# ─────────────────────────────────────────────────────────────
TIMEFRAME_MAP = {
    "M5":   mt5.TIMEFRAME_M5,       # 5 minutes
    "M15":  mt5.TIMEFRAME_M15,      # 15 minutes
    "M30":  mt5.TIMEFRAME_M30,      # 30 minutes
    "H1":   mt5.TIMEFRAME_H1,       # 1 hour
    "H4":   mt5.TIMEFRAME_H4,       # 4 hours
    "D1":   mt5.TIMEFRAME_D1,       # 1 day
    "W1":   mt5.TIMEFRAME_W1,       # 1 week
    "MN1":  mt5.TIMEFRAME_MN1,      # 1 month
    # Aliases for backward compatibility
    "5m":   mt5.TIMEFRAME_M5,
    "15m":  mt5.TIMEFRAME_M15,
    "30m":  mt5.TIMEFRAME_M30,
    "1h":   mt5.TIMEFRAME_H1,
    "4h":   mt5.TIMEFRAME_H4,
    "1d":   mt5.TIMEFRAME_D1,
}

# Symbol normalization — internal style to MT5 style
# MT5 symbols are typically EURUSD, GBPUSD (no =X suffix)
SYMBOL_MAP = {
    # Forex majors
    "EURUSD":      "EURUSD",
    "GBPUSD":      "GBPUSD",
    "USDJPY":      "USDJPY",
    "AUDUSD":      "AUDUSD",
    "USDCHF":      "USDCHF",
    "USDCAD":      "USDCAD",
    "NZDUSD":      "NZDUSD",
    # Forex crosses
    "EURGBP":      "EURGBP",
    "EURJPY":      "EURJPY",
    "EURCHF":      "EURCHF",
    "EURAUD":      "EURAUD",
    "EURCAD":      "EURCAD",
    "EURNZD":      "EURNZD",
    "GBPJPY":      "GBPJPY",
    "GBPCHF":      "GBPCHF",
    "GBPAUD":      "GBPAUD",
    "GBPCAD":      "GBPCAD",
    "GBPNZD":      "GBPNZD",
    "AUDJPY":      "AUDJPY",
    "AUDCHF":      "AUDCHF",
    "AUDCAD":      "AUDCAD",
    "AUDNZD":      "AUDNZD",
    "NZDJPY":      "NZDJPY",
    "NZDCHF":      "NZDCHF",
    "NZDCAD":      "NZDCAD",
    "CADJPY":      "CADJPY",
    "CADCHF":      "CADCHF",
    "CHFJPY":      "CHFJPY",
    # Metals
    "XAUUSD":      "XAUUSD",
    "XAGUSD":      "XAGUSD",
    # Legacy/alternative formats
    "EUR/USD":     "EURUSD",
    "GBP/USD":     "GBPUSD",
    "USD/JPY":     "USDJPY",
    "AUD/USD":     "AUDUSD",
    "USD/CHF":     "USDCHF",
    "USD/CAD":     "USDCAD",
    "EUR/USDT":    "EURUSD",
    "GBP/USDT":    "GBPUSD",
    "EURUSD=X":    "EURUSD",
    "GBPUSD=X":    "GBPUSD",
    "USDJPY=X":    "USDJPY",
}


class DataFetcher:
    """
    MT5-first data fetcher.
    
    Uses MetaTrader5 to fetch OHLCV data for forex/metals.
    Fallback to tvdatafeed if MT5 is unavailable.
    """

    def __init__(self):
        self.source = self._detect_source()
        log.info(f"[OK] DataFetcher initialized | source: {self.source}")

    def _detect_source(self):
        """Detect available data source."""
        try:
            # Try MT5 first
            if mt5.initialize():
                mt5.shutdown()  # Just test connection; will reinit in fetch()
                return "mt5"
        except Exception as e:
            log.debug(f"MT5 not available: {e}")

        try:
            from tvdatafeed import TvDatafeed
            return "tvdatafeed"
        except ImportError:
            log.debug("tvdatafeed not available")

        return "unavailable"

    def fetch_ohlcv(self, symbol="EURUSD", timeframe="M15", limit=300, periods=None):
        """
        Fetch OHLCV data from the available source.
        
        Args:
            symbol (str):     Trading pair (e.g., "EURUSD", "EUR/USD", "EURUSD=X")
            timeframe (str):   Timeframe (e.g., "M5", "M15", "H1", "15m", "1h")
            limit (int):      Number of candles to fetch (default 300)
            periods (int):    Alias for limit (backward compatibility)
        
        Returns:
            pd.DataFrame: OHLCV data with columns ['open', 'high', 'low', 'close', 'volume']
                         and datetime index. Returns None on failure.
        """
        # Backward compatibility: periods → limit
        if periods is not None:
            limit = periods

        symbol = self._normalize_symbol(symbol)
        timeframe = self._normalize_timeframe(timeframe)

        log.info(f"Fetching {symbol} | {timeframe} | {limit} candles...")

        if self.source == "mt5":
            return self._fetch_mt5(symbol, timeframe, limit)
        elif self.source == "tvdatafeed":
            return self._fetch_tvdatafeed(symbol, timeframe, limit)
        else:
            log.error("No data source available (MT5 not connected, tvdatafeed not installed)")
            return None

    # ─────────────────────────────────────────────
    # SOURCE 1: MetaTrader5 (PRIMARY)
    # ─────────────────────────────────────────────

    def _fetch_mt5(self, symbol, timeframe, limit):
        """
        Fetch OHLCV data from MetaTrader5.
        
        Args:
            symbol (str):     MT5 symbol name (e.g., "EURUSD")
            timeframe (str):  Timeframe key (e.g., "M15")
            limit (int):      Number of candles to fetch
        
        Returns:
            pd.DataFrame: OHLCV data, or None on error
        """
        try:
            # Ensure MT5 is initialized
            if not mt5.initialize():
                log.error(f"[MT5] Failed to initialize: {mt5.last_error()}")
                return None

            # Map timeframe string to MT5 constant
            if timeframe not in TIMEFRAME_MAP:
                log.error(f"[MT5] Unknown timeframe: {timeframe}")
                return None

            mt5_timeframe = TIMEFRAME_MAP[timeframe]

            # Activate symbol in Market Watch
            if not mt5.symbol_select(symbol, True):
                error_code, error_msg = mt5.last_error()
                log.error(
                    f"[MT5] Failed to select symbol '{symbol}': "
                    f"code={error_code}, msg={error_msg}. "
                    f"Check if symbol exists on your broker."
                )
                return None

            log.debug(f"[MT5] Symbol selected: {symbol}")

            # Fetch candles from position 0 (most recent) backward
            candles = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, limit)

            if candles is None:
                error_code, error_msg = mt5.last_error()
                log.error(
                    f"[MT5] copy_rates_from_pos failed for {symbol} {timeframe}: "
                    f"code={error_code}, msg={error_msg}"
                )
                return None

            if len(candles) == 0:
                log.warning(f"[MT5] No candles returned for {symbol} {timeframe}")
                return None

            # Convert numpy structured array → pandas DataFrame
            df = pd.DataFrame(candles)

            # Convert 'time' from Unix seconds to datetime
            df['time'] = pd.to_datetime(df['time'], unit='s')

            # Set datetime as index
            df.set_index('time', inplace=True)

            # Keep only OHLCV columns, standardize to lowercase
            df = df[['open', 'high', 'low', 'close', 'tick_volume']].copy()
            df.rename(columns={'tick_volume': 'volume'}, inplace=True)

            # Ensure correct column order
            df = df[['open', 'high', 'low', 'close', 'volume']]

            log.info(
                f"[OK] Got {len(df)} candles for {symbol} {timeframe} via MT5 | "
                f"Latest: {df.index[-1]}"
            )

            return df

        except Exception as e:
            log.error(f"[MT5] Exception during fetch: {type(e).__name__}: {e}")
            return None
        finally:
            # Keep MT5 initialized for subsequent calls (don't shutdown)
            pass

    # ─────────────────────────────────────────────
    # SOURCE 2: TradingView (FALLBACK)
    # ─────────────────────────────────────────────

    def _fetch_tvdatafeed(self, symbol, timeframe, limit):
        """
        Fetch OHLCV data from TradingView (fallback).
        
        Args:
            symbol (str):     Trading pair (e.g., "EURUSD")
            timeframe (str):  Timeframe (e.g., "M15", "15m")
            limit (int):      Number of candles
        
        Returns:
            pd.DataFrame: OHLCV data, or None on error
        """
        try:
            from tvdatafeed import TvDatafeed, Interval

            tf_map = {
                'M5':   Interval.in_5_minute,
                'M15':  Interval.in_15_minute,
                'M30':  Interval.in_30_minute,
                'H1':   Interval.in_1_hour,
                'H4':   Interval.in_4_hour,
                'D1':   Interval.in_daily,
            }

            tv_timeframe = tf_map.get(timeframe, Interval.in_15_minute)

            tv = TvDatafeed()
            raw = tv.get_hist(
                symbol=symbol,
                exchange='FX',
                interval=tv_timeframe,
                n_bars=limit,
            )

            if raw is None or raw.empty:
                log.error(f"[TVDatafeed] No data returned for {symbol}")
                return None

            df = raw[['open', 'high', 'low', 'close', 'volume']]
            log.info(
                f"[OK] Got {len(df)} candles for {symbol} {timeframe} via TradingView | "
                f"Latest: {df.index[-1]}"
            )
            return df

        except Exception as e:
            log.error(f"[TVDatafeed] Exception: {type(e).__name__}: {e}")
            return None

    # ─────────────────────────────────────────────
    # UTILITY METHODS
    # ─────────────────────────────────────────────

    def _normalize_symbol(self, symbol: str) -> str:
        """
        Normalize symbol to MT5 format (e.g., "EURUSD").
        
        Converts:
          - "EUR/USD" → "EURUSD"
          - "EURUSD=X" → "EURUSD"
          - "EUR/USDT" → "EURUSD"
          - "EURUSD" → "EURUSD"
        """
        symbol = str(symbol).upper().strip()
        # Use mapping if available
        if symbol in SYMBOL_MAP:
            return SYMBOL_MAP[symbol]
        # Otherwise, clean it manually
        symbol = (
            symbol
            .replace("=X", "")
            .replace("/", "")
            .replace("USDT", "USD")
        )
        return symbol

    def _normalize_timeframe(self, timeframe: str) -> str:
        """
        Normalize timeframe to TIMEFRAME_MAP key (e.g., "M15").
        
        Converts:
          - "15m" → "M15"
          - "1h" → "H1"
          - "M15" → "M15" (no change)
        """
        timeframe = str(timeframe).upper().strip()
        if timeframe in TIMEFRAME_MAP:
            return timeframe
        # Aliases: convert 15m → M15, 1h → H1, etc.
        if timeframe.endswith("M"):
            return "M" + timeframe[:-1]
        if timeframe.endswith("H"):
            return "H" + timeframe[:-1]
        if timeframe.endswith("D"):
            return "D" + timeframe[:-1]
        log.warning(f"Unknown timeframe format: {timeframe}, defaulting to M15")
        return "M15"