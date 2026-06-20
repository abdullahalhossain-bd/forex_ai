# dashboard/app.py  —  Day 56 | AI Trading Command Center (Home)
# ============================================================
# এটা Day 56-এর মূল entry point। Streamlit multipage convention অনুযায়ী
# `streamlit run dashboard/app.py` চালালে এই ফাইল হোমপেজ হিসেবে খোলে,
# এবং dashboard/pages/ ফোল্ডারের প্রতিটা ফাইল সাইডবারে আলাদা পেজ হিসেবে
# auto-detect হয়:
#
#   1_live_room.py        → 📡 Live Trading Room
#   2_ai_brain.py          → 🧠 AI Brain Monitor
#   3_learning_center.py   → 📚 Learning Center
#   4_strategy_lab.py      → 🧪 Strategy Lab
#   5_risk_monitor.py      → 🛡 Risk Monitor
#
# Home page নিজে দেখায়: system health snapshot, today's quick KPIs,
# এবং Emergency Control Panel (⭐ Bonus 4) — যেটা সব পেজ থেকেই গুরুত্বপূর্ণ
# বলে এখানে top-level রাখা হয়েছে।
# ============================================================

import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import streamlit as st

from components import data_loader, metrics, alerts, charts

try:
    from streamlit_autorefresh import st_autorefresh
    AUTOREFRESH_AVAILABLE = True
except ImportError:
    AUTOREFRESH_AVAILABLE = False


# =========================
# পেজ কনফিগ
# =========================
st.set_page_config(
    page_title="AI Trading Command Center",
    page_icon="🧠",
    layout="wide",
)

# =========================
# Real-time auto refresh (⭐ spec requirement)
# =========================
with st.sidebar:
    st.markdown("### 🔄 Live Updates")
    refresh_on = st.toggle("Auto-refresh", value=True)
    interval = st.slider("Refresh interval (sec)", 5, 60, 15)

if refresh_on:
    if AUTOREFRESH_AVAILABLE:
        st_autorefresh(interval=interval * 1000, key="home_autorefresh")
    else:
        st.sidebar.caption("Install `streamlit-autorefresh` for live polling.")


# =========================
# Header
# =========================
st.title("🧠 AI Trading Command Center")
st.caption("Day 56 — One place to see everything your AI Trader sees, learns, and decides.")

ctrl = data_loader.get_system_control()
status_icon = "🟢" if ctrl.get("trading_enabled") else "🔴"
st.markdown(
    f"**Status:** {status_icon} {'Trading Enabled' if ctrl.get('trading_enabled') else 'Trading STOPPED'}  "
    f"&nbsp;|&nbsp; **Mode:** `{ctrl.get('mode', 'DEMO')}`",
    unsafe_allow_html=True,
)

st.divider()

# =========================
# Today's quick KPIs
# =========================
pnl = data_loader.get_todays_pnl()
risk = data_loader.get_risk_status()

kpi_cols = st.columns(4)
kpi_cols[0].metric("Today's P/L", f"${pnl['pnl']:,.2f}")
kpi_cols[1].metric("Win Rate Today", f"{pnl['win_rate']}%" if pnl["win_rate"] is not None else "—")
kpi_cols[2].metric("Trades Today", pnl["trades"])
kpi_cols[3].metric("Current Risk / Trade", f"{risk['current_risk_pct']}%")

st.divider()

# =========================
# System Health  (⭐ Bonus 3)
# =========================
health = data_loader.get_system_health()
alerts.system_health_panel(health)

st.divider()

# =========================
# Emergency Control Panel  (⭐ Bonus 4)
# =========================
alerts.emergency_control_panel()

st.divider()

# =========================
# Pending approvals banner (Day 55 human-approval-mode bridge)
# =========================
pending = data_loader.get_pending_optimizer_suggestions()
alerts.pending_approvals_alert(pending)

st.divider()

# =========================
# Navigation cards
# =========================
st.markdown("### 🧭 Go to")
nav_cols = st.columns(5)
nav_cols[0].page_link("pages/1_live_room.py", label="📡 Live Trading Room")
nav_cols[1].page_link("pages/2_ai_brain.py", label="🧠 AI Brain Monitor")
nav_cols[2].page_link("pages/3_learning_center.py", label="📚 Learning Center")
nav_cols[3].page_link("pages/4_strategy_lab.py", label="🧪 Strategy Lab")
nav_cols[4].page_link("pages/5_risk_monitor.py", label="🛡 Risk Monitor")

st.divider()
st.markdown("### 📈 Equity Snapshot")
charts.equity_curve_chart(data_loader.get_equity_curve())