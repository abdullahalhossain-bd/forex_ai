# core/constants.py — Unified Project Constants
# ============================================================
# Single source of truth for pip sizes, correlation groups,
# and other constants used across multiple modules.
# ============================================================

from pathlib import Path

# ── Project Root ────────────────────────────────────────────
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

# ── Pip Sizes by Symbol ────────────────────────────────────
PIP_SIZE: dict[str, float] = {
    "EURUSD": 0.0001,
    "GBPUSD": 0.0001,
    "USDJPY": 0.01,
    "GBPJPY": 0.01,
    "EURJPY": 0.01,
    "AUDJPY": 0.01,
    "AUDUSD": 0.0001,
    "NZDUSD": 0.0001,
    "USDCAD": 0.0001,
    "USDCHF": 0.0001,
    "DEFAULT": 0.0001,
}

# Per-standard-lot pip value in USD (approximate)
PIP_VALUE_USD: dict[str, float] = {
    "EURUSD": 10.0,
    "GBPUSD": 10.0,
    "USDJPY": 6.50,
    "GBPJPY": 6.50,
    "EURJPY": 6.50,
    "AUDJPY": 6.50,
    "AUDUSD": 10.0,
    "NZDUSD": 10.0,
    "USDCAD": 10.0,
    "USDCHF": 10.0,
    "DEFAULT": 10.0,
}

# ── Correlation Groups ──────────────────────────────────────
CORRELATION_GROUPS: list[list[str]] = [
    ["EURUSD", "GBPUSD", "AUDUSD", "NZDUSD"],  # USD Majors
    ["USDJPY", "GBPJPY", "EURJPY", "AUDJPY"],  # JPY crosses
    ["USDCAD", "USDCHF"],                       # Commodity pairs
]

# ── Data Paths ──────────────────────────────────────────────
LOGS_DIR: Path = PROJECT_ROOT / "logs"
DATABASE_DIR: Path = PROJECT_ROOT / "database"
MEMORY_DIR: Path = PROJECT_ROOT / "memory"
BACKUPS_DIR: Path = PROJECT_ROOT / "backups"
REPORTS_DIR: Path = PROJECT_ROOT / "reports"

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
