# alerts/telegram_bot.py
# ============================================================
# Telegram Alert & Command System — Full Upgrade (Fixed)
# ============================================================
# FIXES APPLIED:
#   1. send_message() — correct fallback order:
#      Markdown first → plain text fallback (not reversed).
#   2. Command handlers (cmd_status, cmd_calendar, cmd_daily, etc.)
#      now route through a shared _reply() helper that also falls back
#      to plain text, so DB/dynamic content can never break a reply.
#   3. cmd_daily — no longer creates a new TelegramNotifier() on every
#      call; reuses a module-level shared instance instead.
#   4. IS_TRADING_PAUSED protected by asyncio.Lock to prevent race
#      conditions in concurrent async environments.
#   5. notify_weekly_calendar / cmd_calendar — long messages are
#      automatically chunked into ≤4096-char pieces so Telegram never
#      silently drops an oversized message.
# ============================================================

import os
import asyncio
import time
from collections import deque
from datetime import datetime, timezone
from typing import Callable, Optional

from telegram import Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode
from database.db import TraderDB
from utils.logger import get_logger

log = get_logger("telegram_bot")

# ── Global trading-pause state + callback mechanism ───────────

IS_TRADING_PAUSED: bool = False
_pause_lock = asyncio.Lock()
_on_pause_changed: Optional[Callable[[bool], None]] = None

TELEGRAM_MSG_LIMIT = 4096  # Telegram hard limit per message

# ── Day 81+ hotfix: per-channel rate limiter ──────────────────
# Telegram floods when the bot sends dozens of messages per minute
# (trade-open alerts, news alerts, confluence alerts, restart alerts).
# This sliding-window limiter drops messages above TELEGRAM_MAX_MSG_PER_MIN
# (default 10) so the bot doesn't get muted by users or rate-limited by Telegram.

class _RateLimiter:
    """Sliding-window per-channel rate limiter."""
    def __init__(self, max_per_min: int = 10):
        self.max_per_min = max_per_min
        self._timestamps: deque = deque()  # monotonic timestamps of sent msgs
        self._dropped_count = 0

    def allow(self) -> bool:
        now = time.monotonic()
        # Evict timestamps older than 60 seconds
        cutoff = now - 60.0
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()
        if len(self._timestamps) >= self.max_per_min:
            self._dropped_count += 1
            if self._dropped_count % 10 == 1:  # log every 10th drop
                log.warning(
                    f"[Telegram] rate limit: dropped {self._dropped_count} messages "
                    f"({len(self._timestamps)}/{self.max_per_min} in last 60s)"
                )
            return False
        self._timestamps.append(now)
        return True

# Singleton rate limiter — loaded from config on first use
_RATE_LIMITER: Optional[_RateLimiter] = None

def _get_rate_limiter() -> _RateLimiter:
    global _RATE_LIMITER
    if _RATE_LIMITER is None:
        try:
            from config import TELEGRAM_MAX_MSG_PER_MIN
            limit = TELEGRAM_MAX_MSG_PER_MIN
        except Exception:
            limit = 10
        _RATE_LIMITER = _RateLimiter(max_per_min=limit)
    return _RATE_LIMITER


def register_pause_callback(callback: Callable[[bool], None]) -> None:
    """
    Register a callback that fires the moment IS_TRADING_PAUSED changes.

        from alerts.telegram_bot import register_pause_callback
        register_pause_callback(my_engine.on_pause_changed)

    The callback receives the *new* value of IS_TRADING_PAUSED.
    """
    global _on_pause_changed
    _on_pause_changed = callback
    log.info("📞 Pause-state callback registered")


async def _set_trading_paused(value: bool) -> None:
    """Internal async helper — updates flag AND invokes callback."""
    global IS_TRADING_PAUSED
    async with _pause_lock:
        IS_TRADING_PAUSED = value
    if _on_pause_changed is not None:
        try:
            _on_pause_changed(value)
        except Exception as exc:
            log.error(f"❌ Pause callback raised: {exc}")


def _escape_markdown(text) -> str:
    """
    Strip characters that break Telegram's legacy Markdown (V1) entity
    parser when they appear in dynamic/unsanitized strings.

    A single unmatched '*', '_', '`', or '[' causes the ENTIRE send to
    fail with "Can't parse entities". Removing them from dynamic content
    before interpolation is the simplest robust fix.
    """
    if text is None:
        return "—"
    if not isinstance(text, str):
        text = str(text)
    for ch in ("*", "_", "`", "["):
        text = text.replace(ch, "")
    return text


def _chunk_message(text: str, limit: int = TELEGRAM_MSG_LIMIT) -> list[str]:
    """
    Split a long message into chunks of at most `limit` characters,
    splitting on newlines where possible to avoid cutting mid-line.
    """
    if len(text) <= limit:
        return [text]

    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


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
        Send a Markdown-formatted message. If Telegram rejects the
        Markdown (e.g. unmatched entity), falls back to plain text so
        alerts are never silently dropped.

        Long messages are chunked automatically to stay within Telegram's
        4096-character limit.

        Day 81+ hotfix: per-channel rate limiter drops messages above
        TELEGRAM_MAX_MSG_PER_MIN (default 10) to prevent Telegram floods.
        """
        if not self.bot:
            return

        # Day 81+ rate limit check
        if not _get_rate_limiter().allow():
            return  # silently drop — already logged in _RateLimiter.allow()

        for chunk in _chunk_message(text):
            # FIX #1: Try Markdown first, fall back to plain text.
            try:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=chunk,
                    parse_mode=ParseMode.MARKDOWN,
                )
            except Exception as e:
                log.warning(f"⚠️ Markdown send failed ({e}), retrying as plain text…")
                try:
                    await self.bot.send_message(
                        chat_id=self.chat_id,
                        text=chunk,
                    )
                except Exception as e2:
                    log.error(f"❌ Failed to send Telegram alert (all attempts): {e2}")

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
        """Fired when daily loss limit is reached or close to it."""
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
        """Fired when account drawdown exceeds safe thresholds."""
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
        total   = report.get("total_trades", 0)
        wins    = report.get("wins", 0)
        losses  = report.get("losses", 0)
        wr      = report.get("win_rate", 0)
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
                f"  📊 {_escape_markdown(best.get('pair', '—'))} → "
                f"+${round(best.get('pnl', 0), 2)} "
                f"({best.get('pips', 0)} pips)\n\n"
            )

        worst = report.get("worst_trade")
        if worst:
            msg += (
                f"💀 *Worst Trade:*\n"
                f"  📊 {_escape_markdown(worst.get('pair', '—'))} → "
                f"-${abs(round(worst.get('pnl', 0), 2))} "
                f"({worst.get('pips', 0)} pips)\n\n"
            )

        msg += "🤖 _AI Trader — keeping you informed_"
        await self.send_message(msg)

    # ── 5. NEWS WARNING ────────────────────────────────────────

    async def notify_news_warning(self, event_name: str, time_remaining: str):
        safe_event = _escape_markdown(event_name)
        safe_time  = _escape_markdown(time_remaining)
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

        FIX #5: Long calendars are auto-chunked so Telegram never drops them.
        """
        if not weekly_calendar:
            await self.send_message(
                "📅 *FOREX WEEKLY CALENDAR*\n\n✅ No major high-impact events this week."
            )
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

        # send_message() handles chunking internally
        await self.send_message(msg)

    # ── 7. MORNING BRIEFING ────────────────────────────────────

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
        msg = (
            f"🌅 *AI TRADER — MORNING BRIEFING* 🌅\n\n"
            f"🗓 *Date:* {_escape_markdown(date_str)}\n\n"
        )

        if session_schedule:
            msg += "🕐 *Trading Sessions Today:*\n"
            for session, info in session_schedule.items():
                icon = "🟢" if info.get("active") else "🔴"
                msg += (
                    f"  {icon} *{_escape_markdown(session)}:* "
                    f"{info.get('open', '—')} → {info.get('close', '—')}\n"
                )
            msg += "\n"

        if high_impact_today:
            msg += "⚠️ *High Impact Events Today:*\n"
            pause_windows = []
            for e in high_impact_today:
                vol       = e.get("volatility", {})
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


# ── Module-level shared notifier (used by command handlers) ───
# FIX #3: cmd_daily no longer instantiates a new TelegramNotifier()
# on every call — they all share this singleton instead.
_shared_notifier: Optional[TelegramNotifier] = None


def get_notifier() -> TelegramNotifier:
    """Return (or lazily create) the shared TelegramNotifier instance."""
    global _shared_notifier
    if _shared_notifier is None:
        _shared_notifier = TelegramNotifier()
    return _shared_notifier


# ── Shared reply helper for command handlers ──────────────────
# FIX #2: All command handlers use this instead of reply_text()
# with hardcoded ParseMode.MARKDOWN, so dynamic DB content is safe.

async def _reply(update, text: str):
    """
    Reply to a Telegram update with Markdown, falling back to plain
    text if parsing fails. Chunks long messages automatically.
    """
    for chunk in _chunk_message(text):
        try:
            await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            log.warning(f"⚠️ Markdown reply failed ({e}), retrying as plain text…")
            try:
                await update.message.reply_text(chunk)
            except Exception as e2:
                log.error(f"❌ Failed to reply to Telegram command: {e2}")


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
    await _reply(update, msg)


async def cmd_help(update, context: ContextTypes.DEFAULT_TYPE):
    """Alias for /start."""
    await cmd_start(update, context)


async def cmd_status(update, context: ContextTypes.DEFAULT_TYPE):
    """Full system status with portfolio snapshot."""
    try:
        db    = TraderDB()
        stats = db.get_overall_stats()
    except Exception:
        stats = {}

    status_str  = "⏸️ PAUSED" if IS_TRADING_PAUSED else "🚀 RUNNING"
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
    await _reply(update, msg)


async def cmd_pause(update, context: ContextTypes.DEFAULT_TYPE):
    """Pause trading — sets IS_TRADING_PAUSED and invokes callback."""
    if IS_TRADING_PAUSED:
        await _reply(update, "⏸️ Trading is *already paused*.")
        return

    await _set_trading_paused(True)
    log.info("🛑 Trading paused via Telegram /pause command")
    await _reply(
        update,
        "🛑 *TRADING PAUSED* 🛑\n\n"
        "No new trades will be executed.\n"
        "▶️ Use /resume to restart trading.",
    )


async def cmd_resume(update, context: ContextTypes.DEFAULT_TYPE):
    """Resume trading — clears IS_TRADING_PAUSED and invokes callback."""
    if not IS_TRADING_PAUSED:
        await _reply(update, "🚀 Trading is *already running*.")
        return

    await _set_trading_paused(False)
    log.info("▶️ Trading resumed via Telegram /resume command")
    await _reply(
        update,
        "▶️ *TRADING RESUMED* ▶️\n\n"
        "🤖 Scanning market for setups…\n"
        "🛑 Use /pause to stop at any time.",
    )


async def cmd_calendar(update, context: ContextTypes.DEFAULT_TYPE):
    """Show this week's high-impact economic events."""
    try:
        from fundamental.news_filter import NewsFilter
        nf       = NewsFilter()
        calendar = nf.get_weekly_calendar()
    except Exception:
        calendar = None

    if not calendar:
        await _reply(update, "📅 No major high-impact events found for this week.")
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

    # _reply() handles chunking for long calendars
    await _reply(update, msg)


async def cmd_daily(update, context: ContextTypes.DEFAULT_TYPE):
    """Generate today's trading report on demand."""
    try:
        db      = TraderDB()
        stats   = db.get_overall_stats()
        pnl     = stats.get("total_pnl", 0)
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

        # FIX #3: Use shared notifier, not a new instance
        await get_notifier().notify_daily_report(report)
        await _reply(update, "📊 Daily report sent above ☝️")

    except Exception as e:
        await _reply(update, f"❌ Could not generate daily report: {_escape_markdown(str(e))}")


# ══════════════════════════════════════════════════════════════
#  BOT STARTUP
# ══════════════════════════════════════════════════════════════
def start_telegram_bot_polling():
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        log.warning("⚠️ TELEGRAM_TOKEN not set — skipping bot polling.")
        return

    # ✅ নতুন event loop এ চালাও — main loop এর সাথে conflict হবে না
    import threading

    def _run():
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        app = Application.builder().token(token).build()
        app.add_handler(CommandHandler("start",    cmd_start))
        app.add_handler(CommandHandler("help",     cmd_help))
        app.add_handler(CommandHandler("status",   cmd_status))
        app.add_handler(CommandHandler("pause",    cmd_pause))
        app.add_handler(CommandHandler("resume",   cmd_resume))
        app.add_handler(CommandHandler("calendar", cmd_calendar))
        app.add_handler(CommandHandler("daily",    cmd_daily))

        # ── Network-resilient error handler ────────────────────────
        # When the network is down (DNS, getaddrinfo failed, proxy error,
        # etc.), python-telegram-bot logs a full traceback every 5 seconds
        # and floods the log.  Catch these specific errors and log a
        # single compact line instead — the polling loop will auto-retry.
        async def _on_error(update, context):
            err = context.error
            err_str = str(err)
            is_network = any(s in err_str.lower() for s in (
                "getaddrinfo", "connection", "timeout", "timed out",
                "network", "dns", "unreachable", "refused", "reset",
                "11001", "etimedout", "ehostunreach",
            ))
            if is_network:
                # Compact one-line warning — no traceback spam.
                log.warning(f"⚠️ Telegram network error (auto-retry): {err_str[:80]}")
            else:
                # Real error — log normally with traceback.
                log.error(f"❌ Telegram error: {err}", exc_info=context.error)
        app.add_error_handler(_on_error)

        log.info("🤖 Telegram Bot Polling Started…")
        try:
            app.run_polling()  # এখন আলাদা thread এ চলবে
        except Exception as e:
            log.error(f"❌ Telegram polling crashed: {e}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()