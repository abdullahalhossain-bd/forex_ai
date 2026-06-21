# data/fetcher.py
# ============================================================
# Multi-Source Data Fetcher
# Source 1: yfinance  (Yahoo Finance — free, no API key)
# Source 2: TradingView via tvdatafeed (real forex data)
# Fallback: CSV থেকে load
# ============================================================

import pandas as pd
from utils.logger import get_logger

log = get_logger(__name__)

# Symbol mapping — internal style → yfinance style
SYMBOL_MAP = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "AUDUSD": "AUDUSD=X",
    "USDCHF": "USDCHF=X",
    "USDCAD": "USDCAD=X",
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/JPY": "USDJPY=X",
    "AUD/USD": "AUDUSD=X",
    "USD/CHF": "USDCHF=X",
    "USD/CAD": "USDCAD=X",
    "EUR/USDT": "EURUSD=X",
    "GBP/USDT": "GBPUSD=X",
    "USDJPY=X": "USDJPY=X",
    "EURUSD=X": "EURUSD=X",
    "GBPUSD=X": "GBPUSD=X",
}

# Timeframe mapping — our style → yfinance style
TF_MAP = {
    "1m":  "1m",
    "5m":  "5m",
    "15m": "15m",
    "30m": "30m",
    "1h":  "60m",
    "4h":  "4h",   # yfinance supports 4h (recent data only)
    "1d":  "1d",
}


class DataFetcher:

    def __init__(self):
        self.source = self._detect_source()
        log.info(f"[OK] DataFetcher initialized | source: {self.source}")

    def _detect_source(self):
        """Available library detect করো"""
        try:
            import yfinance
            return "yfinance"
        except ImportError:
            pass
        try:
            from tvdatafeed import TvDatafeed
            return "tvdatafeed"
        except ImportError:
            pass
        return "csv"

    def fetch_ohlcv(self, symbol="EUR/USDT", timeframe="15m", limit=300, periods=None):
        """
        Data fetch করো — source অনুযায়ী method বেছে নেবে।
        `periods` is an alias for `limit` for backward compatibility.
        """
        # backward compat: periods → limit
        if periods is not None:
            limit = periods

        symbol = self._normalize_symbol(symbol)
        log.info(f"Fetching {symbol} | {timeframe} | {limit} candles...")

        if self.source == "yfinance":
            return self._fetch_yfinance(symbol, timeframe, limit)
        elif self.source == "tvdatafeed":
            return self._fetch_tvdatafeed(symbol, timeframe, limit)
        else:
            log.warning("No data source found! pip install yfinance")
            return None

    # ─────────────────────────────────────────────
    # SOURCE 1: yfinance (Yahoo Finance)
    # ─────────────────────────────────────────────

    def _fetch_yfinance(self, symbol, timeframe, limit):
        import yfinance as yf

        # Symbol convert
        yf_symbol = SYMBOL_MAP.get(symbol, symbol)
        yf_tf     = TF_MAP.get(timeframe, timeframe)

        # Limit → period calculate
        period = self._limit_to_period(timeframe, limit)

        try:
            ticker = yf.Ticker(yf_symbol)
            raw    = ticker.history(period=period, interval=yf_tf)

            if raw.empty:
                log.error(f"yfinance returned empty data for {yf_symbol}")
                return None

            # Column rename → lowercase
            df = raw.rename(columns={
                'Open':   'open',
                'High':   'high',
                'Low':    'low',
                'Close':  'close',
                'Volume': 'volume',
            })[['open', 'high', 'low', 'close', 'volume']]

            # Timezone remove (naive datetime)
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)

            # Limit to requested candles
            df = df.tail(limit)

            log.info(f"[OK] Got {len(df)} candles | Latest: {df.index[-1]}")
            return df

        except Exception as e:
            log.error(f"yfinance error: {e}")
            return None

    def _limit_to_period(self, timeframe, limit):
        """limit candles → yfinance period string"""
        tf_days = {
            '1m': 1/1440, '5m': 5/1440, '15m': 15/1440,
            '30m': 30/1440, '1h': 1/24, '4h': 4/24, '1d': 1,
        }
        days_per_candle = tf_days.get(timeframe, 1)
        total_days = int(limit * days_per_candle * 1.5) + 5  # buffer

        if total_days <= 7:    return "7d"
        if total_days <= 30:   return "30d"
        if total_days <= 60:   return "60d"
        if total_days <= 90:   return "90d"
        return "6mo"

    # ─────────────────────────────────────────────
    # SOURCE 2: tvdatafeed (TradingView)
    # ─────────────────────────────────────────────

    def _fetch_tvdatafeed(self, symbol, timeframe, limit):
        from tvdatafeed import TvDatafeed, Interval

        tf_map = {
            '1m':  Interval.in_1_minute,
            '5m':  Interval.in_5_minute,
            '15m': Interval.in_15_minute,
            '30m': Interval.in_30_minute,
            '1h':  Interval.in_1_hour,
            '4h':  Interval.in_4_hour,
            '1d':  Interval.in_daily,
        }

        # EUR/USDT → EURUSD  (TradingView symbol format)
        tv_symbol = self._normalize_symbol(symbol)

        try:
            tv = TvDatafeed()
            raw = tv.get_hist(
                symbol   = tv_symbol,
                exchange = 'FX',
                interval = tf_map.get(timeframe, Interval.in_15_minute),
                n_bars   = limit,
            )
            if raw is None or raw.empty:
                log.error("tvdatafeed returned empty")
                return None

            df = raw[['open', 'high', 'low', 'close', 'volume']]
            log.info(f"[OK] Got {len(df)} candles via TradingView | Latest: {df.index[-1]}")
            return df

        except Exception as e:
            log.error(f"tvdatafeed error: {e}")
            return None

    # ─────────────────────────────────────────────
    # UTILS
    # ─────────────────────────────────────────────

    def save_to_csv(self, df, symbol, timeframe):
        filename = f"data/{symbol.replace('/', '_')}_{timeframe}.csv"
        df.to_csv(filename)
        log.info(f"[OK] Saved to {filename}")

    def load_from_csv(self, symbol, timeframe):
        filename = f"data/{symbol.replace('/', '_')}_{timeframe}.csv"
        try:
            df = pd.read_csv(filename, index_col=0, parse_dates=True)
            log.info(f"[OK] Loaded {len(df)} rows from {filename}")
            return df
        except FileNotFoundError:
            log.error(f"File not found: {filename}")
            return None

    def _normalize_symbol(self, symbol: str) -> str:
        return (
            str(symbol)
            .upper()
            .replace("=X", "")
            .replace("/", "")
            .replace("USDT", "USD")
            .strip()
        )