# config.py — Autonomous Forex AI Trader Configuration
# ============================================================
# Single source of truth for all configuration. Sensitive credentials
# come from .env — never hardcode or commit secrets.
# ============================================================

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# ── Project Paths ──────────────────────────────────────────────
PROJECT_ROOT: Path = Path(__file__).resolve().parent
LOG_DIR: Path = PROJECT_ROOT / "logs"
DATA_DIR: Path = PROJECT_ROOT / "data"
DB_PATH: Path = PROJECT_ROOT / "database" / "trader.db"
MODEL_DIR: Path = PROJECT_ROOT / "models"
CHART_OUTPUT: Path = DATA_DIR / "chart.html"

# Ensure directories exist
for _d in (LOG_DIR, DATA_DIR, MODEL_DIR, DB_PATH.parent):
    _d.mkdir(parents=True, exist_ok=True)

# ── General Project Settings ───────────────────────────────────
PROJECT_NAME = "Autonomous Forex AI Trader"

# ── Capital & Risk Management ──────────────────────────────────
# Day 37+ professional tuning — calibrated for 28-pair universe.
INITIAL_BALANCE = 10000
INITIAL_CAPITAL = INITIAL_BALANCE  # Alias for compatibility
RISK_PER_TRADE = 0.01              # 1% per trade (professional standard)
MAX_DAILY_LOSS = 0.03              # 3% daily loss limit
MAX_OPEN_TRADES = 5                # 5 concurrent positions (was 3) — better for 28 pairs
MAX_POSITIONS = 7                  # 7 portfolio-wide (was 5) — slight headroom
MAX_RISK_PER_PAIR = 0.02           # NEW: max 2% risk on a single pair

# ── Market & Data Settings ─────────────────────────────────────
MARKET = "forex"
DATA_SOURCE = "yfinance"

# Complete pair universe: 7 majors + 21 minors/crosses + 2 metals = 30 pairs.
# Per user request — agent trades the FULL forex universe + precious metals.
# Each pair gets its own AITrader instance in AutonomousTraderSystem.
# (MAX_OPEN_TRADES = 5 still applies, so only 5 concurrent positions max.)
SYMBOLS = [
    # ── MAJORS (7) — USD on one side ──
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF",
    "USDCAD", "AUDUSD", "NZDUSD",
    # ── MINORS / CROSSES (21) ──
    # EUR crosses (6)
    "EURGBP", "EURJPY", "EURCHF", "EURAUD",
    "EURCAD", "EURNZD",
    # GBP crosses (5)
    "GBPJPY", "GBPCHF", "GBPAUD", "GBPCAD", "GBPNZD",
    # AUD crosses (4)
    "AUDJPY", "AUDCHF", "AUDCAD", "AUDNZD",
    # NZD crosses (3)
    "NZDJPY", "NZDCHF", "NZDCAD",
    # CAD/CHF crosses (3)
    "CADJPY", "CADCHF", "CHFJPY",
    # ── METALS / COMMODITIES (2) ──
    "XAUUSD",  # Gold
    "XAGUSD",  # Silver
]

# ── Timeframes ─────────────────────────────────────────────────
DEFAULT_TIMEFRAME = "15m"
MTF_CHAIN = ["1d", "4h", "1h", "15m"]

# ── Technical Indicator Settings ───────────────────────────────
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
MA_FAST = 20
MA_SLOW = 50
MA_TREND = 200
ATR_PERIOD = 14

# ── Support / Resistance Settings ──────────────────────────────
SR_WINDOW = 5
SR_TOLERANCE = 0.0015

# ── File Paths (legacy compatibility) ─────────────────────────
LOG_FILE = str(LOG_DIR / "trader.log")

# ── System / Operational Loops ─────────────────────────────────
LOOP_INTERVAL_SEC = 90             # 90s (was 60) — 28 pairs need more analysis time
BACKUP_INTERVAL_MIN = 30
RECOVERY_COOLDOWN_MIN = 5

# ── Monitoring ─────────────────────────────────────────────────
MONITORING_INTERVAL = 60  # seconds between health checks

# ── AI / LLM Settings ─────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
# Anthropic + OpenRouter intentionally disabled — MasterAnalyst now uses
# the same Groq/Gemini chain as AIAnalyst (per user request, free-tier only).
# ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
HF_TOKEN = os.getenv("HF_TOKEN", "")

# ── Execution Mode ─────────────────────────────────────────────
# "paper"    -> Local PaperTrader simulation (default, safe)
# "mt5_demo" -> Real MT5 demo account execution
EXECUTION_MODE = os.getenv("EXECUTION_MODE", "paper").lower()

# ── TEST MODE ─────────────────────────────────────────────────
# When true (default for first-time MT5 demo verification): all safety
# gates become permissive so the system actually places trades.
#  - TradePermission MIN_CONFIDENCE = 10 (instead of 60)
#  - Session quality check becomes warning (instead of block)
#  - ConfidenceEngine auto-skip disabled
#  - ConfidenceEngine WAIT threshold = 10 (instead of 25)
# Switch to false once you've confirmed MT5 orders are filling correctly
# and you want the full safety pipeline re-engaged.
TEST_MODE = os.getenv("TEST_MODE", "true").lower() == "true"

# ── TRADING MODE (Day 81+) ────────────────────────────────────
# SAFE        — high-confidence-only, all confirmations required, small lots
# AUTONOMOUS  — system trades per ApprovalMode (default mode 3 = no human gate)
# ABSOLUTE_SAFETY is an independent kill-switch flag — when true, the
# following hard gates ALWAYS block execution regardless of TRADING_MODE:
#   - broker disconnect
#   - spread > 5x normal
#   - extreme volatility (ATR > 3x median)
#   - news window (±30 min around high-impact events)
#   - margin level < 200%
TRADING_MODE = os.getenv("TRADING_MODE", "AUTONOMOUS").upper()
ABSOLUTE_SAFETY = os.getenv("ABSOLUTE_SAFETY", "true").lower() == "true"

# Confidence thresholds per TRADING_MODE (used by TradePermission)
TRADING_MODE_CONFIDENCE = {
    "SAFE":       80,   # only high-conviction trades
    "AUTONOMOUS": 60,   # balanced — production default
    "TEST":       10,   # permissive — only when TEST_MODE=true
}

# ── Use Scanner ────────────────────────────────────────────────
USE_SCANNER = os.getenv("USE_SCANNER", "false").lower() == "true"

# ── Approval Mode ──────────────────────────────────────────────
# 1 = analysis only (AI watches, never trades)
# 2 = supervised (AI suggests, human must approve each trade)
# 3 = autonomous (default — no human gate)
APPROVAL_MODE = int(os.getenv("APPROVAL_MODE", "3"))

# ── MT5 Broker Credentials ─────────────────────────────────────
MT5_LOGIN_ENV = os.getenv("MT5_LOGIN", "0")
MT5_LOGIN = int(MT5_LOGIN_ENV) if MT5_LOGIN_ENV and MT5_LOGIN_ENV.isdigit() and MT5_LOGIN_ENV != "0" else None
MT5_PASSWORD = os.getenv("MT5_PASSWORD")
MT5_SERVER = os.getenv("MT5_SERVER")
MT5_PATH = os.getenv("MT5_PATH")  # Optional: MT5 terminal.exe path override
MT5_INVESTOR = os.getenv("MT5_INVESTOR")

# ── Telegram ───────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
ENABLE_TELEGRAM = os.getenv("ENABLE_TELEGRAM", "false").lower() == "true"

# ── External API Keys ─────────────────────────────────────────
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")
FRED_API_KEY = os.getenv("FRED_API_KEY", "")

# ── Retraining Settings ───────────────────────────────────────
RETRAINING_INTERVAL = int(os.getenv("RETRAINING_INTERVAL", "24"))  # hours
PERFORMANCE_THRESHOLD = float(os.getenv("PERFORMANCE_THRESHOLD", "0.55"))
MIN_TRAINING_SAMPLES = int(os.getenv("MIN_TRAINING_SAMPLES", "100"))

# ── SMTP / Email Alerts ────────────────────────────────────────
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
ALERT_RECIPIENTS = os.getenv("ALERT_RECIPIENTS", "")
ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "")

# ── Webhook ────────────────────────────────────────────────────
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
WEBHOOK_PORT = int(os.getenv("WEBHOOK_PORT", "5000"))

# ── Logging ────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_MAX_SIZE = 10 * 1024 * 1024  # 10 MB
LOG_BACKUP_COUNT = 5


# ── Configuration Validation ───────────────────────────────────
def validate_mt5_config() -> None:
    """Validate MT5 credentials before starting mt5_demo mode."""
    if EXECUTION_MODE == "mt5_demo":
        missing = []
        if not MT5_LOGIN:
            missing.append("MT5_LOGIN")
        if not MT5_PASSWORD:
            missing.append("MT5_PASSWORD")
        if not MT5_SERVER:
            missing.append("MT5_SERVER")
        if missing:
            from core.exceptions import ConfigurationError
            raise ConfigurationError(
                f"MT5 credentials missing in .env: {', '.join(missing)}. "
                f"Set MT5_LOGIN, MT5_PASSWORD, and MT5_SERVER."
            )


def validate_telegram_config() -> None:
    """Validate Telegram credentials before enabling notifications."""
    if ENABLE_TELEGRAM:
        missing = []
        if not TELEGRAM_TOKEN:
            missing.append("TELEGRAM_TOKEN")
        if not TELEGRAM_CHAT_ID:
            missing.append("TELEGRAM_CHAT_ID")
        if missing:
            import logging
            logging.getLogger(__name__).warning(
                f"Telegram enabled but credentials missing: {', '.join(missing)}. "
                f"Notifications will be disabled."
            )


class Config:
    """Unified configuration class — merges all settings for modules
    that prefer class-based access over module-level constants."""

    # Project
    PROJECT_NAME = PROJECT_NAME
    PROJECT_ROOT = PROJECT_ROOT

    # Paths
    DATA_DIR = DATA_DIR
    LOG_DIR = LOG_DIR
    MODEL_DIR = MODEL_DIR
    DB_PATH = DB_PATH
    CHART_OUTPUT = CHART_OUTPUT
    LOG_FILE = LOG_FILE

    # Capital & Risk
    INITIAL_BALANCE = INITIAL_BALANCE
    INITIAL_CAPITAL = INITIAL_CAPITAL
    RISK_PER_TRADE = RISK_PER_TRADE
    MAX_DAILY_LOSS = MAX_DAILY_LOSS
    MAX_OPEN_TRADES = MAX_OPEN_TRADES
    MAX_POSITIONS = MAX_POSITIONS

    # Market
    MARKET = MARKET
    DATA_SOURCE = DATA_SOURCE
    SYMBOLS = SYMBOLS

    # Timeframes
    DEFAULT_TIMEFRAME = DEFAULT_TIMEFRAME
    MTF_CHAIN = MTF_CHAIN

    # Indicators
    RSI_PERIOD = RSI_PERIOD
    RSI_OVERBOUGHT = RSI_OVERBOUGHT
    RSI_OVERSOLD = RSI_OVERSOLD
    MA_FAST = MA_FAST
    MA_SLOW = MA_SLOW
    MA_TREND = MA_TREND
    ATR_PERIOD = ATR_PERIOD

    # S/R
    SR_WINDOW = SR_WINDOW
    SR_TOLERANCE = SR_TOLERANCE

    # System

    LOOP_INTERVAL_SEC = LOOP_INTERVAL_SEC
    BACKUP_INTERVAL_MIN = BACKUP_INTERVAL_MIN
    RECOVERY_COOLDOWN_MIN = RECOVERY_COOLDOWN_MIN
    MONITORING_INTERVAL = MONITORING_INTERVAL

    # Execution
    EXECUTION_MODE = EXECUTION_MODE
    USE_SCANNER = USE_SCANNER
    APPROVAL_MODE = APPROVAL_MODE
    TEST_MODE = TEST_MODE
    TRADING_MODE = TRADING_MODE
    ABSOLUTE_SAFETY = ABSOLUTE_SAFETY
    TRADING_MODE_CONFIDENCE = TRADING_MODE_CONFIDENCE

    # MT5
    MT5_LOGIN = MT5_LOGIN
    MT5_PASSWORD = MT5_PASSWORD
    MT5_SERVER = MT5_SERVER
    MT5_PATH = MT5_PATH

    # Telegram
    TELEGRAM_TOKEN = TELEGRAM_TOKEN
    TELEGRAM_CHAT_ID = TELEGRAM_CHAT_ID
    ENABLE_TELEGRAM = ENABLE_TELEGRAM

    # LLM
    GROQ_API_KEY = GROQ_API_KEY
    GROQ_MODEL = GROQ_MODEL
    GEMINI_API_KEY = GEMINI_API_KEY
    GEMINI_MODEL = GEMINI_MODEL
    # Anthropic + OpenRouter disabled (per user request — free-tier only)
    # ANTHROPIC_API_KEY = ANTHROPIC_API_KEY
    # OPENROUTER_API_KEY = OPENROUTER_API_KEY

    # External APIs
    ALPHA_VANTAGE_API_KEY = ALPHA_VANTAGE_API_KEY
    FINNHUB_API_KEY = FINNHUB_API_KEY
    TWELVE_DATA_API_KEY = TWELVE_DATA_API_KEY
    FRED_API_KEY = FRED_API_KEY

    # Retraining
    RETRAINING_INTERVAL = RETRAINING_INTERVAL
    PERFORMANCE_THRESHOLD = PERFORMANCE_THRESHOLD
    MIN_TRAINING_SAMPLES = MIN_TRAINING_SAMPLES

    # Logging
    LOG_LEVEL = LOG_LEVEL
    LOG_MAX_SIZE = LOG_MAX_SIZE
    LOG_BACKUP_COUNT = LOG_BACKUP_COUNT

    # Forex pairs for scanner/data updater — full 28-pair universe
    FOREX_PAIRS = SYMBOLS  # Reuse the SYMBOLS list (28 pairs)

    # Data update configuration
    DATA_UPDATE_TIME = "06:00"
    DATA_UPDATE_TIMEZONE = "UTC"
    DATA_HISTORY_DAYS = 365 * 5
    DATA_UPDATE_RETRY_ATTEMPTS = 3
    DATA_UPDATE_RETRY_DELAY = 300

    # Legacy OANDA keys (optional — not used by default)
    OANDA_API_KEY = os.environ.get('OANDA_API_KEY', '')
    OANDA_ACCOUNT_ID = os.environ.get('OANDA_ACCOUNT_ID', '')

    # Database (legacy — system uses SQLite by default)
    DB_HOST = os.environ.get('DB_HOST', 'localhost')
    DB_PORT = os.environ.get('DB_PORT', '5432')
    DB_NAME = os.environ.get('DB_NAME', 'forex_ai')
    DB_USER = os.environ.get('DB_USER', 'postgres')
    DB_PASSWORD = os.environ.get('DB_PASSWORD', '')

    # SMTP
    SMTP_HOST = SMTP_HOST
    SMTP_PORT = SMTP_PORT
    SMTP_USERNAME = SMTP_USERNAME
    SMTP_PASSWORD = SMTP_PASSWORD
    ALERT_RECIPIENTS = ALERT_RECIPIENTS
    ALERT_WEBHOOK_URL = ALERT_WEBHOOK_URL

    # Webhook
    WEBHOOK_SECRET = WEBHOOK_SECRET
    WEBHOOK_PORT = WEBHOOK_PORT


# Auto-validate on import
validate_mt5_config()
validate_telegram_config()
