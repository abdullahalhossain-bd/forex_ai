# alerts/telegram_bot.py
# ============================================================
# Day 20 | Telegram Alert & Command System (AI Communication)
# ============================================================

import os
import asyncio
from telegram import Bot
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.constants import ParseMode
from database.db import TraderDB
from utils.logger import get_logger

log = get_logger("telegram_bot")

# গ্লোবাল স্টেট ট্র্যাকিং (সিম্পল পজ/রেজিউম মেকানিজম)
IS_TRADING_PAUSED = False

class TelegramNotifier:
    """ট্রেডিং বটের সমস্ত আউটগোয়িং নোটিফিকেশন হ্যান্ডেলার।"""
    def __init__(self):
        self.token = os.getenv("TELEGRAM_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not self.token or not self.chat_id:
            log.warning("⚠️ Telegram credentials missing in .env!")
            self.bot = None
        else:
            self.bot = Bot(token=self.token)

    async def send_message(self, text: str):
        """এসিনক্রোনাসলি টেলিগ্রামে মেসেজ সেন্ড করার কোর মেথড।"""
        if not self.bot:
            return
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            log.error(f"❌ Failed to send Telegram alert: {e}")

    # ── নোটিফিকেশন টেমপ্লেট সমূহ ──────────────────────────────────
    
    async def notify_trade_open(self, trade_data: dict, confidence: int, reasons: list):
        msg = (
            f"🟢 *NEW TRADE OPENED*\n\n"
            f"• *Pair:* {trade_data.get('pair')}\n"
            f"• *Action:* {trade_data.get('signal')}\n"
            f"• *Entry:* {trade_data.get('entry')}\n"
            f"• *SL:* {trade_data.get('sl')} | *TP:* {trade_data.get('tp')}\n"
            f"• *Lot Size:* {trade_data.get('lot')}\n"
            f"• *Confidence:* {confidence}%\n\n"
            f"🧠 *AI Reasoning:*\n"
        )
        for r in reasons[:3]:  # শীর্ষ ৩টি কারণ দেখাবে
            msg += f" ✔ {r}\n"
        await self.send_message(msg)

    async def notify_trade_close(self, trade_data: dict):
        result = trade_data.get("result", "CLOSED")
        icon = "🏆" if result == "WIN" else "🔴"
        pnl_prefix = "+" if trade_data.get("pnl", 0) >= 0 else ""
        
        msg = (
            f"{icon} *TRADE CLOSED*\n\n"
            f"• *Pair:* {trade_data.get('pair')}\n"
            f"• *Result:* {result}\n"
            f"• *Profit/Loss:* {pnl_prefix}${round(trade_data.get('pnl', 0), 2)}\n"
            f"• *R:R Ratio:* 1:{trade_data.get('rr_ratio', 0)}"
        )
        await self.send_message(msg)

    async def notify_news_warning(self, event_name: str, time_remaining: str):
        msg = (
            f"⚠️ *HIGH IMPACT NEWS WARNING*\n\n"
            f"• *Event:* {event_name}\n"
            f"• *Time:* Happening in {time_remaining}\n"
            f"🛑 *Action:* Trading paused automatically."
        )
        await self.send_message(msg)


# ── ইনকামিং কমান্ড হ্যান্ডেলারস (Emergency Commands) ──────────────────

async def cmd_status(update, context: ContextTypes.DEFAULT_TYPE):
    """বটের বর্তমান পোর্টফোলিও স্ট্যাটাস দেখাবে।"""
    db = TraderDB()  # আপনার database.py এর কানেক্টর
    stats = db.get_overall_stats()
    status_str = "⏸️ PAUSED" if IS_TRADING_PAUSED else "🚀 RUNNING"
    
    msg = (
        f"📊 *AI TRADER STATUS*\n\n"
        f"• *System State:* {status_str}\n"
        f"• *Total Trades:* {stats.get('total', 0)}\n"
        f"• *Win Rate:* {stats.get('win_rate', 0)}%\n"
        f"• *Total PnL:* ${round(stats.get('total_pnl') or 0, 2)}\n"
        f"• *Open Positions:* {stats.get('open_trades', 0)}"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)

async def cmd_pause(update, context: ContextTypes.DEFAULT_TYPE):
    global IS_TRADING_PAUSED
    IS_TRADING_PAUSED = True
    await update.message.reply_text("🛑 *Trading system paused manually.* No new trades will be executed.", parse_mode=ParseMode.MARKDOWN)

async def cmd_resume(update, context: ContextTypes.DEFAULT_TYPE):
    global IS_TRADING_PAUSED
    IS_TRADING_PAUSED = False
    await update.message.reply_text("🚀 *Trading system resumed.* Scanning market for setups...", parse_mode=ParseMode.MARKDOWN)


def start_telegram_bot_polling():
    """এই ফাংশনটি main.py থেকে ব্যাকগ্রাউন্ড থ্রেড বা এসিঙ্ক টাস্ক হিসেবে রান করবে।"""
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        return
        
    app = Application.builder().token(token).build()
    
    # কমান্ড রেজিস্টার করা
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    
    log.info("🤖 Telegram Command Polling Started...")
    app.run_polling(close_loop=False)