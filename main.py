import os

from config import (
    BACKUP_INTERVAL_MIN,
    DEFAULT_TIMEFRAME,
    EXECUTION_MODE,
    LOOP_INTERVAL_SEC,
    PAPER_BALANCE,
    RECOVERY_COOLDOWN_MIN,
    SYMBOLS,
)
from core.trading_engine import TradingEngine


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).lower() == "true"


if __name__ == "__main__":
    system = TradingEngine(
        symbols=SYMBOLS,
        timeframe=DEFAULT_TIMEFRAME,
        balance=float(os.getenv("PAPER_BALANCE", PAPER_BALANCE)),
        poll_seconds=_env_int("LOOP_INTERVAL_SEC", LOOP_INTERVAL_SEC),
        backup_interval_minutes=_env_int("BACKUP_INTERVAL_MIN", BACKUP_INTERVAL_MIN),
        cooldown_minutes=_env_int("RECOVERY_COOLDOWN_MIN", RECOVERY_COOLDOWN_MIN),
        max_cycles=None,
        enable_telegram=os.getenv("ENABLE_TELEGRAM", "true").lower() != "false",
        use_scanner=_env_bool("USE_SCANNER", EXECUTION_MODE == "mt5_demo"),
        execution_mode=EXECUTION_MODE,
        approval_mode=_env_int("APPROVAL_MODE", 3),
    )

    report = system.run()
    print("\nAI TRADER REPORT")
    print(f"Mode: {report['mode']} | Scanner: {report['scanner']}")
    print(f"Trades: {report['summary']['trades']}")
    print(f"Wins: {report['summary']['wins']} | Losses: {report['summary']['losses']}")
    print(f"Win Rate: {report['summary']['win_rate']}%")
    print(f"Profit: ${report['summary']['profit']}")