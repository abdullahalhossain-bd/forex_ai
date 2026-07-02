"""
analysis/supply_demand_zones.py — Day 97+ Supply/Demand Zones
================================================================
Candlestick Bible: Supply/Demand zones are stronger than S/R because they
reflect institutional order flow, not just prior swing points.

Three criteria for a quality zone (from the book):
  1. Strength/speed of the move away from the zone (fast = institutional)
  2. Favorable risk/reward when traded
  3. Higher time frame zones (4H/daily) are most significant

Usage:
    from analysis.supply_demand_zones import SupplyDemandZones
    sd = SupplyDemandZones()
    result = sd.detect(df)
    # → {"demand_zones": [...], "supply_zones": [...], "nearest_demand": ..., "nearest_supply": ...}
"""

import numpy as np
import pandas as pd
from typing import Any, Dict, List, Optional
from utils.logger import get_logger

log = get_logger("supply_demand")


class SupplyDemandZones:
    """Detects institutional supply/demand zones.

    Book: "Supply/demand zones are a stronger version of S/R, attributed
    to institutional order flow rather than just prior swing points."

    A demand zone = base of a strong bullish rally (institutions bought heavily).
    A supply zone = base of a strong bearish drop (institutions sold heavily).
    """

    # Config
    MIN_RALLY_CANDLES = 3       # minimum candles in the rally away from zone
    MIN_RALLY_PCT = 0.3         # rally must be at least 0.3% to qualify
    ZONE_TOLERANCE = 0.0005     # how close to zone = "at zone"
    MAX_ZONES = 5               # keep only top N strongest zones

    def detect(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Detect supply and demand zones from OHLCV data.

        Returns:
            {
                "demand_zones": [{"zone_low": float, "zone_high": float,
                                   "strength": int, "rally_pct": float, "age_bars": int}],
                "supply_zones": [...],
                "nearest_demand": {"price": float, "distance_pips": float} | None,
                "nearest_supply": {"price": float, "distance_pips": float} | None,
            }
        """
        if len(df) < 10:
            return self._empty_result()

        # Sanitize
        df = df.copy()
        for c in ("open", "high", "low", "close"):
            df[c] = pd.to_numeric(df[c], errors="coerce")

        close = df["close"].values
        high = df["high"].values
        low = df["low"].values
        n = len(df)
        current_price = float(close[-1])

        demand_zones = []
        supply_zones = []

        # Find demand zones: base of strong bullish rallies
        for i in range(self.MIN_RALLY_CANDLES, n - self.MIN_RALLY_CANDLES):
            rally_start = i
            rally_end = min(i + self.MIN_RALLY_CANDLES, n - 1)

            rally_pct = (close[rally_end] - close[rally_start]) / close[rally_start] * 100
            if rally_pct < self.MIN_RALLY_PCT:
                continue

            # The demand zone is the base candle(s) before the rally
            base_low = float(min(low[rally_start-1], low[rally_start]))
            base_high = float(max(high[rally_start-1], high[rally_start]))

            # Strength = rally speed (faster = stronger institutional)
            strength = min(100, int(rally_pct * 20))

            demand_zones.append({
                "zone_low": round(base_low, 5),
                "zone_high": round(base_high, 5),
                "zone_mid": round((base_low + base_high) / 2, 5),
                "strength": strength,
                "rally_pct": round(rally_pct, 2),
                "age_bars": n - rally_start,
            })

        # Find supply zones: base of strong bearish drops
        for i in range(self.MIN_RALLY_CANDLES, n - self.MIN_RALLY_CANDLES):
            drop_start = i
            drop_end = min(i + self.MIN_RALLY_CANDLES, n - 1)

            drop_pct = (close[drop_start] - close[drop_end]) / close[drop_start] * 100
            if drop_pct < self.MIN_RALLY_PCT:
                continue

            base_low = float(min(low[drop_start-1], low[drop_start]))
            base_high = float(max(high[drop_start-1], high[drop_start]))

            strength = min(100, int(drop_pct * 20))

            supply_zones.append({
                "zone_low": round(base_low, 5),
                "zone_high": round(base_high, 5),
                "zone_mid": round((base_low + base_high) / 2, 5),
                "strength": strength,
                "drop_pct": round(drop_pct, 2),
                "age_bars": n - drop_start,
            })

        # Deduplicate and keep strongest
        demand_zones = self._deduplicate(demand_zones)[:self.MAX_ZONES]
        supply_zones = self._deduplicate(supply_zones)[:self.MAX_ZONES]

        # Find nearest zones to current price
        nearest_demand = self._nearest(current_price, demand_zones, "demand")
        nearest_supply = self._nearest(current_price, supply_zones, "supply")

        result = {
            "demand_zones": demand_zones,
            "supply_zones": supply_zones,
            "nearest_demand": nearest_demand,
            "nearest_supply": nearest_supply,
            "current_price": round(current_price, 5),
        }

        log.info(
            f"[SupplyDemand] {len(demand_zones)} demand zones, "
            f"{len(supply_zones)} supply zones detected"
        )
        return result

    def _deduplicate(self, zones: List[dict]) -> List[dict]:
        """Remove overlapping zones, keep the strongest."""
        if not zones:
            return []
        zones.sort(key=lambda z: z["strength"], reverse=True)
        deduped = []
        for z in zones:
            overlap = False
            for d in deduped:
                if abs(z["zone_mid"] - d["zone_mid"]) < self.ZONE_TOLERANCE:
                    overlap = True
                    break
            if not overlap:
                deduped.append(z)
        return deduped

    def _nearest(self, price: float, zones: List[dict], zone_type: str) -> Optional[dict]:
        if not zones:
            return None
        nearest = min(zones, key=lambda z: abs(z["zone_mid"] - price))
        distance = abs(price - nearest["zone_mid"])
        pip_size = 0.0001  # default; use get_pip_size for accuracy
        return {
            "price": nearest["zone_mid"],
            "distance_pips": round(distance / pip_size, 1),
            "strength": nearest["strength"],
            "zone_low": nearest["zone_low"],
            "zone_high": nearest["zone_high"],
            "type": zone_type,
        }

    def _empty_result(self) -> Dict[str, Any]:
        return {
            "demand_zones": [],
            "supply_zones": [],
            "nearest_demand": None,
            "nearest_supply": None,
        }


# ── Singleton ─────────────────────────────────────────────────────

_SDZ: Optional[SupplyDemandZones] = None


def get_supply_demand_zones() -> SupplyDemandZones:
    global _SDZ
    if _SDZ is None:
        _SDZ = SupplyDemandZones()
    return _SDZ
