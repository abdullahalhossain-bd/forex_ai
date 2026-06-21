# risk/exposure_manager.py — Day 58 | Correlation & Portfolio Exposure Manager
# ============================================================
# Monitors and controls portfolio-level exposure to prevent
# correlated risks and over-concentration.
#
# Features:
#   - Correlation detection between currency pairs
#   - Maximum exposure limits per currency (e.g., max 60% USD exposure)
#   - Same-direction trade rejection
#   - Currency exposure aggregation (EUR, USD, GBP, JPY)
# ============================================================

from utils.logger import get_logger
from core.constants import CORRELATION_GROUPS

log = get_logger("exposure_manager")

# Maximum exposure per base currency (e.g., no more than 60% in USD)
MAX_CURRENCY_EXPOSURE = 0.60

# Maximum total portfolio exposure
MAX_TOTAL_EXPOSURE = 0.80

# Correlation threshold (above this, pairs are considered correlated)
CORRELATION_THRESHOLD = 0.70

# Known high correlations (simplified static matrix)
CORRELATION_MATRIX: dict[str, dict[str, float]] = {
    "EURUSD": {"GBPUSD": 0.85, "AUDUSD": 0.72, "NZDUSD": 0.68, "USDCHF": -0.90, "USDCAD": -0.65, "USDJPY": -0.30},
    "GBPUSD": {"EURUSD": 0.85, "AUDUSD": 0.70, "NZDUSD": 0.75, "USDCHF": -0.82, "USDCAD": -0.60, "USDJPY": -0.28},
    "USDJPY": {"EURJPY": 0.92, "GBPJPY": 0.88, "AUDJPY": 0.85, "EURUSD": -0.30, "GBPUSD": -0.28, "USDCHF": 0.55},
    "AUDUSD": {"NZDUSD": 0.88, "EURUSD": 0.72, "GBPUSD": 0.70, "AUDJPY": -0.75, "USDCAD": -0.45},
    "USDCHF": {"EURUSD": -0.90, "GBPUSD": -0.82, "USDCAD": 0.68, "USDJPY": 0.55},
    "USDCAD": {"USDCHF": 0.68, "EURUSD": -0.65, "GBPUSD": -0.60, "AUDUSD": -0.45},
    "XAUUSD": {"EURUSD": 0.35, "GBPUSD": 0.30, "USDJPY": -0.25, "AUDUSD": 0.55},
}


class ExposureManager:
    """
    Portfolio Exposure & Correlation Risk Manager.

    AI-এর Exposure Management Brain.
    Monitors how much risk is concentrated in correlated pairs
    and individual currencies.

    Key responsibilities:
      1. Detect correlated positions (EURUSD + GBPUSD = double USD exposure)
      2. Enforce maximum exposure per currency
      3. Calculate total portfolio exposure
      4. Reject trades that would over-concentrate exposure

    Usage:
        em = ExposureManager()
        em.open_position("EURUSD", "BUY", lot=0.1)
        check = em.check_new_position("GBPUSD", "BUY", open_positions)
        if check["allowed"]:
            ... take trade ...
    """

    def __init__(
        self,
        max_currency_exposure: float = MAX_CURRENCY_EXPOSURE,
        max_total_exposure: float = MAX_TOTAL_EXPOSURE,
        correlation_threshold: float = CORRELATION_THRESHOLD,
    ):
        self.max_currency_exposure = max_currency_exposure
        self.max_total_exposure = max_total_exposure
        self.correlation_threshold = correlation_threshold

        # Open positions: {symbol: {"direction": "BUY/SELL", "lot": float}}
        self._open_positions: dict[str, dict] = {}

        log.info(
            f"[ExposureManager] Initialized | "
            f"Max currency exposure: {max_currency_exposure*100:.0f}% | "
            f"Max total exposure: {max_total_exposure*100:.0f}% | "
            f"Correlation threshold: {correlation_threshold}"
        )

    # ═══════════════════════════════════════════════════════
    # POSITION TRACKING
    # ═══════════════════════════════════════════════════════

    def open_position(
        self, symbol: str, direction: str, lot: float = 0.1
    ) -> None:
        """Register an open position."""
        symbol = symbol.upper()
        self._open_positions[symbol] = {
            "direction": direction.upper(),
            "lot": lot,
        }
        log.debug(
            f"[ExposureManager] Open: {direction} {symbol} ({lot} lots)"
        )

    def close_position(self, symbol: str) -> None:
        """Remove a position from tracking."""
        symbol = symbol.upper()
        if symbol in self._open_positions:
            del self._open_positions[symbol]
            log.debug(f"[ExposureManager] Closed: {symbol}")

    def get_open_positions(self) -> dict[str, dict]:
        """Get all open positions."""
        return dict(self._open_positions)

    # ═══════════════════════════════════════════════════════
    # CORRELATION CHECK
    # ═══════════════════════════════════════════════════════

    def get_correlation(self, pair1: str, pair2: str) -> float:
        """
        Get correlation between two pairs from static matrix.

        Returns correlation value between -1.0 and 1.0.
        """
        p1 = pair1.upper()
        p2 = pair2.upper()

        if p1 in CORRELATION_MATRIX and p2 in CORRELATION_MATRIX[p1]:
            return CORRELATION_MATRIX[p1][p2]
        if p2 in CORRELATION_MATRIX and p1 in CORRELATION_MATRIX[p2]:
            return CORRELATION_MATRIX[p2][p1]

        return 0.0  # unknown correlation, assume independent

    def find_correlated_pairs(
        self, symbol: str, direction: str
    ) -> list[dict]:
        """
        Find all open positions that are correlated with the given symbol.

        Returns list of {symbol, correlation, direction, same_side} dicts.
        """
        symbol = symbol.upper()
        correlated = []

        for open_sym, info in self._open_positions.items():
            corr = abs(self.get_correlation(symbol, open_sym))
            if corr >= self.correlation_threshold:
                same_side = (
                    info["direction"] == direction
                    if corr > 0
                    else info["direction"] != direction
                )
                correlated.append({
                    "symbol": open_sym,
                    "correlation": round(corr, 2),
                    "actual_correlation": round(
                        self.get_correlation(symbol, open_sym), 2
                    ),
                    "direction": info["direction"],
                    "same_side": same_side,
                    "lot": info["lot"],
                })

        return correlated

    # ═══════════════════════════════════════════════════════
    # MAIN GATE — Check if new position is allowed
    # ═══════════════════════════════════════════════════════

    def check_new_position(
        self,
        symbol: str,
        direction: str,
        open_positions: list[dict] | None = None,
    ) -> dict:
        """
        Check if a new position can be opened.

        Checks:
          1. Total exposure limit
          2. Currency-specific exposure limit
          3. Correlation with existing positions
          4. Same-direction correlated exposure

        Args:
            symbol: Currency pair to trade
            direction: "BUY" or "SELL"
            open_positions: List of open positions (or uses internal tracker)

        Returns:
            {"allowed": True/False, "reason": str, "correlated_pairs": [...]}
        """
        symbol = symbol.upper()
        direction = direction.upper()

        # Use internal positions if none provided
        if open_positions is not None:
            self._open_positions = {
                p["symbol"]: {"direction": p["direction"], "lot": p.get("lot", 0.1)}
                for p in open_positions
            }

        # 1. Total exposure check
        total_exposure = self.get_total_exposure_pct()
        if total_exposure >= self.max_total_exposure * 100:
            return {
                "allowed": False,
                "reason": (
                    f"Total exposure at {total_exposure:.0f}% "
                    f"(max {self.max_total_exposure*100:.0f}%)"
                ),
                "correlated_pairs": [],
            }

        # 2. Correlation check
        correlated = self.find_correlated_pairs(symbol, direction)

        # Check for same-side correlated exposure
        same_side_correlated = [
            c for c in correlated if c["same_side"]
        ]

        if len(same_side_correlated) >= 2:
            # More than 2 correlated positions in same direction = reject
            pairs_str = ", ".join(c["symbol"] for c in same_side_correlated)
            return {
                "allowed": False,
                "reason": (
                    f"Too many correlated positions with {symbol}: {pairs_str} "
                    f"(correlation >= {self.correlation_threshold})"
                ),
                "correlated_pairs": correlated,
            }

        if same_side_correlated:
            # One correlated position in same direction — warn but allow
            corr_pair = same_side_correlated[0]
            log.info(
                f"[ExposureManager] Correlation warning: "
                f"{symbol} {direction} correlated with "
                f"{corr_pair['symbol']} {corr_pair['direction']} "
                f"(r={corr_pair['correlation']})"
            )

        # 3. Currency exposure check
        base_curr, quote_curr = self._extract_currencies(symbol)
        for curr in [base_curr, quote_curr]:
            curr_exposure = self.get_currency_exposure_pct(curr)
            if curr_exposure >= self.max_currency_exposure * 100:
                return {
                    "allowed": False,
                    "reason": (
                        f"{curr} exposure at {curr_exposure:.0f}% "
                        f"(max {self.max_currency_exposure*100:.0f}%)"
                    ),
                    "correlated_pairs": correlated,
                }

        return {
            "allowed": True,
            "reason": "OK",
            "correlated_pairs": correlated,
        }

    # ═══════════════════════════════════════════════════════
    # EXPOSURE CALCULATIONS
    # ═══════════════════════════════════════════════════════

    def get_total_exposure_pct(self) -> float:
        """
        Get total portfolio exposure as percentage.

        Each position counts as 1 unit. Total exposure = positions / max_positions * 100.
        Using a simplified model where max 5 positions = 100% exposure.
        """
        max_positions = 5
        n_positions = len(self._open_positions)
        return (n_positions / max_positions) * 100

    def get_currency_exposure_pct(self, currency: str) -> float:
        """
        Get exposure percentage for a specific currency.

        A pair like EURUSD exposes you to both EUR and USD.
        BUY EURUSD = long EUR, short USD
        SELL EURUSD = short EUR, long USD
        """
        currency = currency.upper()
        max_exposure_positions = 4  # max 4 positions in same currency

        count = 0
        for sym, info in self._open_positions.items():
            base, quote = self._extract_currencies(sym)
            if base == currency:
                # If buying, we're long the base
                if info["direction"] == "BUY":
                    count += 1
                # If selling, we're short the base
                else:
                    count += 1  # still exposure, just short
            elif quote == currency:
                count += 1

        return (count / max_exposure_positions) * 100

    def get_currency_exposure_summary(self) -> dict:
        """
        Get exposure breakdown by currency.

        Returns:
            {"USD": 45.0, "EUR": 30.0, "GBP": 15.0, "JPY": 10.0}
        """
        currencies = set()
        for sym in self._open_positions:
            base, quote = self._extract_currencies(sym)
            currencies.update([base, quote])

        return {
            curr: round(self.get_currency_exposure_pct(curr), 1)
            for curr in currencies
        }

    def get_exposure_map(self) -> dict:
        """
        Get complete exposure map for dashboard.

        Returns:
            {
                "total_exposure_pct": 60.0,
                "currency_exposure": {"USD": 45, "EUR": 30},
                "positions": [
                    {"symbol": "EURUSD", "direction": "BUY", "lot": 0.1, "exposure_pct": 20},
                    ...
                ],
                "correlation_warnings": [...],
            }
        """
        warnings = []
        positions = list(self._open_positions.keys())

        for i, p1 in enumerate(positions):
            for p2 in positions[i+1:]:
                corr = abs(self.get_correlation(p1, p2))
                if corr >= self.correlation_threshold:
                    warnings.append({
                        "pair1": p1,
                        "pair2": p2,
                        "correlation": round(corr, 2),
                        "same_side": (
                            self._open_positions[p1]["direction"]
                            == self._open_positions[p2]["direction"]
                            if corr > 0
                            else self._open_positions[p1]["direction"]
                            != self._open_positions[p2]["direction"]
                        ),
                    })

        return {
            "total_exposure_pct": round(self.get_total_exposure_pct(), 1),
            "currency_exposure": self.get_currency_exposure_summary(),
            "positions": [
                {
                    "symbol": sym,
                    "direction": info["direction"],
                    "lot": info["lot"],
                }
                for sym, info in self._open_positions.items()
            ],
            "correlation_warnings": warnings,
            "max_currency_exposure_pct": self.max_currency_exposure * 100,
            "max_total_exposure_pct": self.max_total_exposure * 100,
        }

    # ═══════════════════════════════════════════════════════
    # INTERNAL HELPERS
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def _extract_currencies(symbol: str) -> tuple[str, str]:
        """Extract base and quote currency from symbol."""
        symbol = symbol.upper().replace("/", "").replace("=X", "").strip()
        if len(symbol) == 6:
            return symbol[:3], symbol[3:]
        elif symbol == "XAUUSD":
            return "XAU", "USD"
        elif symbol == "XAGUSD":
            return "XAG", "USD"
        else:
            return symbol[:3], symbol[3:] if len(symbol) > 3 else "USD"

    # ═══════════════════════════════════════════════════════
    # STATUS
    # ═══════════════════════════════════════════════════════

    def print_status(self) -> None:
        """Print exposure status."""
        exposure_map = self.get_exposure_map()
        bar = "=" * 46
        print(f"\n{bar}")
        print("  EXPOSURE MANAGER")
        print(bar)
        print(
            f"  Total Exposure     : {exposure_map['total_exposure_pct']:.0f}%"
        )

        if exposure_map["currency_exposure"]:
            print("  Currency Exposure:")
            for curr, pct in exposure_map["currency_exposure"].items():
                status = "OK" if pct < self.max_currency_exposure * 100 else "HIGH"
                print(f"    {curr}: {pct:.0f}% [{status}]")

        if exposure_map["positions"]:
            print("  Open Positions:")
            for p in exposure_map["positions"]:
                print(
                    f"    {p['symbol']} {p['direction']} ({p['lot']} lots)"
                )

        if exposure_map["correlation_warnings"]:
            print("  Correlation Warnings:")
            for w in exposure_map["correlation_warnings"]:
                side = "SAME SIDE" if w["same_side"] else "OPPOSITE"
                print(
                    f"    {w['pair1']} <-> {w['pair2']} "
                    f"(r={w['correlation']}, {side})"
                )

        print(bar + "\n")
