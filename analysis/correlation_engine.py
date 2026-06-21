# analysis/correlation_engine.py  —  Day 65 | Intermarket Correlation Engine
# ============================================================
# একটা forex pair (বা XAUUSD) আর global asset (DXY/Gold/Oil/US10Y/
# SP500/VIX)-এর মধ্যে rolling correlation calculate করে।
#
# Pearson correlation ব্যবহার করা হয়েছে (numpy দিয়ে)। ফলাফল -1.0
# (perfectly inverse) থেকে +1.0 (perfectly aligned) পর্যন্ত।
#
# Example (doc অনুযায়ী):
#   EURUSD vs DXY  ->  -0.92   (DXY উঠলে EURUSD সাধারণত নামে)
# ============================================================

import numpy as np
from utils.logger import get_logger

log = get_logger("correlation_engine")

CORR_PERIOD   = "1mo"
CORR_INTERVAL = "1d"


class CorrelationEngine:
    """
    Usage:
        engine = CorrelationEngine()
        result = engine.calculate("EURUSD", "DX-Y.NYB", label="DXY")
        matrix = engine.build_matrix("EURUSD")
    """

    def calculate(self, pair_symbol: str, asset_symbol: str, label: str = "") -> dict:
        """
        pair_symbol  : "EURUSD" / "EURUSD=X" (auto-normalized)
        asset_symbol : "DX-Y.NYB", "GC=F" ইত্যাদি yfinance ticker

        Returns:
            {"pair": "EURUSD", "asset": "DXY", "correlation": -0.92,
             "strength": "STRONG", "direction": "INVERSE", "samples": 21}
        """
        try:
            import yfinance as yf

            pair_yf = self._normalize(pair_symbol)
            symbols = [pair_yf, asset_symbol]

            data   = yf.download(symbols, period=CORR_PERIOD, interval=CORR_INTERVAL, progress=False)
            closes = data.get("Close") if data is not None else None

            if closes is None or closes.empty or pair_yf not in closes.columns or asset_symbol not in closes.columns:
                return self._empty(pair_symbol, label)

            a = closes[pair_yf].pct_change().dropna()
            b = closes[asset_symbol].pct_change().dropna()

            joined = a.align(b, join="inner")
            a, b   = joined
            if len(a) < 5:
                return self._empty(pair_symbol, label)

            corr = float(np.corrcoef(a.values, b.values)[0, 1])
            corr = round(corr, 2) if corr == corr else 0.0   # NaN check

            return {
                "pair":        pair_symbol.upper().replace("/", "").replace("=X", "")[:6],
                "asset":       label or asset_symbol,
                "correlation": corr,
                "strength":    self._strength(corr),
                "direction":   "ALIGNED" if corr >= 0 else "INVERSE",
                "samples":     len(a),
            }

        except Exception as e:
            log.warning(f"[CorrelationEngine] Error calculating {pair_symbol} vs {asset_symbol}: {e}")
            return self._empty(pair_symbol, label)

    def build_matrix(self, pair_symbol: str) -> dict:
        """
        একটা pair-এর জন্য সব major global asset-এর সাথে correlation।

        Returns:
            {
                "matrix": {"EURUSD_DXY": -0.92, "EURUSD_GOLD": 0.41, ...},
                "details": {"DXY": {...}, "GOLD": {...}, ...},
                "pair": "EURUSD",
            }
        """
        from analysis.macro_data import GLOBAL_SYMBOLS

        clean_pair = pair_symbol.upper().replace("/", "").replace("=X", "")[:6]
        matrix  = {}
        details = {}

        for label, sym in GLOBAL_SYMBOLS.items():
            res = self.calculate(pair_symbol, sym, label=label)
            matrix[f"{clean_pair}_{label}"] = res["correlation"]
            details[label] = res

        log.info(f"[CorrelationEngine] {clean_pair} correlation matrix: {matrix}")
        return {"matrix": matrix, "details": details, "pair": clean_pair}

    # ── helpers ─────────────────────────────────────────────────

    def _normalize(self, symbol: str) -> str:
        symbol = symbol.upper().replace("/", "").replace("=X", "")
        return symbol + "=X"

    def _strength(self, corr: float) -> str:
        a = abs(corr)
        if a >= 0.7: return "STRONG"
        if a >= 0.4: return "MODERATE"
        if a >= 0.2: return "WEAK"
        return "NEGLIGIBLE"

    def _empty(self, pair_symbol: str, label: str) -> dict:
        return {
            "pair":        pair_symbol.upper().replace("/", "").replace("=X", "")[:6],
            "asset":       label or "UNKNOWN",
            "correlation": 0.0,
            "strength":    "NEGLIGIBLE",
            "direction":   "NONE",
            "samples":     0,
        }

    # ═══════════════════════════════════════════════════════════
    # PRINT SUMMARY
    # ═══════════════════════════════════════════════════════════

    def print_summary(self, matrix_result: dict) -> None:
        bar = "─" * 48
        print(f"\n{bar}")
        print(f"  🔗  CORRELATION MATRIX — {matrix_result.get('pair')}  (Day 65)")
        print(bar)
        for key, val in matrix_result.get("matrix", {}).items():
            icon = "🔴" if val <= -0.4 else ("🟢" if val >= 0.4 else "🟡")
            print(f"  {key:<18}  {icon}  {val:+.2f}")
        print(bar + "\n")