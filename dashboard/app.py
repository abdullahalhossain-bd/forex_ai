import datetime

import numpy as np
import pandas as pd
import streamlit as st


# =========================
# পেজ কনফিগ
# =========================
st.set_page_config(
    page_title="AI Trading Dashboard",
    layout="wide",
)


# =========================
# মক ডাটা (পরে API দিয়ে replace করা যাবে)
# =========================
def get_live_signals() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Pair": ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"],
            "Signal": ["BUY", "SELL", "BUY", "BUY"],
            "Confidence": [0.78, 0.65, 0.82, 0.74],
            "Time": [datetime.datetime.now() for _ in range(4)],
        }
    )


def get_trade_history() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Pair": ["EURUSD", "GBPUSD", "XAUUSD"],
            "Type": ["BUY", "SELL", "BUY"],
            "Profit": [12.5, -8.2, 25.0],
            "Date": pd.date_range(end=datetime.datetime.today(), periods=3),
        }
    )


def get_metrics() -> dict:
    return {
        "Win Rate": "62%",
        "Total Trades": 120,
        "Profit Factor": 1.8,
        "Drawdown": "9.4%",
    }


# =========================
# সাইডবার নেভিগেশন
# =========================
menu = st.sidebar.selectbox(
    "📌 Menu",
    ["Live", "Performance", "Trade History", "Analysis", "Settings"],
)


# =========================
# Live পেজ
# =========================
if menu == "Live":
    st.title("📡 Live Signals & Open Trades")

    df = get_live_signals()
    st.dataframe(df, use_container_width=True)

    st.subheader("🔵 Live Market Overview")
    st.line_chart(np.random.randn(20, 4))


# =========================
# Performance পেজ
# =========================
elif menu == "Performance":
    st.title("📊 Performance Dashboard")

    metrics = get_metrics()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Win Rate", metrics["Win Rate"])
    col2.metric("Total Trades", metrics["Total Trades"])
    col3.metric("Profit Factor", metrics["Profit Factor"])
    col4.metric("Drawdown", metrics["Drawdown"])

    st.subheader("Equity Curve")
    st.area_chart(np.cumsum(np.random.randn(50)))


# =========================
# Trade History পেজ
# =========================
elif menu == "Trade History":
    st.title("📜 Trade History")

    df = get_trade_history()
    st.dataframe(df, use_container_width=True)

    st.subheader("Profit Distribution")
    st.bar_chart(df["Profit"])


# =========================
# Analysis পেজ
# =========================
elif menu == "Analysis":
    st.title("📈 Market Analysis")

    st.write("AI-based market overview (replace with your model output)")

    st.success("Trend: Bullish (EURUSD, XAUUSD)")
    st.warning("Risk: Medium volatility expected")

    st.line_chart(np.random.randn(100, 3))


# =========================
# Settings পেজ
# =========================
elif menu == "Settings":
    st.title("⚙️ Risk Settings")

    risk = st.slider("Risk per trade (%)", 0.1, 5.0, 1.0)
    leverage = st.selectbox("Leverage", [10, 20, 50, 100, 200])

    st.write("Selected Risk:", risk, "%")
    st.write("Selected Leverage:", leverage)
