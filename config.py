# config.py — Autonomous Forex AI Trader Configuration | Day 31 Part 5
# ============================================================================
# Sensitive broker credentials কখনো হার্ডকোড বা git-এ commit করা যাবে না। 
# সব .env ফাইল থেকে আসবে। এই মডিউলে গ্লোবাল কনফিগ ও এমটি৫ গেটওয়ে মার্জ করা হয়েছে।
# ============================================================================

import os
from dotenv import load_dotenv

# Load environmental variables from .env file
load_dotenv()

# ── General Project Settings ─────────────────────────────────
PROJECT_NAME = "Autonomous Forex AI Trader"

# ── Capital & Risk Management ────────────────────────────────
INITIAL_BALANCE = 1000
RISK_PER_TRADE = 0.01
MAX_DAILY_LOSS = 0.03
MAX_OPEN_TRADES = 3

# ── Market & Data Settings ───────────────────────────────────
MARKET = "forex"
DATA_SOURCE = "yfinance"
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY"]

# ── Timeframes ───────────────────────────────────────────────
DEFAULT_TIMEFRAME = "15m"
MTF_CHAIN = ["1d", "4h", "1h", "15m"]

# ── Technical Indicator Settings ─────────────────────────────
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
MA_FAST = 20
MA_SLOW = 50
MA_TREND = 200
ATR_PERIOD = 14

# ── Support / Resistance Settings ────────────────────────────
SR_WINDOW = 5
SR_TOLERANCE = 0.0015

# ── File Paths ───────────────────────────────────────────────
LOG_FILE = "logs/trader.log"
DB_PATH = "database/trader.db"
CHART_OUTPUT = "data/chart.html"

# ── System / Operational Loops ────────────────────────────────
PAPER_BALANCE = 10000
LOOP_INTERVAL_SEC = 60
BACKUP_INTERVAL_MIN = 30
RECOVERY_COOLDOWN_MIN = 5

# ── Execution Mode ───────────────────────────────────────────
# "paper"    → Local PaperTrader simulation
# "mt5_demo" → Real MT5 demo account execution
EXECUTION_MODE = os.getenv("EXECUTION_MODE", "paper").lower()

# ── MT5 Broker Credentials (Day 31 Cleaned) ──────────────────
MT5_LOGIN_ENV = os.getenv("MT5_LOGIN", "0")
MT5_LOGIN = int(MT5_LOGIN_ENV) if MT5_LOGIN_ENV and MT5_LOGIN_ENV.isdigit() and MT5_LOGIN_ENV != "0" else None

MT5_PASSWORD = os.getenv("MT5_PASSWORD")
MT5_SERVER   = os.getenv("MT5_SERVER")
MT5_PATH     = os.getenv("MT5_PATH")  # Optional: MT5 terminal.exe path override


# ── Configuration Validation ─────────────────────────────────
def validate_mt5_config() -> None:
    """MT5 mode চালু করার আগে প্রয়োজনীয় credentials আছে কিনা চেক করে।"""
    if EXECUTION_MODE == "mt5_demo":
        missing = []
        if not MT5_LOGIN:
            missing.append("MT5_LOGIN")
        if not MT5_PASSWORD:
            missing.append("MT5_PASSWORD")
        if not MT5_SERVER:
            missing.append("MT5_SERVER")

        if missing:
            raise ValueError(
                f".env ফাইলে এই credentials গুলো missing: {', '.join(missing)}. "
                f"অনুগ্রহ করে MT5_LOGIN, MT5_PASSWORD, এবং MT5_SERVER সঠিকভাবে সেট করুন।"
            )

# মেইন স্ক্রিপ্ট বা পাইপলাইনে রান করার আগে অটোমেটিক ভ্যালিডেশন চেক
if EXECUTION_MODE == "mt5_demo":
    validate_mt5_config()
    # Add these to the existing Config class
class Config:
    # ... existing configuration ...
    
    # Forex data configuration
    FOREX_PAIRS = [
        'EUR/USD', 'GBP/USD', 'USD/JPY', 'USD/CHF',
        'AUD/USD', 'USD/CAD', 'NZD/USD',
        'EUR/GBP', 'EUR/JPY', 'GBP/JPY'
    ]
    
    # Data update configuration
    DATA_UPDATE_TIME = "06:00"  # Daily update at 6 AM
    DATA_UPDATE_TIMEZONE = "UTC"
    DATA_HISTORY_DAYS = 365 * 5  # 5 years of history
    DATA_UPDATE_RETRY_ATTEMPTS = 3
    DATA_UPDATE_RETRY_DELAY = 300  # 5 minutes
    
    # API credentials (should be in environment variables)
    OANDA_API_KEY = os.environ.get('OANDA_API_KEY')
    OANDA_ACCOUNT_ID = os.environ.get('OANDA_ACCOUNT_ID')
    
    # Database configuration
    DB_HOST = os.environ.get('DB_HOST', 'localhost')
    DB_PORT = os.environ.get('DB_PORT', '5432')
    DB_NAME = os.environ.get('DB_NAME', 'forex_ai')
    DB_USER = os.environ.get('DB_USER', 'postgres')
    DB_PASSWORD = os.environ.get('DB_PASSWORD', '')
    
    # Logging configuration
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
    LOG_FILE = 'logs/forex_ai.log'
    LOG_MAX_SIZE = 10 * 1024 * 1024  # 10 MB
    LOG_BACKUP_COUNT = 5