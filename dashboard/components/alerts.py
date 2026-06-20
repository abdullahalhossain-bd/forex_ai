# dashboard/components/alerts.py  —  Day 56 | Alerts, System Health, Emergency Controls
# ============================================================
# ⭐ Bonus 3: System Health Panel
# ⭐ Bonus 4: Emergency Control Panel
#
# Emergency panel সরাসরি trading engine-কে control করে না (dashboard ও
# engine আলাদা process) — বরং memory/system_control.json-এ একটা flag
# লিখে দেয়, যেটা trading engine প্রতি cycle-এ check করে নিজেকে
# pause/resume করতে পারে। এটাই standard "dashboard ↔ engine" pattern।
# ============================================================

import streamlit as st

from components.data_loader import get_system_control, set_system_control


def alert_banner(level: str, message: str) -> None:
    level = level.upper()
    if level == "SUCCESS":
        st.success(message)
    elif level == "WARNING":
        st.warning(message)
    elif level == "ERROR":
        st.error(message)
    else:
        st.info(message)


def system_health_panel(health: dict) -> None:
    """⭐ MT5 / Database / Vision AI connection status।"""
    st.markdown("#### 🩺 System Health")
    c1, c2, c3, c4 = st.columns(4)

    def badge(v):
        v = (v or "").upper()
        return f"🟢 {v}" if v in ("CONNECTED", "OK") else f"🔴 {v}"

    c1.metric("MT5", badge(health.get("mt5")))
    c2.metric("Database", badge(health.get("database")))
    c3.metric("Vision AI", badge(health.get("vision_ai")))
    c4.metric("Last Restart", health.get("last_restart", "Unknown"))


def emergency_control_panel() -> None:
    """⭐ Stop / Resume / Close-all / Demo-Live switch।"""
    st.markdown("#### 🛑 Emergency Controls")
    ctrl = get_system_control()

    status_text = "🟢 TRADING ENABLED" if ctrl.get("trading_enabled") else "🔴 TRADING STOPPED"
    st.markdown(f"**Current status:** {status_text}  |  **Mode:** `{ctrl.get('mode', 'DEMO')}`")

    c1, c2, c3, c4 = st.columns(4)

    if c1.button("🛑 Stop Trading", use_container_width=True, type="primary"):
        set_system_control(trading_enabled=False, last_changed_by="dashboard_user")
        st.warning("Trading STOPPED. The engine will halt new entries on its next check cycle.")
        st.rerun()

    if c2.button("▶ Resume", use_container_width=True):
        set_system_control(trading_enabled=True, last_changed_by="dashboard_user")
        st.success("Trading RESUMED.")
        st.rerun()

    if c3.button("❌ Close All Positions", use_container_width=True):
        set_system_control(close_all_requested=True, last_changed_by="dashboard_user")
        st.error("Close-all request sent. The execution engine should pick this up next cycle.")

    new_mode = "LIVE" if ctrl.get("mode", "DEMO") == "DEMO" else "DEMO"
    if c4.button(f"🔁 Switch to {new_mode}", use_container_width=True):
        if new_mode == "LIVE":
            st.session_state["_confirm_live_switch"] = True
        else:
            set_system_control(mode=new_mode, last_changed_by="dashboard_user")
            st.success(f"Switched to {new_mode} mode.")
            st.rerun()

    if st.session_state.get("_confirm_live_switch"):
        st.warning("⚠️ You're about to switch to LIVE trading with real funds.")
        cc1, cc2 = st.columns(2)
        if cc1.button("✅ Confirm switch to LIVE"):
            set_system_control(mode="LIVE", last_changed_by="dashboard_user")
            st.session_state["_confirm_live_switch"] = False
            st.success("Switched to LIVE mode.")
            st.rerun()
        if cc2.button("Cancel"):
            st.session_state["_confirm_live_switch"] = False
            st.rerun()


def pending_approvals_alert(pending: list, page_hint: str = "Strategy Lab") -> None:
    """Human-approval-mode suggestions থাকলে banner দেখায়।"""
    if pending:
        alert_banner(
            "WARNING",
            f"⏸️ {len(pending)} optimizer suggestion(s) awaiting your approval — see **{page_hint}**.",
        )