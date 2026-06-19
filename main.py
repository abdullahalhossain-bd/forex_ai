# main.py  —  Day 7 | Week 1 Final Integration
# ============================================================
# একটি command-এ AI Trader পুরো perception pipeline চালাবে:
#
#   1. Market data fetch
#   2. Indicators calculate
#   3. Candlestick patterns detect
#   4. Support / Resistance find
#   5. Complete chart show
#   6. Full AI Market Report print
# ============================================================

import time
from config import PROJECT_NAME
from data.fetcher import DataFetcher
from data.indicators import Indicators
from analysis.patterns import PatternDetector
from analysis.support_resistance import SupportResistance
from visualization.chart import ChartEngine


# ── Config ──────────────────────────────────────────────────
SYMBOL    = "EUR/USDT"
TIMEFRAME = "15m"
CANDLES   = 300
# ────────────────────────────────────────────────────────────


def run_analysis():

    print("\n" + "█" * 48)
    print(f"  🤖  {PROJECT_NAME}")
    print(f"  📅  Day 7 — Week 1 Integration & Test")
    print("█" * 48)

    start = time.time()

    # ── 1. Market Data ───────────────────────────────────────
    _step(1, "Fetching market data")
    fetcher = DataFetcher()
    df = fetcher.fetch_ohlcv(
        symbol    = SYMBOL,
        timeframe = TIMEFRAME,
        limit     = CANDLES,
    )
    if df is None:
        print("❌ Data fetch failed. Check internet connection.")
        return
    print(f"   ✅ {len(df)} candles received | Latest: {df.index[-1]}")

    # ── 2. Indicators ────────────────────────────────────────
    _step(2, "Calculating indicators")
    ind = Indicators()
    df  = ind.add_all(df)
    ind_ctx = ind.get_ai_context(df)
    ind.get_summary(df)

    # ── 3. Candlestick Patterns ──────────────────────────────
    _step(3, "Detecting candlestick patterns")
    detector = PatternDetector()
    df = detector.run_full_detection(df)
    detector.get_latest_patterns(df, lookback=10)
    pat_ctx = detector.get_ai_pattern_context(df, lookback=5)

    # ── 4. Support & Resistance ──────────────────────────────
    _step(4, "Finding support & resistance zones")
    sr     = SupportResistance(window=5, tolerance=0.0015)
    result = sr.analyze(df)
    sr.get_summary(result)
    sr_ctx = sr.get_ai_context(result)

    # ── 5. Full AI Market Report ─────────────────────────────
    _step(5, "Generating AI Market Report")
    _print_report(ind_ctx, pat_ctx, sr_ctx)

    # ── 6. Chart ─────────────────────────────────────────────
    _step(6, "Opening interactive chart")
    chart = ChartEngine(symbol=SYMBOL, timeframe=TIMEFRAME)
    chart.create_full_chart(
        df               = df,
        support_zones    = result['support_zones'],
        resistance_zones = result['resistance_zones'],
        patterns_df      = df,
        show             = True,
        save_html        = "data/chart.html",
    )

    # ── Done ─────────────────────────────────────────────────
    elapsed = round(time.time() - start, 1)
    print("\n" + "═" * 48)
    print(f"  ✅  Week 1 Complete!  ({elapsed}s)")
    print(f"  📂  Chart saved → data/chart.html")
    print("═" * 48)
    print()
    print("  👁️  AI Trader এখন যা পারে:")
    print("      ✔ Live market data নিতে পারে")
    print("      ✔ Indicators calculate করতে পারে")
    print("      ✔ Candlestick patterns detect করতে পারে")
    print("      ✔ Support/Resistance খুঁজতে পারে")
    print("      ✔ Visual chart দেখাতে পারে")
    print()
    print("  🧠  Week 2 এ তৈরি হবে — Decision Brain")
    print("      (Market Structure → Trade Signal → Risk)")
    print()


# ── Helpers ─────────────────────────────────────────────────

def _step(n, msg):
    print(f"\n[{n}/6] {msg}...")


def _print_report(ind_ctx, pat_ctx, sr_ctx):
    """Human-readable full market report"""

    # Bias score — সব signal দেখে overall direction
    bias_score = 0
    reasons    = []

    # Trend
    trend = ind_ctx.get('trend', '')
    if 'bullish' in trend:
        bias_score += 2 if 'strong' in trend else 1
        reasons.append(f"Trend: {trend}")
    elif 'bearish' in trend:
        bias_score -= 2 if 'strong' in trend else 1
        reasons.append(f"Trend: {trend}")

    # RSI
    rsi = ind_ctx.get('rsi', 50)
    rsi_sig = ind_ctx.get('rsi_signal', '')
    if rsi_sig == 'bullish_zone':   bias_score += 1; reasons.append("RSI: bullish zone")
    elif rsi_sig == 'bearish_zone': bias_score -= 1; reasons.append("RSI: bearish zone")
    elif rsi_sig == 'oversold':     bias_score += 2; reasons.append("RSI: oversold (bounce possible)")
    elif rsi_sig == 'overbought':   bias_score -= 2; reasons.append("RSI: overbought (drop possible)")

    # MACD
    macd_cross = ind_ctx.get('macd_cross', '')
    if macd_cross == 'bullish_cross': bias_score += 1; reasons.append("MACD: bullish cross")
    elif macd_cross == 'bearish_cross': bias_score -= 1; reasons.append("MACD: bearish cross")

    # Pattern
    pat_sig = pat_ctx.get('pattern_signal', '')
    if 'Bullish' in pat_sig: bias_score += 2; reasons.append(f"Pattern: {pat_ctx.get('latest_pattern')}")
    elif 'Bearish' in pat_sig: bias_score -= 2; reasons.append(f"Pattern: {pat_ctx.get('latest_pattern')}")

    # Location
    location = sr_ctx.get('price_location', '')
    if location == 'near_support':    bias_score += 1; reasons.append("Location: near support")
    elif location == 'near_resistance': bias_score -= 1; reasons.append("Location: near resistance")

    # Final bias
    if bias_score >= 3:      bias = "🟢 STRONG BUY"
    elif bias_score >= 1:    bias = "🟢 BUY BIAS"
    elif bias_score <= -3:   bias = "🔴 STRONG SELL"
    elif bias_score <= -1:   bias = "🔴 SELL BIAS"
    else:                    bias = "🟡 NEUTRAL — WAIT"

    # Print
    print("\n" + "═" * 48)
    print("  📋  AI MARKET REPORT")
    print("═" * 48)
    print(f"  Symbol      :  {SYMBOL}  {TIMEFRAME}")
    print(f"  Price       :  {ind_ctx.get('price')}")
    print()
    print(f"  ── Analysis ──")
    print(f"  Trend       :  {ind_ctx.get('trend', '').upper()}")
    print(f"  RSI         :  {rsi:.1f}  ({rsi_sig})")
    print(f"  MACD        :  {macd_cross}")
    print(f"  Pattern     :  {pat_ctx.get('latest_pattern', 'none')}  {pat_sig}")
    print(f"  Location    :  {location}")
    print()
    print(f"  ── S/R ──")
    print(f"  Resistance  :  {sr_ctx.get('nearest_resistance')}  "
          f"(+{sr_ctx.get('dist_to_resistance_pips')} pips)")
    print(f"  Support     :  {sr_ctx.get('nearest_support')}  "
          f"(-{sr_ctx.get('dist_to_support_pips')} pips)")
    print(f"  Pivot       :  {sr_ctx.get('pivot')}")
    print()
    print(f"  ── Signal Reasons ──")
    for r in reasons:
        print(f"    • {r}")
    print()
    print(f"  ┌─────────────────────────────────┐")
    print(f"  │  BIAS SCORE : {bias_score:+d}  →  {bias:<18}│")
    print(f"  └─────────────────────────────────┘")
    print("═" * 48)


if __name__ == "__main__":
    run_analysis()