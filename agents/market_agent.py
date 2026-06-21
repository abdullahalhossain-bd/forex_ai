# agents/market_agent.py  —  Day 12 | Market Data Agent

from data.fetcher import DataFetcher
from data.validator import DataValidator
from data.indicators import Indicators
from analysis.timeframe import MultiTimeframeAnalyzer
from analysis.market_regime import MarketRegimeDetector
from utils.logger import get_logger

log = get_logger("market_agent")


class MarketAgent:
    """
    Market data collect, validate, indicator calculate, regime detect।
    Pipeline এর প্রথম agent।
    """

    def __init__(self, symbol: str, timeframe: str = "15m"):
        self.symbol    = symbol
        self.timeframe = timeframe

    def run(self) -> dict:
        log.info(f"[MarketAgent] Running for {self.symbol} {self.timeframe}")

        # MTF
        mtf      = MultiTimeframeAnalyzer(self.symbol)
        mtf_data = mtf.analyze(["1d", "4h", "1h", "15m"])
        mtf_bias = mtf.print_summary(mtf_data)

        # Fetch
        fetcher = DataFetcher()
        df = fetcher.fetch_ohlcv(self.symbol, self.timeframe, limit=300)
        if df is None:
            log.error("Data fetch failed")
            return {"error": "fetch_failed"}

        # Validate
        if not DataValidator().validate(df, self.symbol, self.timeframe):
            log.error("Validation failed")
            return {"error": "validation_failed"}

        # Indicators
        ind    = Indicators()
        df     = ind.add_all(df)
        ind.get_summary(df)
        ind_ctx = ind.get_ai_context(df)

        # Regime
        regime_detector = MarketRegimeDetector()
        regime_result   = regime_detector.detect(df)
        regime_detector.print_summary(regime_result)
        regime_ctx = regime_detector.get_ai_context(regime_result)

        log.info(
            f"[MarketAgent] Done — "
            f"Price: {ind_ctx.get('price')} | "
            f"Trend: {ind_ctx.get('trend')} | "
            f"Regime: {regime_result.get('regime')}"
        )

        return {
            "df":          df,
            "ind_ctx":     ind_ctx,
            "regime":      regime_result,
            "regime_ctx":  regime_ctx,
            "mtf_bias":    mtf_bias,
            "symbol":      self.symbol,
            "timeframe":   self.timeframe,
        }