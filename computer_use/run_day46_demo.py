# computer_use/run_day46_demo.py  —  Day 46 Demo Runner
# ============================================================
# Run:  python -m computer_use.run_day46_demo
#
# Day 46-এর "AI Command Interface" (Section 10) সরাসরি দেখানোর জন্য —
# Master Analyst থেকে আসা JSON command-এর মতো করে chart control করা।
# ============================================================

from computer_use.browser_safety import BrowserSafetyLayer, BrowserSafetyConfig
from computer_use.tradingview_agent import TradingViewAgent


def main():
    safety = BrowserSafetyLayer(BrowserSafetyConfig(
        allowed_brokers=["tradingview.com"],
        allowed_pairs=["EURUSD"],
        allowed_timeframes=["M15", "H1"],
    ))

    agent = TradingViewAgent(safety=safety)
    agent.start()

    # AI Command Interface — ঠিক যেভাবে Master Analyst পাঠাবে
    result = agent.execute_command({
        "action":    "OPEN_CHART",
        "pair":      "EURUSD",
        "timeframe": "H1",
    })
    print(result)

    agent.fullscreen_chart()
    agent.controller.print_activity_log()

    agent.close()
    return result


if __name__ == "__main__":
    main()