# computer_use/run_day45_demo.py  —  Day 45 Demo Runner
# ============================================================
# Run:  python -m computer_use.run_day45_demo
#
# Day 45 doc-এর "TradingView Automation Test" সরাসরি চালানোর জন্য।
# Expected output:
#   🤖 Computer Agent
#   TradingView opened ✅
#   EURUSD loaded ✅
#   M15 selected ✅
# ============================================================

from computer_use.computer_agent import ComputerAgent


def main():
    hands = ComputerAgent(allowed_symbols=["EURUSD"], max_lot=0.1)
    result = hands.tradingview_test(symbol="EURUSD", timeframe="15")
    hands.stop_browser()
    return result


if __name__ == "__main__":
    main()