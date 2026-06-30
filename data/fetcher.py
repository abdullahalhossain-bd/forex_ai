# data/fetcher.py
# ============================================================
# Multi-Source Data Fetcher (MT5-first)
# Primary Source: MetaTrader5 (native forex data)
# Fallback Source: TradingView via tvdatafeed
# ============================================================

import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from utils.logger import get_logger

log = get_logger(__name__)

# ─────────────────────────────────────────────────────────────
# MT5 AVAILABILITY GUARD
# ─────────────────────────────────────────────────────────────
# MetaTrader5 package is Windows-only. On Linux/Mac the import
# would crash the whole project at module-load time. We guard it
# here so DataFetcher still imports cleanly and falls back to
# tvdatafeed / "unavailable" mode when MT5 isn't installed.
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False
    log.info(
        "MetaTrader5 package not installed — DataFetcher will use "
        "tvdatafeed as fallback. Install MetaTrader5 on Windows with "
        "MetaTrader 5 terminal running to enable MT5 data source."
    )

# ─────────────────────────────────────────────────────────────
# MT5 TIMEFRAME MAPPING
# ─────────────────────────────────────────────────────────────
# Built lazily — only resolved when MT5 is available, so importing
# this module on Linux/Mac (where MetaTrader5 is unavailable) doesn't
# raise AttributeError on `mt5.TIMEFRAME_*`.
TIMEFRAME_MAP = {}

def _build_timeframe_map():
    """Populate TIMEFRAME_MAP from live mt5 constants (called once, lazily)."""
    if not MT5_AVAILABLE or TIMEFRAME_MAP:
        return
    TIMEFRAME_MAP.update({
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
    })

# Populate immediately if MT5 is available; otherwise TIMEFRAME_MAP
# stays empty and the fetcher will report "no data source available".
_build_timeframe_map()

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
        """Detect available data source.

        Day 81+ architecture change: MT5 is now the SINGLE SOURCE OF TRUTH.
        TradingView (tvdatafeed) fallback is intentionally disabled because
        trading on data from source A while executing on broker B causes
        data/execution mismatch (different spreads, tick timing, liquidity).

        If MT5 is unavailable, the fetcher returns "unavailable" and the
        trading cycle aborts — this is by design.  Do NOT re-enable the
        TradingView fallback without a corresponding execution-side
        fallback (i.e. paper trading).

        Day 90 addition: yfinance fallback for Linux VPS / dev environments
        where MT5 is unavailable. Yahoo Finance exposes forex pairs as
        EURUSD=X, GBPUSD=X etc. and is free + keyless. Use ONLY for
        demo / paper trading — production should still use MT5 for
        data/execution consistency.
        """
        if MT5_AVAILABLE:
            try:
                if mt5.initialize():
                    mt5.shutdown()  # Just test connection; will reinit in fetch()
                    return "mt5"
            except Exception as e:
                log.debug(f"MT5 not available: {e}")

        # TradingView fallback DISABLED — see docstring above.
        # try:
        #     from tvdatafeed import TvDatafeed  # noqa: F401
        #     return "tvdatafeed"
        # except ImportError:
        #     log.debug("tvdatafeed not available")

        # ── Day 92 — Preferred source override (highest priority) ──
        # If the operator explicitly set PREFERRED_DATA_SOURCE in .env,
        # use it without falling through to yfinance auto-detect.
        # This matters because yfinance is otherwise checked FIRST and
        # would shadow the explicit preference.
        preferred = os.getenv("PREFERRED_DATA_SOURCE", "").lower().strip()
        candidates = [
            ("alpha_vantage", "ALPHA_VANTAGE_API_KEY"),
            ("polygon",       "POLYGON_API_KEY"),
            ("finnhub",       "FINNHUB_API_KEY"),
            ("twelve_data",   "TWELVE_DATA_API_KEY"),
        ]
        if preferred:
            for name, env in candidates:
                if name == preferred and os.getenv(env, "").strip():
                    log.info(f"[DataFetcher] {name} selected (PREFERRED_DATA_SOURCE)")
                    return name
            log.warning(
                f"[DataFetcher] PREFERRED_DATA_SOURCE={preferred!r} but its API "
                f"key is missing — falling through to auto-detect"
            )

        # ── Day 90 — yfinance fallback (Linux VPS / demo only) ──
        try:
            import yfinance  # noqa: F401
            log.info(
                "[DataFetcher] yfinance available — using as demo data source. "
                "Set SIMULATION_MODE=true for execution-side matching."
            )
            return "yfinance"
        except ImportError:
            pass

        # ── Day 92 — Auto-detect (no PREFERRED_DATA_SOURCE set) ──
        for name, env in candidates:
            if os.getenv(env, "").strip():
                log.info(f"[DataFetcher] {name} selected (key found in env)")
                return name

        log.warning(
            "[DataFetcher] MT5 unavailable and TradingView fallback is disabled. "
            "Install MetaTrader5 on Windows with MT5 terminal running to enable data."
        )
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
        elif self.source == "yfinance":
            return self._fetch_yfinance(symbol, timeframe, limit)
        elif self.source == "alpha_vantage":
            return self._fetch_alpha_vantage(symbol, timeframe, limit)
        elif self.source == "polygon":
            return self._fetch_polygon(symbol, timeframe, limit)
        elif self.source == "finnhub":
            return self._fetch_finnhub(symbol, timeframe, limit)
        elif self.source == "twelve_data":
            return self._fetch_twelve_data(symbol, timeframe, limit)
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
        if not MT5_AVAILABLE:
            log.error("[MT5] MetaTrader5 package not installed — cannot fetch")
            return None
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

    # ── Day 90 — yfinance fallback (Linux VPS / demo) ──
    def _fetch_yfinance(self, symbol, timeframe, limit):
        """
        Fetch OHLCV data from Yahoo Finance via yfinance.

        Yahoo exposes forex pairs as EURUSD=X, GBPUSD=X, USDJPY=X etc.
        Metals: GC=F (gold), SI=F (silver). Indexes: ^GSPC (S&P 500).

        Limitations:
          - Yahoo's forex data is delayed 15-20 min.
          - Intraday history is limited to last 60 days for 5m/15m.
          - Use ONLY for demo / paper trading, never production.

        Returns DataFrame with columns ['open','high','low','close','volume']
        and datetime index, or None on failure.
        """
        try:
            import yfinance as yf
        except ImportError:
            log.error("[yfinance] package not installed — run: pip install yfinance")
            return None

        # Map symbol to Yahoo format
        yf_symbol = self._to_yahoo_symbol(symbol)
        # Map timeframe to yfinance interval
        interval = self._tf_to_yfinance_interval(timeframe)
        if interval is None:
            log.error(f"[yfinance] unsupported timeframe: {timeframe}")
            return None

        # Compute period — yfinance doesn't take a candle count.
        # Use a generous lookback; the tail(limit) truncates later.
        period = "60d" if interval in ("5m", "15m", "30m") else "1y"

        try:
            log.debug(f"[yfinance] Fetching {yf_symbol} interval={interval} period={period}")
            df = yf.download(
                yf_symbol,
                interval=interval,
                period=period,
                progress=False,
                auto_adjust=False,
            )
        except Exception as e:
            log.error(f"[yfinance] download failed for {yf_symbol}: {e}")
            return None

        if df is None or len(df) == 0:
            log.error(f"[yfinance] no data returned for {yf_symbol}")
            return None

        # Normalize columns
        df = df.rename(columns={
            "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume",
        })
        # If multi-level columns (yfinance sometimes returns DataFrame
        # with MultiIndex columns when single ticker), flatten.
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Keep only OHLCV
        keep = [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]
        df = df[keep].copy()

        # Truncate to limit
        df = df.tail(limit)

        # Ensure tz-naive (some pipelines expect naive index)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)

        log.info(
            f"[yfinance] {symbol} ({yf_symbol}) | {timeframe} | "
            f"{len(df)} candles | last close: {df['close'].iloc[-1]:.5f}"
        )
        return df

    @staticmethod
    def _to_yahoo_symbol(symbol: str) -> str:
        """Convert internal symbol to Yahoo Finance format."""
        s = symbol.upper().replace("/", "").replace("=", "")
        # Forex majors — Yahoo uses EURUSD=X format
        forex_pairs = {
            "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
            "USDCHF", "NZDUSD", "EURGBP", "EURJPY", "EURCHF",
            "EURAUD", "EURCAD", "EURNZD", "GBPJPY", "GBPCHF",
            "GBPAUD", "GBPCAD", "GBPNZD", "AUDJPY", "AUDCHF",
            "AUDCAD", "AUDNZD", "NZDJPY", "NZDCHF", "NZDCAD",
            "CADJPY", "CADCHF", "CHFJPY",
        }
        if s in forex_pairs:
            return f"{s}=X"
        # Metals — Yahoo uses futures tickers
        if s == "XAUUSD":
            return "GC=F"   # Gold futures
        if s == "XAGUSD":
            return "SI=F"   # Silver futures
        # Indices
        if s == "SPX500":
            return "^GSPC"
        if s == "US30":
            return "^DJI"
        if s == "NAS100":
            return "^NDX"
        if s == "VIX":
            return "^VIX"
        # Default — assume it's already a Yahoo ticker (e.g. AAPL)
        return s

    @staticmethod
    def _tf_to_yfinance_interval(timeframe: str) -> str | None:
        """Map internal timeframe to yfinance interval string."""
        tf = timeframe.upper().replace("M", "").replace("H", "h").replace("D", "d")
        mapping = {
            "5": "5m", "15": "15m", "30": "30m",
            "1H": "1h", "4H": "1h",  # 4h not supported by yfinance — use 1h
            "1D": "1d",
            "5M": "5m", "15M": "15m", "30M": "30m",
        }
        return mapping.get(timeframe.upper()) or mapping.get(tf)

    # ════════════════════════════════════════════════════════════
    # Day 92 — Professional free-tier API providers
    # ════════════════════════════════════════════════════════════
    # Each provider has slightly different symbol formats + interval
    # conventions. We normalize them all to our internal format
    # (EURUSD / M15) so downstream code doesn't care which source
    # produced the data.
    # ════════════════════════════════════════════════════════════

    # ── SOURCE: Alpha Vantage ────────────────────────────────────
    # Free tier: 25 requests/day, 5 req/min. Good for live forex +
    # pre-built technical indicators (RSI, MACD, SMA) without us
    # having to compute them ourselves.
    # Docs: https://www.alphavantage.co/documentation/

    def _fetch_alpha_vantage(self, symbol: str, timeframe: str, limit: int):
        """Fetch OHLCV from Alpha Vantage FX_INTRADAY / FX_DAILY endpoint."""
        import requests
        api_key = os.getenv("ALPHA_VANTAGE_API_KEY", "")
        if not api_key:
            log.error("[AlphaVantage] API key not set")
            return None

        # AV uses EUR/USD format (with slash)
        av_symbol = self._to_av_symbol(symbol)
        av_interval = self._tf_to_av_interval(timeframe)
        if av_interval is None:
            log.error(f"[AlphaVantage] unsupported timeframe: {timeframe}")
            return None

        # FX_INTRADAY for intraday, FX_DAILY for daily
        if av_interval == "daily":
            function = "FX_DAILY"
            params = {
                "function": function,
                "from_symbol": symbol[:3],
                "to_symbol": symbol[3:6],
                "outputsize": "full",
                "apikey": api_key,
            }
        else:
            function = "FX_INTRADAY"
            params = {
                "function": function,
                "from_symbol": symbol[:3],
                "to_symbol": symbol[3:6],
                "interval": av_interval,
                "outputsize": "full",
                "apikey": api_key,
            }

        try:
            url = os.getenv("ALPHA_VANTAGE_BASE_URL", "https://www.alphavantage.co/query")
            log.debug(f"[AlphaVantage] {function} {symbol} interval={av_interval}")
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.error(f"[AlphaVantage] fetch failed: {e}")
            return None

        # Parse the time series
        ts_key = next((k for k in data if k.startswith("Time Series")), None)
        if not ts_key:
            err = data.get("Note") or data.get("Error Message") or "unknown"
            log.warning(f"[AlphaVantage] no time series in response: {err}")
            return None

        ts = data[ts_key]
        rows = []
        for ts_str, ohlc in ts.items():
            try:
                dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S") \
                    if " " in ts_str else datetime.strptime(ts_str, "%Y-%m-%d")
                rows.append({
                    "datetime": dt,
                    "open":  float(ohlc["1. open"]),
                    "high":  float(ohlc["2. high"]),
                    "low":   float(ohlc["3. low"]),
                    "close": float(ohlc["4. close"]),
                    "volume": 0.0,
                })
            except Exception:
                continue

        if not rows:
            log.warning(f"[AlphaVantage] parsed 0 rows for {symbol}")
            return None

        df = pd.DataFrame(rows).sort_values("datetime").tail(limit).reset_index(drop=True)
        df = df.set_index("datetime")
        df.index.name = None
        log.info(
            f"[AlphaVantage] {symbol} | {timeframe} | "
            f"{len(df)} candles | last close: {df['close'].iloc[-1]:.5f}"
        )
        return df

    @staticmethod
    def _to_av_symbol(symbol: str) -> str:
        """Convert EURUSD → EUR/USD (Alpha Vantage format)."""
        s = symbol.upper().replace("/", "").replace("=X", "")
        if len(s) >= 6:
            return f"{s[:3]}/{s[3:6]}"
        return s

    @staticmethod
    def _tf_to_av_interval(timeframe: str):
        """Map internal timeframe to Alpha Vantage interval."""
        tf = timeframe.upper()
        return {
            "M5":  "5min", "5M": "5min",
            "M15": "15min", "15M": "15min",
            "M30": "30min", "30M": "30min",
            "H1":  "60min", "1H": "60min",
            "D1":  "daily", "1D": "daily",
        }.get(tf)

    # ── SOURCE: Polygon.io ──────────────────────────────────────
    # Free tier: 5 requests/min, end-of-day data only (no real-time).
    # Good for backtesting + historical analysis. Real-time needs paid.
    # Docs: https://polygon.io/docs/forex
    def _fetch_polygon(self, symbol: str, timeframe: str, limit: int):
        """Fetch OHLCV from Polygon.io forex aggregates endpoint."""
        import requests
        api_key = os.getenv("POLYGON_API_KEY", "")
        if not api_key:
            log.error("[Polygon] API key not set")
            return None

        # Polygon uses C:EURUSD format
        poly_symbol = f"C:{symbol.upper().replace('/', '').replace('=X', '')}"
        poly_mult, poly_timespan = self._tf_to_polygon(timeframe)
        if poly_mult is None:
            log.error(f"[Polygon] unsupported timeframe: {timeframe}")
            return None

        # Compute date range (Polygon needs explicit from/to)
        from datetime import datetime, timedelta
        end = datetime.utcnow()
        # Generous lookback (limit * interval minutes, in days)
        lookback_days = max(30, limit * poly_mult // (60 * 24) + 30)
        start = end - timedelta(days=lookback_days)

        url = f"https://api.polygon.io/v2/aggs/ticker/{poly_symbol}/range/{poly_mult}/{poly_timespan}/{start.strftime('%Y-%m-%d')}/{end.strftime('%Y-%m-%d')}"
        params = {"adjusted": "true", "sort": "asc", "limit": min(limit, 50000), "apiKey": api_key}

        try:
            log.debug(f"[Polygon] {poly_symbol} {poly_mult}{poly_timespan}")
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.error(f"[Polygon] fetch failed: {e}")
            return None

        results = data.get("results", [])
        if not results:
            log.warning(f"[Polygon] no results for {symbol}")
            return None

        rows = []
        for r in results:
            try:
                # Polygon timestamp is in milliseconds
                dt = datetime.utcfromtimestamp(r["t"] / 1000)
                rows.append({
                    "datetime": dt,
                    "open":  float(r["o"]),
                    "high":  float(r["h"]),
                    "low":   float(r["l"]),
                    "close": float(r["c"]),
                    "volume": float(r.get("v", 0)),
                })
            except Exception:
                continue

        df = pd.DataFrame(rows).tail(limit).reset_index(drop=True)
        df = df.set_index("datetime")
        df.index.name = None
        log.info(
            f"[Polygon] {symbol} | {timeframe} | "
            f"{len(df)} candles | last close: {df['close'].iloc[-1]:.5f}"
        )
        return df

    @staticmethod
    def _tf_to_polygon(timeframe: str):
        """Map internal timeframe to (multiplier, timespan) for Polygon."""
        tf = timeframe.upper()
        return {
            "M5":  (5, "minute"),  "5M":  (5, "minute"),
            "M15": (15, "minute"), "15M": (15, "minute"),
            "M30": (30, "minute"), "30M": (30, "minute"),
            "H1":  (1, "hour"),    "1H":  (1, "hour"),
            "H4":  (4, "hour"),    "4H":  (4, "hour"),
            "D1":  (1, "day"),     "1D":  (1, "day"),
        }.get(tf, (None, None))

    # ── SOURCE: Finnhub ─────────────────────────────────────────
    # Free tier: 60 req/min, forex candles endpoint.
    # Docs: https://finnhub.io/docs/api/forex-candles
    def _fetch_finnhub(self, symbol: str, timeframe: str, limit: int):
        """Fetch OHLCV from Finnhub forex candle endpoint."""
        import requests
        api_key = os.getenv("FINNHUB_API_KEY", "")
        if not api_key:
            log.error("[Finnhub] API key not set")
            return None

        # Finnhub uses OANDA:EUR_USD format
        finn_symbol = f"OANDA:{symbol[:3]}_{symbol[3:6]}"
        finn_res = self._tf_to_finnhub(timeframe)
        if finn_res is None:
            log.error(f"[Finnhub] unsupported timeframe: {timeframe}")
            return None

        from datetime import datetime, timedelta
        end = int(datetime.utcnow().timestamp())
        # Generous lookback
        start = end - 30 * 86400  # 30 days

        url = os.getenv("FINNHUB_BASE_URL", "https://finnhub.io/api/v1") + "/forex/candle"
        params = {"symbol": finn_symbol, "resolution": finn_res,
                  "from": start, "to": end, "token": api_key}

        try:
            log.debug(f"[Finnhub] {finn_symbol} res={finn_res}")
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.error(f"[Finnhub] fetch failed: {e}")
            return None

        if data.get("s") != "ok":
            log.warning(f"[Finnhub] response not ok: {data}")
            return None

        rows = []
        for i, ts in enumerate(data["t"]):
            try:
                dt = datetime.utcfromtimestamp(ts)
                rows.append({
                    "datetime": dt,
                    "open":  float(data["o"][i]),
                    "high":  float(data["h"][i]),
                    "low":   float(data["l"][i]),
                    "close": float(data["c"][i]),
                    "volume": float(data["v"][i]) if i < len(data.get("v", [])) else 0,
                })
            except Exception:
                continue

        df = pd.DataFrame(rows).tail(limit).reset_index(drop=True)
        df = df.set_index("datetime")
        df.index.name = None
        log.info(
            f"[Finnhub] {symbol} | {timeframe} | "
            f"{len(df)} candles | last close: {df['close'].iloc[-1]:.5f}"
        )
        return df

    @staticmethod
    def _tf_to_finnhub(timeframe: str):
        """Map internal timeframe to Finnhub resolution."""
        tf = timeframe.upper()
        return {
            "M5":  "5",  "5M":  "5",
            "M15": "15", "15M": "15",
            "M30": "30", "30M": "30",
            "H1":  "60", "1H":  "60",
            "H4":  "240","4H":  "240",
            "D1":  "D",  "1D":  "D",
        }.get(tf)

    # ── SOURCE: Twelve Data ─────────────────────────────────────
    # Free tier: 800 req/day, 8 req/min, 5-year historical.
    # Docs: https://twelvedata.com/docs#time-series
    def _fetch_twelve_data(self, symbol: str, timeframe: str, limit: int):
        """Fetch OHLCV from Twelve Data time_series endpoint."""
        import requests
        api_key = os.getenv("TWELVE_DATA_API_KEY", "")
        if not api_key:
            log.error("[TwelveData] API key not set")
            return None

        # Twelve Data uses EUR/USD format
        td_symbol = self._to_av_symbol(symbol)  # same format
        td_interval = self._tf_to_twelve_data(timeframe)
        if td_interval is None:
            log.error(f"[TwelveData] unsupported timeframe: {timeframe}")
            return None

        url = os.getenv("TWELVE_DATA_BASE_URL", "https://api.twelvedata.com") + "/time_series"
        params = {
            "symbol": td_symbol,
            "interval": td_interval,
            "outputsize": min(limit, 5000),
            "apikey": api_key,
            "format": "JSON",
        }

        try:
            log.debug(f"[TwelveData] {td_symbol} interval={td_interval}")
            resp = requests.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            log.error(f"[TwelveData] fetch failed: {e}")
            return None

        values = data.get("values", [])
        if not values:
            log.warning(f"[TwelveData] no values: {data.get('message', 'unknown')}")
            return None

        rows = []
        for v in values:
            try:
                dt = datetime.strptime(v["datetime"], "%Y-%m-%d %H:%M:%S")
                rows.append({
                    "datetime": dt,
                    "open":  float(v["open"]),
                    "high":  float(v["high"]),
                    "low":   float(v["low"]),
                    "close": float(v["close"]),
                    "volume": 0.0,
                })
            except Exception:
                continue

        # Twelve Data returns newest-first; reverse for chronological order
        rows.reverse()
        df = pd.DataFrame(rows).tail(limit).reset_index(drop=True)
        df = df.set_index("datetime")
        df.index.name = None
        log.info(
            f"[TwelveData] {symbol} | {timeframe} | "
            f"{len(df)} candles | last close: {df['close'].iloc[-1]:.5f}"
        )
        return df

    @staticmethod
    def _tf_to_twelve_data(timeframe: str):
        """Map internal timeframe to Twelve Data interval."""
        tf = timeframe.upper()
        return {
            "M5":  "5min",  "5M":  "5min",
            "M15": "15min", "15M": "15min",
            "M30": "30min", "30M": "30min",
            "H1":  "1h",    "1H":  "1h",
            "H4":  "4h",    "4H":  "4h",
            "D1":  "1day",  "1D":  "1day",
        }.get(tf)

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