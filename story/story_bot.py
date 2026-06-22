"""
Story Bot

Telegram bot for capturing fleeting thoughts and daily reflections.
- Send text -> saved to Obsidian via GitHub API with timestamp
- Delete button to remove last entry
- /today to view all entries for today
- Files stored at: 01. Daily Reflection/99. Story Bot/YYYY-MM-DD.md
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import base64
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
import pytz

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Config
BOT_TOKEN = os.getenv("STORY_BOT_TOKEN")
USER_ID = os.getenv("STORY_USER_ID", "")
TIMEZONE = os.getenv("TIMEZONE", "Europe/London")
GITHUB_TOKEN = os.getenv("OBSIDIAN_GITHUB_TOKEN")

GITHUB_API = "https://api.github.com"
REPO = "NotebookOfCCC/Obsidian"
BASE_PATH = "01. Daily Reflection/99. Story Bot"

REPLY_KEYBOARD = ReplyKeyboardMarkup(
    [["Today"]],
    resize_keyboard=True,
    is_persistent=True,
)

# SHA cache for GitHub conflict resolution
_sha_cache = {}


def is_authorized(update: Update) -> bool:
    return str(update.effective_user.id) == USER_ID


def _now() -> datetime:
    tz = pytz.timezone(TIMEZONE)
    return datetime.now(tz)


def _today_filepath() -> str:
    today = _now().strftime("%Y-%m-%d")
    month = _now().strftime("%Y-%m")
    return f"{BASE_PATH}/{month}/{today}.md"


# -- GitHub operations --

async def _github_get(filepath: str) -> tuple[str, str]:
    """Fetch file content and SHA. Returns (content, sha)."""
    url = f"{GITHUB_API}/repos/{REPO}/contents/{filepath}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status == 404:
                return None, None
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"GitHub GET {resp.status}: {text}")
            data = await resp.json()
            content = base64.b64decode(data["content"]).decode("utf-8")
            sha = data["sha"]
            _sha_cache[filepath] = sha
            return content, sha


async def _github_put(filepath: str, content: str, message: str):
    """Write file to GitHub. Creates or updates."""
    url = f"{GITHUB_API}/repos/{REPO}/contents/{filepath}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    sha = _sha_cache.get(filepath)
    if not sha:
        _, sha = await _github_get(filepath)

    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    payload = {"message": message, "content": encoded}
    if sha:
        payload["sha"] = sha

    for attempt in range(3):
        async with aiohttp.ClientSession() as session:
            async with session.put(url, headers=headers, json=payload) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    _sha_cache[filepath] = data["content"]["sha"]
                    return
                elif resp.status == 409 and attempt < 2:
                    logger.warning(f"Conflict on {filepath}, retrying")
                    _sha_cache.pop(filepath, None)
                    _, sha = await _github_get(filepath)
                    payload["sha"] = sha
                    continue
                else:
                    text = await resp.text()
                    raise Exception(f"GitHub PUT {resp.status}: {text}")


async def _append_entry(text: str) -> str:
    """Append a timestamped entry to today's file. Returns the timestamp used."""
    filepath = _today_filepath()
    now = _now()
    timestamp = now.strftime("%H:%M")
    today_str = now.strftime("%Y-%m-%d")

    existing, _ = await _github_get(filepath)

    if existing:
        new_content = existing.rstrip("\n") + f"\n\n### {timestamp}\n{text}\n"
    else:
        new_content = f"# {today_str}\n\n### {timestamp}\n{text}\n"

    await _github_put(filepath, new_content, f"story: {today_str} {timestamp}")
    return timestamp


async def _delete_entry(timestamp: str) -> bool:
    """Delete a specific entry by timestamp from today's file."""
    filepath = _today_filepath()
    content, _ = await _github_get(filepath)
    if not content:
        return False

    lines = content.split("\n")
    new_lines = []
    skip = False
    found = False

    for line in lines:
        if line.strip() == f"### {timestamp}":
            skip = True
            found = True
            # Remove trailing blank line before this entry
            while new_lines and new_lines[-1].strip() == "":
                new_lines.pop()
            continue
        if skip and line.startswith("### "):
            skip = False
        if not skip:
            new_lines.append(line)

    if not found:
        return False

    new_content = "\n".join(new_lines).rstrip("\n") + "\n"
    today_str = _now().strftime("%Y-%m-%d")
    await _github_put(filepath, new_content, f"story: delete {timestamp} on {today_str}")
    return True


async def _get_today_entries() -> str | None:
    """Get today's file content."""
    filepath = _today_filepath()
    content, _ = await _github_get(filepath)
    return content


# -- Handlers --

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        await update.message.reply_text("Sorry, this bot is private.")
        return
    await update.message.reply_text(
        "Story Bot\n\n"
        "Send me any text and I'll save it to Obsidian with a timestamp.\n\n"
        "Commands:\n"
        "/today - View today's entries\n"
        "/help - Show this message",
        reply_markup=REPLY_KEYBOARD,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    await start_command(update, context)


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    content = await _get_today_entries()
    if content:
        await update.message.reply_text(content, reply_markup=REPLY_KEYBOARD)
    else:
        await update.message.reply_text("No entries today.", reply_markup=REPLY_KEYBOARD)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save any text message as a story entry."""
    if not is_authorized(update):
        return

    text = update.message.text.strip()
    if text in ("Today",):
        await today_command(update, context)
        return

    try:
        timestamp = await _append_entry(text)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Delete", callback_data=f"sdel_{timestamp}")]
        ])
        await update.message.reply_text(
            f"Saved ({timestamp})",
            reply_markup=keyboard,
        )
    except Exception as e:
        logger.error(f"Failed to save entry: {e}")
        await update.message.reply_text(f"Failed to save: {e}")


async def handle_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if str(query.from_user.id) != USER_ID:
        await query.answer()
        return

    data = query.data
    if not data.startswith("sdel_"):
        await query.answer()
        return

    timestamp = data[5:]  # e.g. "14:30"

    try:
        deleted = await _delete_entry(timestamp)
        if deleted:
            await query.edit_message_text("Deleted")
        else:
            await query.answer("Entry not found", show_alert=True)
    except Exception as e:
        logger.error(f"Failed to delete entry: {e}")
        await query.answer(f"Delete failed: {e}", show_alert=True)


# -- Main --

def main():
    if not BOT_TOKEN:
        print("ERROR: STORY_BOT_TOKEN not set")
        return
    if not USER_ID:
        print("ERROR: STORY_USER_ID not set")
        return
    if not GITHUB_TOKEN:
        print("ERROR: OBSIDIAN_GITHUB_TOKEN not set")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("today", today_command))
    application.add_handler(CallbackQueryHandler(handle_delete_callback, pattern=r"^sdel_"))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_text,
    ))

    print(f"Story bot starting... (saving to {BASE_PATH}/)")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
