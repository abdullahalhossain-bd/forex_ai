# analysis/_engine_utils.py
# ============================================================
# Shared Helpers for All Signal Engines
# ============================================================
# Eliminates 5-way code duplication of:
#   - _atr(df, period)       → atr_series / atr_value
#   - _pip_value(symbol)     → pip_value
#   - _is_round_number(...)  → is_round_number (full multi-asset version)
#   - _no_trade_signal(...)  → no_trade_signal (schema-aware)
#
# All engines should import from here instead of defining their own.
# ============================================================

import numpy as np
import pandas as pd
from typing import Optional


# ─── ATR ──────────────────────────────────────────────────────

def atr_series(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR as a pandas Series (for rolling computations)."""
    try:
        h, l, c = df["high"], df["low"], df["close"]
        tr = pd.concat(
            [(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1
        ).max(axis=1)
        return tr.rolling(period, min_periods=1).mean()
    except Exception:
        return pd.Series([np.nan] * len(df), index=df.index)


def atr_value(df: pd.DataFrame, period: int = 14) -> float:
    """Current ATR value as float (with fallback)."""
    try:
        atr = atr_series(df, period).iloc[-1]
        if np.isfinite(atr) and atr > 0:
            return float(atr)
        return float(df["close"].iloc[-1]) * 0.001
    except Exception:
        try:
            return float(df["close"].iloc[-1]) * 0.001
        except Exception:
            return 0.001


# ─── Pip Value ────────────────────────────────────────────────

def pip_value(symbol: str) -> float:
    """Pip value per instrument type."""
    sym = (symbol or "").upper()
    if sym.endswith("JPY"):
        return 0.01
    if sym == "XAUUSD":
        return 0.1
    if sym in ("US30", "NAS100", "SPX500", "GER40"):
        return 1.0
    return 0.0001


# ─── Round Number Detection ───────────────────────────────────

def is_round_number(price: float, symbol: str) -> bool:
    """Check if price is near a 'round' psychological level.

    FX majors: multiples of 50 pips (0.0050) or 100 pips (0.0100)
    JPY pairs : multiples of 50 pips (0.50) or 100 pips (1.00)
    XAUUSD    : multiples of $5 or $10
    Indices   : multiples of 50 or 100 points

    Uses tolerance-based check (NOT modulo) to avoid floating-point issues.
    """
    try:
        sym = (symbol or "").upper()
        if sym.endswith("JPY"):
            for step in (0.50, 1.00):
                nearest = round(price / step) * step
                if abs(price - nearest) < step * 0.05:
                    return True
            return False
        if sym == "XAUUSD":
            for step in (5.0, 10.0):
                nearest = round(price / step) * step
                if abs(price - nearest) < step * 0.05:
                    return True
            return False
        if sym in ("US30", "NAS100", "SPX500", "GER40"):
            for step in (50.0, 100.0):
                nearest = round(price / step) * step
                if abs(price - nearest) < step * 0.05:
                    return True
            return False
        # FX major: 50-pip = 0.0050, 100-pip = 0.0100
        for step in (0.0050, 0.0100):
            nearest = round(price / step) * step
            if abs(price - nearest) < step * 0.05:
                return True
        return False
    except Exception:
        return False


# ─── No-Trade Signal Builders ─────────────────────────────────

def no_trade_signal(reason: str, schema: str = "default") -> dict:
    """
    Build a NO_TRADE signal dict.

    schema="default"  → entry_price, stop_loss, take_profit
    schema="pa"       → entry_price, stop_loss, take_profit_suggested, risk_reward
    schema="ict"      → entry_price, stop_loss, take_profit, risk_reward
    """
    if schema == "pa":
        return {
            "action":                "NO_TRADE",
            "entry_price":           None,
            "stop_loss":             None,
            "take_profit_suggested": None,
            "risk_reward":           None,
            "reason":                reason,
            "confidence":            "Low",
        }
    if schema == "ict":
        return {
            "action":      "NO_TRADE",
            "entry_price": None,
            "stop_loss":   None,
            "take_profit": None,
            "risk_reward": None,
            "reason":      reason,
            "confidence":  "Low",
        }
    # default
    return {
        "action":      "NO_TRADE",
        "entry_price": None,
        "stop_loss":   None,
        "take_profit": None,
        "reason":      reason,
        "confidence":  "Low",
    }


def wait_signal(reason: str) -> dict:
    """Build a WAIT signal dict (for sideways/consolidation)."""
    return {
        "action":                "WAIT",
        "entry_price":           None,
        "stop_loss":             None,
        "take_profit_suggested": None,
        "risk_reward":           None,
        "reason":                reason,
        "confidence":            "Low",
    }
