# core/constants.py — Unified Project Constants
# ============================================================
# Single source of truth for pip sizes, correlation groups,
# and other constants used across multiple modules.
# ALL other modules MUST import from here — no local duplicates.
# ============================================================

from pathlib import Path

# ── Project Root ────────────────────────────────────────────
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

# ── Pip Sizes by Symbol ────────────────────────────────────
PIP_SIZE: dict[str, float] = {
    # USD majors
    "EURUSD": 0.0001, "GBPUSD": 0.0001, "AUDUSD": 0.0001,
    "NZDUSD": 0.0001, "USDCAD": 0.0001, "USDCHF": 0.0001,
    # JPY crosses
    "USDJPY": 0.01,   "GBPJPY": 0.01,   "EURJPY": 0.01,
    "AUDJPY": 0.01,   "NZDJPY": 0.01,   "CADJPY": 0.01,
    "CHFJPY": 0.01,
    # Minor crosses
    "EURGBP": 0.0001, "EURAUD": 0.0001, "EURNZD": 0.0001,
    "EURCAD": 0.0001, "EURCHF": 0.0001,
    "GBPAUD": 0.0001, "GBPNZD": 0.0001, "GBPCAD": 0.0001,
    "GBPCHF": 0.0001,
    "AUDCAD": 0.0001, "AUDCHF": 0.0001, "AUDNZD": 0.0001,
    "NZDCAD": 0.0001, "NZDCHF": 0.0001,
    "CADCHF": 0.0001,
    # Commodities
    "XAUUSD": 0.01,   "XAGUSD": 0.001,
    # Indices
    "US30":   1.0,    "NAS100":  0.01,
    # Default fallback
    "DEFAULT": 0.0001,
}

# Per-standard-lot pip value in USD (approximate)
PIP_VALUE_USD: dict[str, float] = {
    # USD majors (pip = 0.0001, lot = 100k)
    "EURUSD": 10.0, "GBPUSD": 10.0, "AUDUSD": 10.0,
    "NZDUSD": 10.0, "USDCAD": 7.40, "USDCHF": 8.90,
    # JPY crosses (pip = 0.01, lot = 100k, value depends on USDJPY)
    "USDJPY": 6.50, "GBPJPY": 6.50, "EURJPY": 6.50,
    "AUDJPY": 6.50, "NZDJPY": 6.50, "CADJPY": 6.50,
    "CHFJPY": 6.50,
    # Minor crosses
    "EURGBP": 12.70, "EURAUD": 6.50, "EURNZD": 6.10,
    "EURCAD": 7.40, "EURCHF": 8.90,
    "GBPAUD": 6.50, "GBPNZD": 6.10, "GBPCAD": 7.40,
    "GBPCHF": 8.90,
    "AUDCAD": 7.40, "AUDCHF": 8.90, "AUDNZD": 6.10,
    "NZDCAD": 7.40, "NZDCHF": 8.90,
    "CADCHF": 8.90,
    # Commodities
    "XAUUSD": 1.0,  # pip = $0.01, lot = 100 oz → $1/pip
    "XAGUSD": 5.0,
    # Indices
    "US30":   1.0,  "NAS100": 1.0,
    # Default fallback
    "DEFAULT": 10.0,
}


# ── Correlation Groups ──────────────────────────────────────
CORRELATION_GROUPS: list[list[str]] = [
    ["EURUSD", "AUDUSD", "NZDUSD"],         # USD-quoted (EUR side)
    ["GBPUSD"],                              # GBP — আলাদা রাখা হয়েছে
    ["USDJPY", "GBPJPY", "EURJPY", "AUDJPY"],  # JPY crosses
    ["USDCAD", "USDCHF"],                    # Commodity/safe-haven
    ["EURGBP"],                              # European cross
]

# ── Trading Sessions ────────────────────────────────────────
TRADING_SESSIONS = {
    "sydney":   {"open": 22, "close": 7,  "utc_offset": 0},
    "tokyo":    {"open": 0,  "close": 9,  "utc_offset": 0},
    "london":   {"open": 8,  "close": 17, "utc_offset": 0},
    "new_york": {"open": 13, "close": 22, "utc_offset": 0},
}

# ── Data Paths ──────────────────────────────────────────────
LOGS_DIR: Path = PROJECT_ROOT / "logs"
DATABASE_DIR: Path = PROJECT_ROOT / "database"
MEMORY_DIR: Path = PROJECT_ROOT / "memory"
BACKUPS_DIR: Path = PROJECT_ROOT / "backups"
REPORTS_DIR: Path = PROJECT_ROOT / "reports"
DATA_DIR: Path = PROJECT_ROOT / "data"
MODELS_DIR: Path = PROJECT_ROOT / "models"

# ── State File Paths ────────────────────────────────────────
DB_PATH: Path = DATABASE_DIR / "trader.db"
MEMORY_DB_PATH: Path = MEMORY_DIR / "trader.db"
TRADE_MEMORY_PATH: Path = MEMORY_DIR / "trade_memory.json"
DAILY_RISK_PATH: Path = MEMORY_DIR / "daily_risk.json"
ANALYSIS_HISTORY_PATH: Path = MEMORY_DIR / "analysis_history.json"
CIRCUIT_BREAKER_PATH: Path = MEMORY_DIR / "circuit_breaker_state.json"
PENDING_APPROVALS_PATH: Path = MEMORY_DIR / "pending_approvals.json"

# ── Day 58: Autonomous Risk Manager State Paths ───────────
DRAWDOWN_STATE_PATH: Path = MEMORY_DIR / "drawdown_state.json"
CAPITAL_STATE_PATH: Path = MEMORY_DIR / "capital_allocation_state.json"

# ── Magic number for MT5 orders ────────────────────────────
MT5_MAGIC_NUMBER = 424242


def get_pip_size(symbol: str) -> float:
    """Get pip size for a symbol, with safe fallback."""
    clean = symbol.upper().replace("/", "").replace("=X", "").strip()[:6]
    return PIP_SIZE.get(clean, PIP_SIZE["DEFAULT"])


def get_pip_value_usd(symbol: str) -> float:
    """Get per-standard-lot pip value in USD for a symbol."""
    clean = symbol.upper().replace("/", "").replace("=X", "").strip()[:6]
    return PIP_VALUE_USD.get(clean, PIP_VALUE_USD["DEFAULT"])


def clean_symbol(symbol: str) -> str:
    """Normalize a symbol string for internal use."""
    return str(symbol).upper().replace("/", "").replace("=X", "").replace("USDT", "USD").strip()


def pips_to_price(symbol: str, pips: float) -> float:
    """Convert a pip distance to price distance for a given symbol."""
    return pips * get_pip_size(symbol)


def price_to_pips(symbol: str, price_distance: float) -> float:
    """Convert a price distance to pips for a given symbol."""
    pip = get_pip_size(symbol)
    return price_distance / pip if pip else 0.0
