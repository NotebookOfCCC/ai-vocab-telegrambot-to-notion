"""
News Digest Bot

Telegram bot for daily AI builder digests from follow-builders feeds.
- Fetches tweets, podcasts, blogs from GitHub CDN (free)
- Summarizes via Haiku (~$0.005/day)
- Configurable language (zh/en/bilingual) and push time
- Config dual-saved to Notion + GitHub, read from Notion
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import json
import asyncio
import aiohttp
from datetime import datetime

from dotenv import load_dotenv
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from news.digest_handler import DigestHandler
from shared.notion_handler import NotionHandler

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Config
BOT_TOKEN = os.getenv("NEWS_BOT_TOKEN")
USER_ID = os.getenv("NEWS_USER_ID", "")
TIMEZONE = os.getenv("TIMEZONE", "Europe/London")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")
NOTION_KEY = os.getenv("NOTION_API_KEY")
CONFIG_DB_ID = os.getenv("CONFIG_DB_ID")
GITHUB_TOKEN = os.getenv("OBSIDIAN_GITHUB_TOKEN")

# GitHub config backup path
GITHUB_API = "https://api.github.com"
GITHUB_REPO = "NotebookOfCCC/Obsidian"
GITHUB_CONFIG_PATH = "98. 数据库/02. Bot Config/.news_bot_config.json"

CONFIG_KEY = "__CONFIG_news_settings__"

REPLY_KEYBOARD = ReplyKeyboardMarkup(
    [["Digest", "Settings"]],
    resize_keyboard=True,
    is_persistent=True,
)

LANGUAGE_LABELS = {"zh": "中文", "en": "English", "bilingual": "双语"}

# Global state
notion_handler = None
digest_handler = None
scheduler = None
application = None
is_paused = False
news_config = None


def get_default_config() -> dict:
    return {
        "push_hour": 9,
        "push_minute": 0,
        "language": "zh",
        "is_paused": False,
    }


def load_config() -> dict:
    """Load config from Notion, falling back to defaults."""
    default = get_default_config()
    if not notion_handler:
        return default
    try:
        config = notion_handler.load_bot_config(CONFIG_KEY)
        if config:
            return {**default, **config}
    except Exception as e:
        logger.error(f"Error loading config: {e}")
    return default


def save_config(config: dict) -> bool:
    """Save config to Notion (primary). Returns True if successful."""
    if not notion_handler:
        return False
    try:
        result = notion_handler.save_bot_config(CONFIG_KEY, config)
        logger.info(f"Config saved to Notion: {config}")
        return result if result is not None else True
    except Exception as e:
        logger.error(f"Failed to save config to Notion: {e}")
        return False


async def save_config_to_github(config: dict) -> bool:
    """Best-effort backup config to GitHub."""
    if not GITHUB_TOKEN:
        return False
    try:
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
        }
        url = f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{GITHUB_CONFIG_PATH}"
        content_json = json.dumps(config, indent=2, ensure_ascii=False) + "\n"
        import base64
        encoded = base64.b64encode(content_json.encode()).decode()

        async with aiohttp.ClientSession() as session:
            # Check if file exists (get SHA)
            sha = None
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    sha = data.get("sha")

            # Create or update
            payload = {
                "message": f"news-bot config: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                "content": encoded,
            }
            if sha:
                payload["sha"] = sha

            async with session.put(url, headers=headers, json=payload) as resp:
                if resp.status in (200, 201):
                    logger.info("Config backed up to GitHub")
                    return True
                else:
                    logger.warning(f"GitHub config backup failed: {resp.status}")
                    return False
    except Exception as e:
        logger.error(f"GitHub config backup error: {e}")
        return False


async def dual_save_config(config: dict) -> bool:
    """Save to Notion (primary) + GitHub (backup). Returns Notion save result."""
    saved = save_config(config)
    # GitHub backup is best-effort, don't block on it
    asyncio.create_task(save_config_to_github(config))
    return saved


def is_authorized(update: Update) -> bool:
    return str(update.effective_user.id) == USER_ID


def _format_settings_text() -> str:
    hour = news_config.get("push_hour", 9)
    minute = news_config.get("push_minute", 0)
    lang = news_config.get("language", "zh")
    paused = news_config.get("is_paused", False)
    return (
        f"📰 News Digest Settings\n\n"
        f"Push time: {hour:02d}:{minute:02d}\n"
        f"Language: {LANGUAGE_LABELS.get(lang, lang)}\n"
        f"Status: {'⏸ Paused' if paused else '▶️ Active'}"
    )


# ── Commands ──────────────────────────────────────────────────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Sorry, this bot is private.")
        return
    await update.message.reply_text(
        "📰 News Digest Bot\n\n"
        "Daily AI builder digests from top researchers, founders, and engineers.\n\n"
        "Commands:\n"
        "/digest — Get today's digest now\n"
        "/settings — Configure time & language\n"
        "/stop — Pause daily pushes\n"
        "/resume — Resume daily pushes\n"
        "/status — Show current settings",
        reply_markup=REPLY_KEYBOARD,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    await update.message.reply_text(
        "📰 Commands:\n"
        "/digest — Get today's digest\n"
        "/settings — Configure push time & language\n"
        "/stop — Pause daily pushes\n"
        "/resume — Resume daily pushes\n"
        "/status — Current settings\n\n"
        "Reply keyboard:\n"
        "[Digest] — Same as /digest\n"
        "[Settings] — Same as /settings",
        reply_markup=REPLY_KEYBOARD,
    )


async def digest_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual trigger — generate and send digest now."""
    if not is_authorized(update):
        return

    await update.message.reply_text("📰 Generating digest...")

    language = news_config.get("language", "zh")
    digest = await digest_handler.generate_digest(language=language)

    if digest:
        # Split long messages (Telegram limit ~4096 chars)
        if len(digest) <= 4096:
            await update.message.reply_text(digest, reply_markup=REPLY_KEYBOARD)
        else:
            for i in range(0, len(digest), 4096):
                chunk = digest[i:i + 4096]
                await update.message.reply_text(chunk)
            # Reattach keyboard on last chunk
            await update.message.reply_text("—", reply_markup=REPLY_KEYBOARD)
    else:
        await update.message.reply_text(
            "No new content available today. Try again later!",
            reply_markup=REPLY_KEYBOARD,
        )


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_paused
    if not is_authorized(update):
        return

    is_paused = True
    news_config["is_paused"] = True
    saved = await dual_save_config(news_config)

    if saved:
        await update.message.reply_text("⏸ Daily digest paused (saved). Use /resume to continue.")
    else:
        await update.message.reply_text("⏸ Paused for this session.\n⚠️ Config save failed — may not survive restart.")
    logger.info(f"News digest paused (persisted={saved})")


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global is_paused
    if not is_authorized(update):
        return

    is_paused = False
    news_config["is_paused"] = False
    saved = await dual_save_config(news_config)

    if saved:
        await update.message.reply_text("▶️ Daily digest resumed!")
    else:
        await update.message.reply_text("▶️ Resumed for this session.\n⚠️ Config save failed — may revert after restart.")
    logger.info(f"News digest resumed (persisted={saved})")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    status = "paused" if is_paused else "active"
    jobs = scheduler.get_jobs() if scheduler else []
    await update.message.reply_text(
        f"📰 News Digest Bot Status\n\n"
        f"Status: {status}\n"
        f"Timezone: {TIMEZONE}\n"
        f"Push time: {news_config.get('push_hour', 9):02d}:{news_config.get('push_minute', 0):02d}\n"
        f"Language: {LANGUAGE_LABELS.get(news_config.get('language', 'zh'), 'zh')}\n"
        f"Scheduled jobs: {len(jobs)}\n\n"
        f"Commands: /digest /settings /stop /resume",
        reply_markup=REPLY_KEYBOARD,
    )


# ── Settings UI (inline buttons) ──────────────────────────────────────

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    await send_settings_display(update.message)


async def send_settings_display(message_or_query, edit: bool = False):
    text = _format_settings_text()
    keyboard = [
        [
            InlineKeyboardButton("Edit Time", callback_data="nsched_edit_time"),
            InlineKeyboardButton("Edit Language", callback_data="nsched_edit_lang"),
        ],
    ]
    markup = InlineKeyboardMarkup(keyboard)
    if edit:
        await message_or_query.edit_message_text(text=text, reply_markup=markup)
    else:
        await message_or_query.reply_text(text, reply_markup=markup)


def _build_hour_grid() -> InlineKeyboardMarkup:
    current_hour = news_config.get("push_hour", 9)
    rows = []
    for row_hours in [(7, 8, 9, 10, 11, 12), (13, 14, 15, 16, 17, 18), (19, 20, 21, 22, 23)]:
        row = []
        for h in row_hours:
            label = f"✅ {h:02d}" if h == current_hour else f"{h:02d}"
            row.append(InlineKeyboardButton(label, callback_data=f"nsched_hour_{h}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("Back", callback_data="nsched_back")])
    return InlineKeyboardMarkup(rows)


def _build_minute_grid(hour: int) -> InlineKeyboardMarkup:
    current_hour = news_config.get("push_hour", 9)
    current_min = news_config.get("push_minute", 0)
    options = [0, 15, 30, 45]
    row = []
    for m in options:
        label = f"✅ {hour:02d}:{m:02d}" if (hour == current_hour and m == current_min) else f"{hour:02d}:{m:02d}"
        row.append(InlineKeyboardButton(label, callback_data=f"nsched_min_{hour}_{m}"))
    return InlineKeyboardMarkup([row, [InlineKeyboardButton("Back", callback_data="nsched_edit_time")]])


def _build_language_options() -> InlineKeyboardMarkup:
    current = news_config.get("language", "zh")
    options = [("zh", "中文"), ("en", "English"), ("bilingual", "双语")]
    row = []
    for code, label in options:
        display = f"✅ {label}" if code == current else label
        row.append(InlineKeyboardButton(display, callback_data=f"nsched_lang_{code}"))
    return InlineKeyboardMarkup([row, [InlineKeyboardButton("Back", callback_data="nsched_back")]])


async def handle_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global news_config
    query = update.callback_query

    if str(query.from_user.id) != USER_ID:
        await query.answer()
        return

    data = query.data

    if data == "nsched_edit_time":
        await query.answer("Tap an hour, then pick minutes", show_alert=True)
        await query.edit_message_text(
            text="Select push hour:",
            reply_markup=_build_hour_grid(),
        )

    elif data.startswith("nsched_hour_"):
        await query.answer()
        hour = int(data.split("_")[-1])
        await query.edit_message_text(
            text=f"Selected {hour:02d}:xx — pick minutes:",
            reply_markup=_build_minute_grid(hour),
        )

    elif data.startswith("nsched_min_"):
        await query.answer()
        parts = data.split("_")
        hour, minute = int(parts[2]), int(parts[3])
        news_config["push_hour"] = hour
        news_config["push_minute"] = minute
        _apply_schedule()
        await dual_save_config(news_config)
        await send_settings_display(query, edit=True)

    elif data == "nsched_edit_lang":
        await query.answer()
        await query.edit_message_text(
            text="Select language:",
            reply_markup=_build_language_options(),
        )

    elif data.startswith("nsched_lang_"):
        await query.answer()
        lang = data.split("_")[-1]
        news_config["language"] = lang
        await dual_save_config(news_config)
        await send_settings_display(query, edit=True)

    elif data == "nsched_back":
        await query.answer()
        await send_settings_display(query, edit=True)


# ── Reply keyboard handler ───────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    text = update.message.text.strip()
    if text == "Digest":
        await digest_command(update, context)
    elif text == "Settings":
        await settings_command(update, context)


# ── Scheduled digest ─────────────────────────────────────────────────

async def send_daily_digest():
    """Scheduled job — send digest if not paused."""
    if is_paused:
        logger.info("News digest paused, skipping")
        return

    if not USER_ID:
        logger.error("NEWS_USER_ID not configured")
        return

    try:
        language = news_config.get("language", "zh")
        digest = await digest_handler.generate_digest(language=language)

        if digest:
            if len(digest) <= 4096:
                await application.bot.send_message(
                    chat_id=USER_ID,
                    text=digest,
                    reply_markup=REPLY_KEYBOARD,
                )
            else:
                for i in range(0, len(digest), 4096):
                    chunk = digest[i:i + 4096]
                    await application.bot.send_message(chat_id=USER_ID, text=chunk)
            logger.info("Sent daily digest")
        else:
            logger.info("No new content for daily digest, skipping")

    except Exception as e:
        logger.error(f"Error sending daily digest: {e}")


def _apply_schedule():
    """Update the scheduler job to match current config."""
    if not scheduler:
        return
    tz = pytz.timezone(TIMEZONE)
    hour = news_config.get("push_hour", 9)
    minute = news_config.get("push_minute", 0)

    # Remove existing job if any
    try:
        scheduler.remove_job("daily_digest")
    except Exception:
        pass

    scheduler.add_job(
        send_daily_digest,
        CronTrigger(hour=hour, minute=minute, timezone=tz),
        id="daily_digest",
        replace_existing=True,
    )
    logger.info(f"Digest scheduled at {hour:02d}:{minute:02d} {TIMEZONE}")


# ── Startup ──────────────────────────────────────────────────────────

async def post_init(app: Application):
    """Called after application is initialized."""
    global scheduler
    scheduler = AsyncIOScheduler()
    _apply_schedule()
    scheduler.start()
    logger.info("News bot scheduler started")


def main():
    global notion_handler, digest_handler, application, news_config, is_paused

    if not BOT_TOKEN:
        print("ERROR: NEWS_BOT_TOKEN not set")
        return
    if not USER_ID:
        print("ERROR: NEWS_USER_ID not set")
        return
    if not ANTHROPIC_KEY:
        print("ERROR: ANTHROPIC_API_KEY not set")
        return

    # Initialize handlers
    digest_handler = DigestHandler(ANTHROPIC_KEY)

    if NOTION_KEY and CONFIG_DB_ID:
        notion_handler = NotionHandler(NOTION_KEY, CONFIG_DB_ID)
        print("Notion config handler initialized")
    else:
        print("WARNING: CONFIG_DB_ID not set — config won't persist")

    # Load config
    news_config = load_config()
    is_paused = news_config.get("is_paused", False)
    print(f"Config loaded: time={news_config['push_hour']:02d}:{news_config['push_minute']:02d}, "
          f"language={news_config['language']}, paused={is_paused}")

    # Create application
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("digest", digest_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("resume", resume_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CallbackQueryHandler(handle_settings_callback, pattern=r"^nsched_"))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r"^(Digest|Settings)$"),
        handle_text,
    ))

    print(f"News Digest bot starting... (push at {news_config['push_hour']:02d}:{news_config['push_minute']:02d})")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
