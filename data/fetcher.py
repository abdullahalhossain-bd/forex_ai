# data/fetcher.py
import ccxt
import pandas as pd
from datetime import datetime
from config import SYMBOLS, DEFAULT_TIMEFRAME

class DataFetcher:
    def __init__(self):
        # Binance free API — no key needed for public data
        self.exchange = ccxt.binance({
            'enableRateLimit': True,
        })
        print("✅ DataFetcher initialized")

    def fetch_ohlcv(self, symbol="EUR/USDT", timeframe=DEFAULT_TIMEFRAME, limit=500):
        """
        OHLCV = Open, High, Low, Close, Volume
        limit=500 মানে শেষ ৫০০টা candle
        """
        try:
            print(f"📡 Fetching {symbol} | {timeframe} | {limit} candles...")
            raw = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            
            df = pd.DataFrame(raw, columns=[
                'timestamp', 'open', 'high', 'low', 'close', 'volume'
            ])
            
            # Timestamp কে readable date-এ convert
            df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('datetime', inplace=True)
            df.drop('timestamp', axis=1, inplace=True)
            
            print(f"✅ Got {len(df)} candles | Latest: {df.index[-1]}")
            return df

        except Exception as e:
            print(f"❌ Fetch error: {e}")
            return None

    def save_to_csv(self, df, symbol, timeframe):
        """Data CSV-তে save করো — পরে কাজে লাগবে"""
        filename = f"data/{symbol.replace('/', '_')}_{timeframe}.csv"
        df.to_csv(filename)
        print(f"💾 Saved to {filename}")

    def load_from_csv(self, symbol, timeframe):
        """Save করা data load করো"""
        filename = f"data/{symbol.replace('/', '_')}_{timeframe}.csv"
        try:
            df = pd.read_csv(filename, index_col='datetime', parse_dates=True)
            print(f"📂 Loaded {len(df)} rows from {filename}")
            return df
        except FileNotFoundError:
            print(f"❌ File not found: {filename}")
            return None