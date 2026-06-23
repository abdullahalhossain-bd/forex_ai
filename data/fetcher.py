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
# Updated: metals use futures symbols (GC=F, SI=F) as primary, =X as fallback
SYMBOL_MAP = {
    # Forex majors
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "AUDUSD": "AUDUSD=X",
    "USDCHF": "USDCHF=X",
    "USDCAD": "USDCAD=X",
    "NZDUSD": "NZDUSD=X",
    # Forex crosses — all need =X
    "EURGBP": "EURGBP=X",
    "EURJPY": "EURJPY=X",
    "EURCHF": "EURCHF=X",
    "EURAUD": "EURAUD=X",
    "EURCAD": "EURCAD=X",
    "EURNZD": "EURNZD=X",
    "GBPJPY": "GBPJPY=X",
    "GBPCHF": "GBPCHF=X",
    "GBPAUD": "GBPAUD=X",
    "GBPCAD": "GBPCAD=X",
    "GBPNZD": "GBPNZD=X",
    "AUDJPY": "AUDJPY=X",
    "AUDCHF": "AUDCHF=X",
    "AUDCAD": "AUDCAD=X",
    "AUDNZD": "AUDNZD=X",
    "NZDJPY": "NZDJPY=X",
    "NZDCHF": "NZDCHF=X",
    "NZDCAD": "NZDCAD=X",
    "CADJPY": "CADJPY=X",
    "CADCHF": "CADCHF=X",
    "CHFJPY": "CHFJPY=X",
    # Metals — use futures symbols (more reliable on yfinance)
    "XAUUSD": "GC=F",      # Gold futures (primary)
    "XAGUSD": "SI=F",      # Silver futures (primary)
    # Legacy compat
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

# Fallback symbols — if primary fails, try these alternatives
SYMBOL_FALLBACKS = {
    "XAUUSD": ["GC=F", "XAUUSD=X", "GLD"],       # Gold: futures → forex → ETF
    "XAGUSD": ["SI=F", "XAGUSD=X", "SLV"],        # Silver: futures → forex → ETF
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

        # Symbol convert — use SYMBOL_MAP, or auto-append =X for forex
        yf_symbol = SYMBOL_MAP.get(symbol, symbol)
        # Auto-append =X for 6-letter forex pairs that don't already have it
        if not yf_symbol.endswith("=X") and "=" not in yf_symbol and len(yf_symbol) == 6 and yf_symbol.isalpha():
            yf_symbol = yf_symbol + "=X"
            log.debug(f"Auto-appended =X: {symbol} → {yf_symbol}")

        yf_tf = TF_MAP.get(timeframe, timeframe)
        periods_to_try = self._get_period_fallbacks(timeframe, limit)

        # Build list of symbols to try: primary + fallbacks
        symbols_to_try = [yf_symbol]
        if symbol in SYMBOL_FALLBACKS:
            for fb in SYMBOL_FALLBACKS[symbol]:
                if fb not in symbols_to_try:
                    symbols_to_try.append(fb)
        if symbol not in SYMBOL_FALLBACKS and not yf_symbol.endswith("=X"):
            symbols_to_try.append(symbol + "=X")

        # Try each symbol × each period until one works
        for try_symbol in symbols_to_try:
            for try_period in periods_to_try:
                try:
                    ticker = yf.Ticker(try_symbol)
                    raw = ticker.history(period=try_period, interval=yf_tf)

                    if raw.empty:
                        log.debug(f"yfinance returned empty for {try_symbol} period={try_period}, trying next...")
                        continue

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

                    log.info(f"[OK] Got {len(df)} candles for {symbol} via {try_symbol} period={try_period} | Latest: {df.index[-1]}")
                    return df

                except Exception as e:
                    log.debug(f"yfinance error for {try_symbol} period={try_period}: {e}")
                    continue

        # All symbols failed
        log.error(f"yfinance failed for {symbol} — tried {symbols_to_try}")
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

    def _get_period_fallbacks(self, timeframe, limit):
        """Return a list of periods to try if the primary period fails.
        yfinance sometimes fails on 30d for 1h but works on 60d or 90d."""
        primary = self._limit_to_period(timeframe, limit)
        fallbacks = [primary]
        # Add longer periods as fallback
        for p in ["60d", "90d", "6mo", "1y"]:
            if p not in fallbacks:
                fallbacks.append(p)
        return fallbacks

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