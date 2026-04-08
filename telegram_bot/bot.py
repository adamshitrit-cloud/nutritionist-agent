"""
NutriAI Telegram Marketing Bot
================================
Automatically posts daily nutrition content to a Telegram channel in Hebrew.

Schedules:
  07:00 Israel time — Morning tip
  13:00 Israel time — Midday fact / recipe / quote (rotating)
  20:00 Israel time — Evening tip
  Sunday 09:00 Israel time — Weekly challenge

Admin commands:
  /post    — Force-send the next scheduled post now
  /stats   — Show channel subscriber count
  /schedule — Show today's post schedule

Environment variables required:
  TELEGRAM_BOT_TOKEN   — Bot token from @BotFather
  TELEGRAM_CHANNEL_ID  — Channel username (e.g. @NutriAIChannel) or numeric ID
"""

import logging
import os
import datetime
from typing import Optional

import pytz
from dotenv import load_dotenv
from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    ChatMemberHandler,
    ContextTypes,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError

import content as ct

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv()

TELEGRAM_BOT_TOKEN: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID: str = os.environ.get("TELEGRAM_CHANNEL_ID", "")

ISRAEL_TZ = pytz.timezone("Asia/Jerusalem")

# Logging
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("nutriai_bot")

# ---------------------------------------------------------------------------
# State (simple in-memory counters; reset on restart)
# ---------------------------------------------------------------------------

_state: dict = {
    "tip_index": 0,
    "midday_index": 0,  # cycles: 0=fact, 1=recipe, 2=quote (mod 3)
    "challenge_week": 0,
    "posts_sent_today": 0,
    "total_posts_sent": 0,
}


def _now_israel() -> datetime.datetime:
    return datetime.datetime.now(ISRAEL_TZ)


# ---------------------------------------------------------------------------
# Post builders
# ---------------------------------------------------------------------------

def build_morning_post() -> str:
    """Build the 07:00 morning tip post."""
    tip = ct.get_daily_tip(_state["tip_index"])
    _state["tip_index"] += 1
    return tip


def build_midday_post() -> str:
    """Build the 13:00 post — rotates between fact, recipe, motivational quote."""
    idx = _state["midday_index"]
    _state["midday_index"] += 1

    cycle = idx % 3
    if cycle == 0:
        return ct.get_did_you_know(idx // 3)
    elif cycle == 1:
        return ct.get_recipe(idx // 3)
    else:
        return ct.get_motivational_quote(idx // 3)


def build_evening_post() -> str:
    """Build the 20:00 evening tip post."""
    tip = ct.get_daily_tip(_state["tip_index"])
    _state["tip_index"] += 1
    return tip


def build_weekly_challenge_post() -> str:
    """Build the Sunday 09:00 weekly challenge post."""
    challenge = ct.get_weekly_challenge(_state["challenge_week"])
    _state["challenge_week"] += 1
    return challenge


# ---------------------------------------------------------------------------
# Core send helper
# ---------------------------------------------------------------------------

async def send_channel_post(bot: Bot, text: str, label: str = "post") -> bool:
    """Send a message to the configured channel. Returns True on success."""
    if not TELEGRAM_CHANNEL_ID:
        logger.error("TELEGRAM_CHANNEL_ID is not set — cannot send post.")
        return False
    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHANNEL_ID,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=False,
        )
        _state["posts_sent_today"] += 1
        _state["total_posts_sent"] += 1
        logger.info("Sent %s to channel %s", label, TELEGRAM_CHANNEL_ID)
        return True
    except TelegramError as exc:
        logger.error("Failed to send %s: %s", label, exc)
        return False


# ---------------------------------------------------------------------------
# Scheduled job callbacks
# ---------------------------------------------------------------------------

async def job_morning_post(context: ContextTypes.DEFAULT_TYPE) -> None:
    """07:00 — Daily morning tip."""
    logger.info("Running scheduled job: morning_post")
    text = build_morning_post()
    await send_channel_post(context.bot, text, label="morning_post")
    # Reset daily counter at morning post
    _state["posts_sent_today"] = 0


async def job_midday_post(context: ContextTypes.DEFAULT_TYPE) -> None:
    """13:00 — Midday rotating content."""
    logger.info("Running scheduled job: midday_post")
    text = build_midday_post()
    await send_channel_post(context.bot, text, label="midday_post")


async def job_evening_post(context: ContextTypes.DEFAULT_TYPE) -> None:
    """20:00 — Evening tip."""
    logger.info("Running scheduled job: evening_post")
    text = build_evening_post()
    await send_channel_post(context.bot, text, label="evening_post")


async def job_weekly_challenge(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sunday 09:00 — Weekly challenge."""
    logger.info("Running scheduled job: weekly_challenge")
    text = build_weekly_challenge_post()
    await send_channel_post(context.bot, text, label="weekly_challenge")


# ---------------------------------------------------------------------------
# Command handlers (admin)
# ---------------------------------------------------------------------------

async def cmd_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/post — Force-send the next scheduled post immediately."""
    if not update.message:
        return

    now = _now_israel()
    hour = now.hour

    # Determine which post type to send based on current time of day
    if hour < 10:
        text = build_morning_post()
        label = "morning_post (forced)"
    elif hour < 16:
        text = build_midday_post()
        label = "midday_post (forced)"
    else:
        text = build_evening_post()
        label = "evening_post (forced)"

    success = await send_channel_post(context.bot, text, label=label)
    if success:
        await update.message.reply_text("✅ הפוסט נשלח לערוץ בהצלחה!")
    else:
        await update.message.reply_text(
            "❌ שגיאה בשליחת הפוסט. בדוק את הלוגים."
        )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stats — Show channel stats."""
    if not update.message:
        return

    try:
        count = await context.bot.get_chat_member_count(TELEGRAM_CHANNEL_ID)
        now_str = _now_israel().strftime("%d/%m/%Y %H:%M")
        text = (
            f"📊 <b>סטטיסטיקות NutriAI</b>\n\n"
            f"👥 מנויים בערוץ: <b>{count:,}</b>\n"
            f"📨 פוסטים נשלחו היום: <b>{_state['posts_sent_today']}</b>\n"
            f"📬 סה״כ פוסטים נשלחו: <b>{_state['total_posts_sent']}</b>\n"
            f"💡 טיפ נוכחי: <b>{_state['tip_index'] % 30 + 1}/30</b>\n"
            f"🏆 אתגר שבועי נוכחי: <b>{_state['challenge_week'] % 7 + 1}/7</b>\n"
            f"🕐 עדכון אחרון: {now_str}"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    except TelegramError as exc:
        logger.error("cmd_stats error: %s", exc)
        await update.message.reply_text(f"❌ שגיאה בקבלת סטטיסטיקות: {exc}")


async def cmd_schedule(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """/schedule — Show today's posting schedule."""
    if not update.message:
        return

    now = _now_israel()
    today_str = now.strftime("%A, %d/%m/%Y")
    weekday = now.weekday()  # 6 = Sunday in Python

    schedule_text = (
        f"📅 <b>לוח פוסטים — {today_str}</b>\n\n"
        f"🌅 07:00 — טיפ תזונתי בוקר\n"
        f"☀️ 13:00 — תוכן מסתובב (עובדה / מתכון / ציטוט)\n"
        f"🌙 20:00 — טיפ תזונתי ערב\n"
    )

    if weekday == 6:  # Sunday
        schedule_text += "🏆 09:00 — <b>אתגר שבועי (ראשון!)</b>\n"
    else:
        days_until_sunday = (6 - weekday) % 7
        schedule_text += (
            f"\n⏳ האתגר השבועי הבא: בעוד {days_until_sunday} ימים\n"
        )

    schedule_text += (
        f"\n📊 פוסטים נשלחו היום: {_state['posts_sent_today']}\n"
        f"🔢 סה״כ מאז ההפעלה: {_state['total_posts_sent']}"
    )

    await update.message.reply_text(schedule_text, parse_mode=ParseMode.HTML)


# ---------------------------------------------------------------------------
# New member welcome handler
# ---------------------------------------------------------------------------

async def handle_chat_member(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Welcome new members who join the channel."""
    result = update.chat_member
    if not result:
        return

    old_status = result.old_chat_member.status
    new_status = result.new_chat_member.status

    # Detect new member (was not member, now is member)
    joined = old_status in ("left", "kicked", "restricted") and new_status in (
        "member",
        "administrator",
    )

    if joined:
        welcome_text = ct.get_welcome_message()
        try:
            await context.bot.send_message(
                chat_id=result.chat.id,
                text=welcome_text,
                parse_mode=ParseMode.HTML,
            )
            logger.info(
                "Sent welcome message to channel %s for new member",
                result.chat.id,
            )
        except TelegramError as exc:
            logger.error("Failed to send welcome message: %s", exc)


# ---------------------------------------------------------------------------
# Application setup
# ---------------------------------------------------------------------------

def register_jobs(application: Application) -> None:
    """Register all scheduled jobs with the job queue."""
    jq = application.job_queue
    if jq is None:
        logger.error(
            "Job queue is None — ensure python-telegram-bot[job-queue] is installed."
        )
        return

    # Morning tip — 07:00 Israel
    jq.run_daily(
        job_morning_post,
        time=datetime.time(hour=7, minute=0, second=0, tzinfo=ISRAEL_TZ),
        name="morning_post",
    )

    # Midday rotating content — 13:00 Israel
    jq.run_daily(
        job_midday_post,
        time=datetime.time(hour=13, minute=0, second=0, tzinfo=ISRAEL_TZ),
        name="midday_post",
    )

    # Evening tip — 20:00 Israel
    jq.run_daily(
        job_evening_post,
        time=datetime.time(hour=20, minute=0, second=0, tzinfo=ISRAEL_TZ),
        name="evening_post",
    )

    # Weekly challenge — Sunday 09:00 Israel
    # weekday: 0=Monday … 6=Sunday
    jq.run_daily(
        job_weekly_challenge,
        time=datetime.time(hour=9, minute=0, second=0, tzinfo=ISRAEL_TZ),
        days=(6,),  # Sunday only
        name="weekly_challenge",
    )

    logger.info("All scheduled jobs registered.")


def build_application() -> Application:
    """Build and configure the Telegram Application."""
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN environment variable is not set. "
            "Please set it before running the bot."
        )
    if not TELEGRAM_CHANNEL_ID:
        raise ValueError(
            "TELEGRAM_CHANNEL_ID environment variable is not set. "
            "Please set it before running the bot."
        )

    application = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )

    # Admin command handlers
    application.add_handler(CommandHandler("post", cmd_post))
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CommandHandler("schedule", cmd_schedule))

    # New member welcome
    application.add_handler(
        ChatMemberHandler(handle_chat_member, ChatMemberHandler.CHAT_MEMBER)
    )

    # Register scheduled jobs
    register_jobs(application)

    return application


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logger.info("Starting NutriAI Telegram Bot...")
    logger.info("Channel: %s", TELEGRAM_CHANNEL_ID)

    app = build_application()

    logger.info(
        "Bot is running. Scheduled posts at 07:00, 13:00, 20:00 (IL time) "
        "and weekly challenge every Sunday at 09:00."
    )
    app.run_polling(
        allowed_updates=["message", "chat_member"],
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
