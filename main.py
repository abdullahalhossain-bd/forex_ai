import os

from config import (
    BACKUP_INTERVAL_MIN,
    DEFAULT_TIMEFRAME,
    LOOP_INTERVAL_SEC,
    PAPER_BALANCE,
    RECOVERY_COOLDOWN_MIN,
    SYMBOLS,
)
from core.trader import AutonomousTraderSystem


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


if __name__ == "__main__":
    system = AutonomousTraderSystem(
        symbols=SYMBOLS,
        timeframe=DEFAULT_TIMEFRAME,
        balance=float(os.getenv("PAPER_BALANCE", PAPER_BALANCE)),
        poll_seconds=_env_int("LOOP_INTERVAL_SEC", LOOP_INTERVAL_SEC),
        backup_interval_minutes=_env_int("BACKUP_INTERVAL_MIN", BACKUP_INTERVAL_MIN),
        cooldown_minutes=_env_int("RECOVERY_COOLDOWN_MIN", RECOVERY_COOLDOWN_MIN),
        max_cycles=None,
        enable_telegram=os.getenv("ENABLE_TELEGRAM", "true").lower() != "false",
    )
    report = system.run()
    print("\nAI TRADER REPORT")
    print(f"Trades: {report['summary']['trades']}")
    print(f"Wins: {report['summary']['wins']} | Losses: {report['summary']['losses']}")
    print(f"Win Rate: {report['summary']['win_rate']}%")
    print(f"Profit: ${report['summary']['profit']}")
