# alerts/telegram_bot.py
# ============================================================
# Telegram Alert & Command System — Full Upgrade
# ============================================================
# Features:
#   - Trade opened notification (pair, entry, SL, TP, lot, confidence)
#   - Trade closed notification (pair, result, P/L, pips)
#   - Risk warnings (daily loss limit, drawdown alert)
#   - Daily report (total trades, wins, losses, P/L %, best/worst)
#   - System status (/status)
#   - Pause / Resume trading (/pause, /resume) with callback
#   - Morning briefing (market overview, session schedule)
#   - Weekly calendar (/calendar)
#   - All notifications formatted with emoji icons
#
#   - Hotfix: dynamic text (news event names, AI reasoning strings, etc.)
#     can contain '*', '_', '`', or '[' which breaks Telegram's legacy
#     Markdown entity parser and raises BadRequest: "Can't parse entities".
#     Two layers of protection are added:
#       1. `_escape_markdown()` strips those characters from any dynamic
#          string before it's interpolated into a template.
#       2. `send_message()` now falls back to a plain-text send (no
#          parse_mode) if the Markdown-formatted send fails for any
#          reason, so an alert is never silently dropped.
# ============================================================

import os
import asyncio
from datetime import datetime, timezone
from typing import Callable, Optional

from telegram import Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode
from database.db import TraderDB
from utils.logger import get_logger

log = get_logger("telegram_bot")

# ── Global trading-pause state + callback mechanism ───────────
# IS_TRADING_PAUSED is the canonical flag.  The optional
# _on_pause_changed callback lets the trading engine register
# a function that fires immediately whenever pause/resume changes,
# so there is zero lag between the Telegram command and the engine
# reacting to it.

IS_TRADING_PAUSED: bool = False
_on_pause_changed: Optional[Callable[[bool], None]] = None


def register_pause_callback(callback: Callable[[bool], None]) -> None:
    """
    Call this from the trading engine (main.py) to register a
    callback that fires the moment IS_TRADING_PAUSED changes.

        from alerts.telegram_bot import register_pause_callback
        register_pause_callback(my_engine.on_pause_changed)

    The callback receives the *new* value of IS_TRADING_PAUSED.
    """
    global _on_pause_changed
    _on_pause_changed = callback
    log.info("📞 Pause-state callback registered")


def _set_trading_paused(value: bool) -> None:
    """Internal helper — updates flag AND invokes callback."""
    global IS_TRADING_PAUSED
    IS_TRADING_PAUSED = value
    if _on_pause_changed is not None:
        try:
            _on_pause_changed(value)
        except Exception as exc:
            log.error(f"❌ Pause callback raised: {exc}")


def _escape_markdown(text) -> str:
    """
    Strip characters that break Telegram's legacy Markdown (V1) entity
    parser when they appear in dynamic/unsanitized strings (news event
    names, AI-generated reasoning text, pattern names, etc.).

    Legacy Markdown is fragile — a single unmatched '*', '_', '`', or '['
    anywhere in the message causes the ENTIRE send to fail with
    "Can't parse entities". Since these characters add no real value in
    plain alert text, the simplest robust fix is to just remove them from
    dynamic content before it's inserted into a template literal.
    """
    if text is None:
        return "—"
    if not isinstance(text, str):
        text = str(text)
    for ch in ("*", "_", "`", "["):
        text = text.replace(ch, "")
    return text


# ══════════════════════════════════════════════════════════════
#  TelegramNotifier — outbound notification templates
# ══════════════════════════════════════════════════════════════

class TelegramNotifier:
    """Handles every outgoing notification for the trading bot."""

    def __init__(self):
        self.token = os.getenv("TELEGRAM_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not self.token or not self.chat_id:
            log.warning("⚠️ Telegram credentials missing in .env!")
            self.bot = None
        else:
            self.bot = Bot(token=self.token)

    # ── core sender ─────────────────────────────────────────────

    async def send_message(self, text: str):
        """
        Send a message asynchronously to the configured chat.

        Tries Markdown formatting first. If Telegram rejects it (e.g. an
        unescaped '*'/'_'/'`' in dynamic content broke entity parsing),
        falls back to a plain-text send with no parse_mode so the alert
        still reaches the user instead of being silently dropped.
        """
        if not self.bot:
            return
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            log.error(f"❌ Failed to send Telegram alert (markdown): {e}")
            try:
                await self.bot.send_message(chat_id=self.chat_id, text=text)
            except Exception as e2:
                log.error(f"❌ Failed to send Telegram alert (plain fallback): {e2}")

    # ── 1. TRADE OPENED ────────────────────────────────────────

    async def notify_trade_open(
        self,
        trade_data: dict,
        confidence: int,
        reasons: list,
    ):
        """
        trade_data keys: pair, signal, entry, sl, tp, lot
        confidence: 0-100
        reasons: list of AI reasoning strings (top 3 shown)
        """
        pair   = _escape_markdown(trade_data.get("pair", "—"))
        signal = _escape_markdown(trade_data.get("signal", "—"))
        entry  = trade_data.get("entry", "—")
        sl     = trade_data.get("sl", "—")
        tp     = trade_data.get("tp", "—")
        lot    = trade_data.get("lot", "—")

        # confidence colour
        if confidence >= 80:
            conf_icon = "🟢"
        elif confidence >= 60:
            conf_icon = "🟡"
        else:
            conf_icon = "🔴"

        msg = (
            f"🟢 *TRADE OPENED* 🟢\n\n"
            f"📊 *Pair:* {pair}\n"
            f"📍 *Action:* {signal}\n"
            f"💰 *Entry:* `{entry}`\n"
            f"🛡 *Stop Loss:* `{sl}`\n"
            f"🎯 *Take Profit:* `{tp}`\n"
            f"📦 *Lot Size:* {lot}\n"
            f"{conf_icon} *Confidence:* {confidence}%\n\n"
            f"🧠 *AI Reasoning:*\n"
        )
        for r in reasons[:3]:
            msg += f"  ✅ {_escape_markdown(r)}\n"

        await self.send_message(msg)

    # ── 2. TRADE CLOSED ────────────────────────────────────────

    async def notify_trade_close(self, trade_data: dict):
        """
        trade_data keys: pair, result, pnl, pips, rr_ratio
        """
        result = trade_data.get("result", "CLOSED")
        pnl    = trade_data.get("pnl", 0)
        pips   = trade_data.get("pips", 0)
        rr     = trade_data.get("rr_ratio", 0)

        if result == "WIN":
            icon    = "🏆"
            pnl_str = f"+${round(pnl, 2)}"
        else:
            icon    = "🔴"
            pnl_str = f"-${abs(round(pnl, 2))}"

        pips_str = f"+{round(pips, 1)}" if pips >= 0 else f"{round(pips, 1)}"

        msg = (
            f"{icon} *TRADE CLOSED* {icon}\n\n"
            f"📊 *Pair:* {_escape_markdown(trade_data.get('pair', '—'))}\n"
            f"📋 *Result:* {_escape_markdown(result)}\n"
            f"💵 *Profit/Loss:* {pnl_str}\n"
            f"📏 *Pips:* {pips_str} pips\n"
            f"📈 *R:R Ratio:* 1:{rr}"
        )
        await self.send_message(msg)

    # ── 3. RISK WARNINGS ───────────────────────────────────────

    async def notify_daily_loss_limit(self, used: float, limit: float):
        """
        Fired when daily loss limit is reached or close to it.
        """
        pct = (used / limit * 100) if limit else 0
        if pct >= 100:
            msg = (
                f"🚨 *DAILY LOSS LIMIT REACHED* 🚨\n\n"
                f"💀 *Used:* ${used:,.2f} / ${limit:,.2f} ({pct:.0f}%)\n"
                f"🛑 *Action:* Trading has been automatically paused for the day.\n"
                f"⏳ Resume manually with /resume tomorrow."
            )
        else:
            msg = (
                f"⚠️ *DAILY LOSS WARNING* ⚠️\n\n"
                f"📊 *Used:* ${used:,.2f} / ${limit:,.2f} ({pct:.0f}%)\n"
                f"💡 Consider reducing position sizes or pausing trading."
            )
        await self.send_message(msg)

    async def notify_drawdown_alert(self, drawdown_pct: float, max_allowed: float):
        """
        Fired when account drawdown exceeds safe thresholds.
        """
        if drawdown_pct >= max_allowed:
            msg = (
                f"🔴 *DRAWDOWN ALERT* 🔴\n\n"
                f"📉 *Current Drawdown:* {drawdown_pct:.1f}%\n"
                f"🛡 *Max Allowed:* {max_allowed:.1f}%\n"
                f"🚨 *Action:* Circuit breaker triggered! Trading paused.\n"
                f"⏳ Review your positions and resume with /resume when ready."
            )
        else:
            msg = (
                f"⚠️ *DRAWDOWN WARNING* ⚠️\n\n"
                f"📉 *Current Drawdown:* {drawdown_pct:.1f}%\n"
                f"🛡 *Max Allowed:* {max_allowed:.1f}%\n"
                f"💡 Drawdown is approaching the safety limit. Trade with caution."
            )
        await self.send_message(msg)

    # ── 4. DAILY REPORT ────────────────────────────────────────

    async def notify_daily_report(self, report: dict):
        """
        report keys: total_trades, wins, losses, pnl_pct, pnl_abs,
                     best_trade (dict), worst_trade (dict), win_rate
        """
        total  = report.get("total_trades", 0)
        wins   = report.get("wins", 0)
        losses = report.get("losses", 0)
        wr     = report.get("win_rate", 0)
        pnl_pct = report.get("pnl_pct", 0)
        pnl_abs = report.get("pnl_abs", 0)

        pnl_icon = "📈" if pnl_abs >= 0 else "📉"
        pnl_sign = "+" if pnl_abs >= 0 else ""

        msg = (
            f"📊 *DAILY TRADING REPORT* 📊\n"
            f"🗓 *Date:* {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n\n"
            f"🔢 *Total Trades:* {total}\n"
            f"✅ *Wins:* {wins}  |  ❌ *Losses:* {losses}\n"
            f"🎯 *Win Rate:* {wr:.1f}%\n"
            f"{pnl_icon} *P/L:* {pnl_sign}${round(pnl_abs, 2)} ({pnl_sign}{pnl_pct:.2f}%)\n\n"
        )

        best = report.get("best_trade")
        if best:
            msg += (
                f"🏆 *Best Trade:*\n"
                f"  📊 {_escape_markdown(best.get('pair', '—'))} → +${round(best.get('pnl', 0), 2)} "
                f"({best.get('pips', 0)} pips)\n\n"
            )

        worst = report.get("worst_trade")
        if worst:
            msg += (
                f"💀 *Worst Trade:*\n"
                f"  📊 {_escape_markdown(worst.get('pair', '—'))} → -${abs(round(worst.get('pnl', 0), 2))} "
                f"({worst.get('pips', 0)} pips)\n\n"
            )

        msg += "🤖 _AI Trader — keeping you informed_"
        await self.send_message(msg)

    # ── 5. NEWS WARNING ────────────────────────────────────────

    async def notify_news_warning(self, event_name: str, time_remaining: str):
        safe_event = _escape_markdown(event_name)
        safe_time = _escape_markdown(time_remaining)
        msg = (
            f"⚠️ *HIGH IMPACT NEWS WARNING* ⚠️\n\n"
            f"📰 *Event:* {safe_event}\n"
            f"⏰ *Time:* Happening in {safe_time}\n"
            f"🛑 *Action:* Trading paused automatically."
        )
        await self.send_message(msg)

    # ── 6. WEEKLY CALENDAR ─────────────────────────────────────

    async def notify_weekly_calendar(self, weekly_calendar: dict):
        """
        weekly_calendar — NewsFilter.get_weekly_calendar() output:
            {"2026-06-22": [{"time":..,"currency":..,"event":..,"volatility":{...}}, ...], ...}
        """
        if not weekly_calendar:
            msg = "📅 *FOREX WEEKLY CALENDAR*\n\n✅ No major high-impact events this week."
            await self.send_message(msg)
            return

        msg = "📅 *FOREX WEEKLY CALENDAR* 📅\n\n"
        for day, events in weekly_calendar.items():
            msg += f"🗓 *{_escape_markdown(day)}*\n"
            if not events:
                msg += "  ✅ No major events\n\n"
                continue
            for e in events:
                vol_level = e.get("volatility", {}).get("level", "")
                tag = "⚠️ " if vol_level in ("HIGH", "EXTREME") else "🔸 "
                msg += (
                    f"  {tag}{_escape_markdown(e.get('time'))}  "
                    f"{_escape_markdown(e.get('currency'))}  "
                    f"{_escape_markdown(e.get('event'))}\n"
                )
            msg += "\n"

        await self.send_message(msg)

    # ── 7. MORNING BRIEFING (enhanced with session schedule) ───

    async def notify_morning_briefing(
        self,
        date_str: str,
        high_impact_today: list,
        fundamental_scores: dict | None = None,
        session_schedule: dict | None = None,
    ):
        """
        Enhanced morning briefing with market overview + session schedule.

        session_schedule — optional dict of session windows:
            {
                "Asian":    {"open": "00:00 UTC", "close": "08:00 UTC", "active": True},
                "London":   {"open": "07:00 UTC", "close": "16:00 UTC", "active": True},
                "New York": {"open": "12:00 UTC", "close": "21:00 UTC", "active": True},
            }
        """
        msg = f"🌅 *AI TRADER — MORNING BRIEFING* 🌅\n\n🗓 *Date:* {_escape_markdown(date_str)}\n\n"

        # ── Session Schedule ──────────────────────────────────
        if session_schedule:
            msg += "🕐 *Trading Sessions Today:*\n"
            for session, info in session_schedule.items():
                icon = "🟢" if info.get("active") else "🔴"
                msg += (
                    f"  {icon} *{_escape_markdown(session)}:* "
                    f"{info.get('open', '—')} → {info.get('close', '—')}\n"
                )
            msg += "\n"

        # ── High Impact Events ────────────────────────────────
        if high_impact_today:
            msg += "⚠️ *High Impact Events Today:*\n"
            pause_windows = []
            for e in high_impact_today:
                vol = e.get("volatility", {})
                vol_level = vol.get("level", "?")
                tag = "🔴" if vol_level in ("HIGH", "EXTREME") else "🔸"
                msg += (
                    f"  {tag} {_escape_markdown(e.get('time'))} — "
                    f"{_escape_markdown(e.get('currency'))} "
                    f"{_escape_markdown(e.get('event'))} [{vol_level}]\n"
                )
                pause_windows.append(
                    f"{_escape_markdown(e.get('currency'))} pairs: "
                    f"±30 min around {_escape_markdown(e.get('time'))}"
                )

            msg += "\n⏸ *Trading Pause Windows:*\n"
            for w in pause_windows:
                msg += f"  🛑 {w}\n"
        else:
            msg += "✅ No major high-impact events today — normal trading conditions.\n"

        # ── Fundamental Bias ──────────────────────────────────
        if fundamental_scores:
            msg += "\n🌐 *Fundamental Bias:*\n"
            for cur, score in fundamental_scores.items():
                if score > 10:
                    icon = "🟢"
                elif score < -10:
                    icon = "🔴"
                else:
                    icon = "🟡"
                msg += f"  {icon} {_escape_markdown(cur)}: {score:+d}\n"

        msg += "\n🤖 _Have a profitable day!_"
        await self.send_message(msg)


# ══════════════════════════════════════════════════════════════
#  INCOMING COMMAND HANDLERS
# ══════════════════════════════════════════════════════════════

async def cmd_start(update, context: ContextTypes.DEFAULT_TYPE):
    """Welcome message with available commands."""
    msg = (
        "🤖 *AI Forex Trader Bot*\n\n"
        "📡 *Available Commands:*\n\n"
        "📊 /status — System status & portfolio snapshot\n"
        "🛑 /pause — Pause all trading\n"
        "▶️ /resume — Resume trading\n"
        "📅 /calendar — Weekly economic calendar\n"
        "📈 /daily — Today's trading report\n"
        "ℹ️ /help — Show this message\n\n"
        "🧠 _Powered by AI Trading Engine_"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def cmd_help(update, context: ContextTypes.DEFAULT_TYPE):
    """Alias for /start."""
    await cmd_start(update, context)


async def cmd_status(update, context: ContextTypes.DEFAULT_TYPE):
    """Full system status with portfolio snapshot."""
    try:
        db = TraderDB()
        stats = db.get_overall_stats()
    except Exception:
        stats = {}

    status_str = "⏸️ PAUSED" if IS_TRADING_PAUSED else "🚀 RUNNING"
    status_icon = "🟡" if IS_TRADING_PAUSED else "🟢"

    balance = stats.get("balance", 0)
    total   = stats.get("total", 0)
    wins    = stats.get("wins", 0)
    losses  = stats.get("losses", 0)
    wr      = stats.get("win_rate", 0)
    pnl     = stats.get("total_pnl", 0)
    open_t  = stats.get("open_trades", 0)

    pnl_sign = "+" if pnl >= 0 else ""
    pnl_icon = "📈" if pnl >= 0 else "📉"

    msg = (
        f"📊 *AI TRADER — SYSTEM STATUS* 📊\n\n"
        f"{status_icon} *System State:* {status_str}\n\n"
        f"💰 *Balance:* ${balance:,.2f}\n"
        f"{pnl_icon} *Total P/L:* {pnl_sign}${round(pnl, 2)}\n\n"
        f"🔢 *Total Trades:* {total}\n"
        f"✅ *Wins:* {wins}  |  ❌ *Losses:* {losses}\n"
        f"🎯 *Win Rate:* {wr}%\n"
        f"📂 *Open Positions:* {open_t}\n\n"
        f"🕐 *Last Check:* {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def cmd_pause(update, context: ContextTypes.DEFAULT_TYPE):
    """Pause trading — sets IS_TRADING_PAUSED and invokes callback."""
    if IS_TRADING_PAUSED:
        await update.message.reply_text(
            "⏸️ Trading is *already paused*.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    _set_trading_paused(True)
    log.info("🛑 Trading paused via Telegram /pause command")

    await update.message.reply_text(
        "🛑 *TRADING PAUSED* 🛑\n\n"
        "No new trades will be executed.\n"
        "▶️ Use /resume to restart trading.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_resume(update, context: ContextTypes.DEFAULT_TYPE):
    """Resume trading — clears IS_TRADING_PAUSED and invokes callback."""
    if not IS_TRADING_PAUSED:
        await update.message.reply_text(
            "🚀 Trading is *already running*.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    _set_trading_paused(False)
    log.info("▶️ Trading resumed via Telegram /resume command")

    await update.message.reply_text(
        "▶️ *TRADING RESUMED* ▶️\n\n"
        "🤖 Scanning market for setups...\n"
        "🛑 Use /pause to stop at any time.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_calendar(update, context: ContextTypes.DEFAULT_TYPE):
    """Show this week's high-impact economic events."""
    try:
        from fundamental.news_filter import NewsFilter
        nf = NewsFilter()
        calendar = nf.get_weekly_calendar()
    except Exception:
        calendar = None

    if not calendar:
        await update.message.reply_text(
            "📅 No major high-impact events found for this week.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    msg = "📅 *FOREX WEEKLY CALENDAR* 📅\n\n"
    for day, events in calendar.items():
        msg += f"🗓 *{_escape_markdown(day)}*\n"
        for e in events:
            vol_level = e.get("volatility", {}).get("level", "")
            tag = "🔴 " if vol_level in ("HIGH", "EXTREME") else "🔸 "
            msg += (
                f"  {tag}{_escape_markdown(e.get('time'))}  "
                f"{_escape_markdown(e.get('currency'))}  "
                f"{_escape_markdown(e.get('event'))}\n"
            )
        msg += "\n"

    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def cmd_daily(update, context: ContextTypes.DEFAULT_TYPE):
    """Generate today's trading report on demand."""
    try:
        db = TraderDB()
        stats = db.get_overall_stats()
        # Build a daily-style report from overall stats as a best-effort
        pnl = stats.get("total_pnl", 0)
        balance = stats.get("balance", 10000)
        pnl_pct = (pnl / 10000) * 100 if balance else 0

        report = {
            "total_trades": stats.get("total", 0),
            "wins":         stats.get("wins", 0),
            "losses":       stats.get("losses", 0),
            "win_rate":     stats.get("win_rate", 0),
            "pnl_abs":      pnl,
            "pnl_pct":      pnl_pct,
        }

        notifier = TelegramNotifier()
        await notifier.notify_daily_report(report)
        await update.message.reply_text(
            "📊 Daily report sent above ☝️",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ Could not generate daily report: {e}",
            parse_mode=ParseMode.MARKDOWN,
        )


# ══════════════════════════════════════════════════════════════
#  BOT STARTUP
# ══════════════════════════════════════════════════════════════

def start_telegram_bot_polling():
    """
    Call from main.py as a background thread or async task.
    Registers all command handlers and starts long-polling.
    """
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        log.warning("⚠️ TELEGRAM_TOKEN not set — skipping bot polling.")
        return

    app = Application.builder().token(token).build()

    # Register command handlers
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("status",   cmd_status))
    app.add_handler(CommandHandler("pause",    cmd_pause))
    app.add_handler(CommandHandler("resume",   cmd_resume))
    app.add_handler(CommandHandler("calendar", cmd_calendar))
    app.add_handler(CommandHandler("daily",    cmd_daily))

    log.info("🤖 Telegram Command Polling Started (7 commands registered)...")
    app.run_polling(close_loop=False)