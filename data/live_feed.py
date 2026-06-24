"""
data/live_feed.py — MT5 Live Tick Intelligence (Day 81+)
=========================================================

Single source of truth for real-time MT5 market data:
  - Bid/Ask/Spread
  - Tick velocity (ticks per second — proxy for market activity)
  - Tick direction pressure (buyers vs sellers over last N ticks)
  - Spread explosion detection (current spread vs N-period median)
  - Liquidity condition classification (NORMAL / THIN / EXPLOSIVE)

This module NEVER falls back to TradingView or any other data source.
If MT5 is unavailable, every method returns None — callers MUST handle
this as "no data, no trade".

Usage:
    from data.live_feed import LiveFeed

    feed = LiveFeed()
    snapshot = feed.get_snapshot("EURUSD")
    if snapshot is None:
        # MT5 down — abort cycle
        return
    if snapshot.liquidity == "EXPLOSIVE":
        # Spread blew up — wait
        return
    # ... proceed with snapshot.bid / snapshot.ask / snapshot.spread_pips
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, Dict, Optional

from utils.logger import get_logger

log = get_logger("live_feed")

# Guard MT5 import so this module loads on Linux/Mac (for unit tests)
try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False


# ── Tick snapshot ─────────────────────────────────────────────

@dataclass
class TickSnapshot:
    """One moment-in-time view of a symbol's live market state."""
    symbol: str
    bid: float
    ask: float
    spread_pips: float
    last_price: float
    timestamp: str  # ISO 8601 UTC

    # Velocity — ticks per second over the last 60s window
    tick_velocity: float = 0.0
    # Direction pressure — +1.0 = all buyers, -1.0 = all sellers, 0 = balanced
    direction_pressure: float = 0.0
    # Liquidity classification
    liquidity: str = "NORMAL"  # NORMAL / THIN / EXPLOSIVE / CLOSED
    # Spread vs median (multiple, e.g. 2.5x = current spread is 2.5x normal)
    spread_multiple: float = 1.0

    # Internal: raw spread history for median calc (kept out of __repr__)
    _raw_spread_history: tuple = field(default_factory=tuple, repr=False)

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    @property
    def is_tradeable(self) -> bool:
        """Quick check — should we even consider trading this symbol right now?"""
        return self.liquidity in ("NORMAL",) and self.spread_multiple < 5.0

    def to_dict(self) -> Dict:
        return {
            "symbol":              self.symbol,
            "bid":                 self.bid,
            "ask":                 self.ask,
            "spread_pips":         self.spread_pips,
            "last_price":          self.last_price,
            "timestamp":           self.timestamp,
            "tick_velocity":       round(self.tick_velocity, 2),
            "direction_pressure":  round(self.direction_pressure, 2),
            "liquidity":           self.liquidity,
            "spread_multiple":     round(self.spread_multiple, 2),
            "is_tradeable":        self.is_tradeable,
        }


# ── Live feed ─────────────────────────────────────────────────

class LiveFeed:
    """
    Real-time MT5 tick intelligence layer.

    Maintains a per-symbol rolling buffer of the last N ticks so we can
    compute velocity, pressure, and spread-median without re-fetching.
    """

    BUFFER_SIZE = 120  # ~2 minutes of ticks at 1/sec

    def __init__(self, buffer_size: int = None):
        self._buffers: Dict[str, Deque[Dict]] = {}
        self._size = buffer_size or self.BUFFER_SIZE
        self._last_fetch: Dict[str, float] = {}  # symbol → epoch

    # ── Public API ─────────────────────────────────────────────

    def get_snapshot(self, symbol: str) -> Optional[TickSnapshot]:
        """Fetch a fresh tick + compute intelligence metrics. None if MT5 down."""
        if not MT5_AVAILABLE:
            log.debug("[LiveFeed] MetaTrader5 not installed — returning None")
            return None

        tick = mt5.symbol_info_tick(symbol)
        if tick is None or tick.time == 0:
            log.debug(f"[LiveFeed] No tick for {symbol}")
            return None

        info = mt5.symbol_info(symbol)
        digits = info.digits if info else 5
        spread_points = tick.ask - tick.bid
        spread_pips = round(spread_points * (10 ** (digits - 1)), 2) if digits else 0

        # Push to rolling buffer
        now = time.time()
        record = {
            "time":      now,
            "bid":       tick.bid,
            "ask":       tick.ask,
            "last":      tick.last if tick.last else (tick.bid + tick.ask) / 2,
            "spread":    spread_pips,
        }
        buf = self._buffers.setdefault(symbol, deque(maxlen=self._size))
        buf.append(record)
        self._last_fetch[symbol] = now

        # Compute intelligence metrics from the buffer
        velocity = self._compute_velocity(buf, now)
        pressure = self._compute_pressure(buf)
        spread_median = self._compute_spread_median(buf)
        spread_multiple = (spread_pips / spread_median) if spread_median > 0 else 1.0
        liquidity = self._classify_liquidity(spread_pips, spread_multiple, velocity)

        return TickSnapshot(
            symbol=symbol,
            bid=tick.bid,
            ask=tick.ask,
            spread_pips=spread_pips,
            last_price=record["last"],
            timestamp=datetime.fromtimestamp(tick.time, tz=timezone.utc).isoformat(),
            tick_velocity=velocity,
            direction_pressure=pressure,
            liquidity=liquidity,
            spread_multiple=spread_multiple,
        )

    def get_multi_snapshot(self, symbols: list[str]) -> Dict[str, TickSnapshot]:
        """Fetch snapshots for many symbols at once — used by the scanner."""
        out = {}
        for sym in symbols:
            snap = self.get_snapshot(sym)
            if snap is not None:
                out[sym] = snap
        return out

    # ── Intelligence calculators ───────────────────────────────

    @staticmethod
    def _compute_velocity(buf: Deque[Dict], now: float, window_sec: float = 60.0) -> float:
        """Ticks per second over the last `window_sec` seconds."""
        if len(buf) < 2:
            return 0.0
        cutoff = now - window_sec
        recent = [r for r in buf if r["time"] >= cutoff]
        if len(recent) < 2:
            return 0.0
        elapsed = recent[-1]["time"] - recent[0]["time"]
        if elapsed <= 0:
            return 0.0
        return len(recent) / elapsed

    @staticmethod
    def _compute_pressure(buf: Deque[Dict], lookback: int = 20) -> float:
        """Direction pressure over last N ticks. +1 = all buyers, -1 = all sellers."""
        if len(buf) < 2:
            return 0.0
        recent = list(buf)[-lookback:]
        buyers = 0
        sellers = 0
        for i in range(1, len(recent)):
            if recent[i]["last"] > recent[i - 1]["last"]:
                buyers += 1
            elif recent[i]["last"] < recent[i - 1]["last"]:
                sellers += 1
        total = buyers + sellers
        if total == 0:
            return 0.0
        return (buyers - sellers) / total

    @staticmethod
    def _compute_spread_median(buf: Deque[Dict]) -> float:
        """Median spread over the buffer (used to detect spread explosions)."""
        if not buf:
            return 0.0
        spreads = sorted(r["spread"] for r in buf)
        n = len(spreads)
        if n % 2 == 1:
            return spreads[n // 2]
        return (spreads[n // 2 - 1] + spreads[n // 2]) / 2

    @staticmethod
    def _classify_liquidity(spread_pips: float, spread_multiple: float, velocity: float) -> str:
        """Classify current liquidity condition — used as a hard gate.

        NORMAL    — typical spread, normal tick activity
        THIN      — very low velocity (off-hours) → wider slippage risk
        EXPLOSIVE — spread blew up >5x normal (news just hit) → DO NOT TRADE
        CLOSED    — spread is zero (market closed)
        """
        if spread_pips == 0:
            return "CLOSED"
        if spread_multiple >= 5.0:
            return "EXPLOSIVE"
        if velocity < 0.1:  # less than 1 tick per 10 seconds
            return "THIN"
        return "NORMAL"

    # ── Hard safety gates (used by ABSOLUTE_SAFETY) ────────────

    def is_safe_to_trade(self, symbol: str, max_spread_multiple: float = 5.0) -> tuple[bool, str]:
        """Quick gate for ABSOLUTE_SAFETY — returns (safe, reason)."""
        snap = self.get_snapshot(symbol)
        if snap is None:
            return False, "MT5 unavailable or no tick data"
        if snap.liquidity == "CLOSED":
            return False, f"{symbol} market closed"
        if snap.liquidity == "EXPLOSIVE":
            return False, f"{symbol} spread exploded ({snap.spread_multiple:.1f}x normal)"
        if snap.spread_multiple >= max_spread_multiple:
            return False, f"{symbol} spread {snap.spread_multiple:.1f}x exceeds limit"
        return True, "OK"


# ── Singleton accessor ────────────────────────────────────────

_FEED: Optional[LiveFeed] = None


def get_live_feed() -> LiveFeed:
    global _FEED
    if _FEED is None:
        _FEED = LiveFeed()
    return _FEED
