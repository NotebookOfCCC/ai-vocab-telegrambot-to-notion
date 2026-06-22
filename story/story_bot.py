"""
Story Bot

Telegram bot for capturing fleeting thoughts and daily reflections.
- Send text -> saved to Obsidian via GitHub API with timestamp
- Delete button to remove last entry
- /today to view all entries for today
- Single file: 01. Daily Reflection/99. Story Bot.md
- Format: date headers with table rows (| Time | Story |)
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import base64
import re
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
FILEPATH = "01. Daily Reflection/99. Story Bot.md"

TABLE_HEADER = "| Time | Story |\n|------|-------|"

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


# -- GitHub operations --

async def _github_get() -> tuple[str | None, str | None]:
    """Fetch file content and SHA. Returns (content, sha)."""
    url = f"{GITHUB_API}/repos/{REPO}/contents/{FILEPATH}"
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
            _sha_cache[FILEPATH] = sha
            return content, sha


async def _github_put(content: str, message: str):
    """Write file to GitHub. Creates or updates."""
    url = f"{GITHUB_API}/repos/{REPO}/contents/{FILEPATH}"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }
    sha = _sha_cache.get(FILEPATH)
    if not sha:
        _, sha = await _github_get()

    encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")
    payload = {"message": message, "content": encoded}
    if sha:
        payload["sha"] = sha

    for attempt in range(3):
        async with aiohttp.ClientSession() as session:
            async with session.put(url, headers=headers, json=payload) as resp:
                if resp.status in (200, 201):
                    data = await resp.json()
                    _sha_cache[FILEPATH] = data["content"]["sha"]
                    return
                elif resp.status == 409 and attempt < 2:
                    logger.warning(f"Conflict on {FILEPATH}, retrying")
                    _sha_cache.pop(FILEPATH, None)
                    _, sha = await _github_get()
                    payload["sha"] = sha
                    continue
                else:
                    text = await resp.text()
                    raise Exception(f"GitHub PUT {resp.status}: {text}")


def _escape_pipe(text: str) -> str:
    """Escape pipe characters in text for markdown table cells."""
    return text.replace("|", "\\|")


async def _append_entry(text: str) -> str:
    """Append a timestamped entry to today's section. Returns the timestamp."""
    now = _now()
    timestamp = now.strftime("%H:%M")
    today_str = now.strftime("%Y-%m-%d")
    date_header = f"## {today_str}"
    escaped_text = _escape_pipe(text)
    new_row = f"| {timestamp} | {escaped_text} |"

    existing, _ = await _github_get()

    if not existing:
        # Brand new file
        content = f"# Story Bot\n\n{date_header}\n\n{TABLE_HEADER}\n{new_row}\n"
    elif date_header in existing:
        # Today's section exists — append row after last table row in that section
        lines = existing.split("\n")
        insert_idx = None
        in_today = False
        for i, line in enumerate(lines):
            if line.strip() == date_header:
                in_today = True
            elif in_today and line.startswith("## "):
                # Hit next date section
                insert_idx = i
                break
            elif in_today and line.startswith("| ") and not line.startswith("|---"):
                insert_idx = i + 1
        if insert_idx is None:
            insert_idx = len(lines)
        # Remove trailing empty lines before insert point
        while insert_idx > 0 and lines[insert_idx - 1].strip() == "":
            insert_idx -= 1
            # Keep the empty line but insert before next section
            if insert_idx < len(lines) and lines[insert_idx].startswith("## "):
                break
        lines.insert(insert_idx, new_row)
        content = "\n".join(lines)
        if not content.endswith("\n"):
            content += "\n"
    else:
        # New day — add section at the top (after # Story Bot header)
        lines = existing.split("\n")
        insert_idx = 1  # After "# Story Bot"
        # Skip blank lines after header
        while insert_idx < len(lines) and lines[insert_idx].strip() == "":
            insert_idx += 1
        new_section = f"\n{date_header}\n\n{TABLE_HEADER}\n{new_row}\n"
        lines.insert(insert_idx, new_section)
        content = "\n".join(lines)
        if not content.endswith("\n"):
            content += "\n"

    await _github_put(content, f"story: {today_str} {timestamp}")
    return timestamp


async def _delete_entry(date_str: str, timestamp: str) -> bool:
    """Delete a specific entry by date and timestamp."""
    content, _ = await _github_get()
    if not content:
        return False

    date_header = f"## {date_str}"
    if date_header not in content:
        return False

    lines = content.split("\n")
    found = False
    in_target_date = False
    remove_idx = None

    for i, line in enumerate(lines):
        if line.strip() == date_header:
            in_target_date = True
        elif in_target_date and line.startswith("## "):
            break
        elif in_target_date and line.startswith(f"| {timestamp} |"):
            remove_idx = i
            found = True
            break

    if not found:
        return False

    lines.pop(remove_idx)

    # Check if this date section is now empty (only header + table header left)
    in_target_date = False
    has_data_rows = False
    section_start = None
    section_end = None
    for i, line in enumerate(lines):
        if line.strip() == date_header:
            in_target_date = True
            section_start = i
        elif in_target_date and line.startswith("## "):
            section_end = i
            break
        elif in_target_date and line.startswith("| ") and not line.startswith("|---") and line.strip() != TABLE_HEADER.split("\n")[0]:
            has_data_rows = True

    if not has_data_rows and section_start is not None:
        # Remove entire empty section
        if section_end is None:
            section_end = len(lines)
        # Also remove blank line before section
        while section_start > 0 and lines[section_start - 1].strip() == "":
            section_start -= 1
        del lines[section_start:section_end]

    new_content = "\n".join(lines)
    if not new_content.endswith("\n"):
        new_content += "\n"

    await _github_put(new_content, f"story: delete {timestamp} on {date_str}")
    return True


async def _get_today_entries() -> str | None:
    """Get today's entries as readable text."""
    content, _ = await _github_get()
    if not content:
        return None

    today_str = _now().strftime("%Y-%m-%d")
    date_header = f"## {today_str}"

    if date_header not in content:
        return None

    lines = content.split("\n")
    in_today = False
    entries = []
    for line in lines:
        if line.strip() == date_header:
            in_today = True
            continue
        if in_today and line.startswith("## "):
            break
        if in_today and line.startswith("| ") and not line.startswith("|---") and not line.startswith("| Time"):
            # Parse table row: | HH:MM | text |
            match = re.match(r"\|\s*(\S+)\s*\|\s*(.*?)\s*\|$", line)
            if match:
                entries.append(f"{match.group(1)}  {match.group(2)}")

    if not entries:
        return None
    return f"Today ({today_str}):\n\n" + "\n".join(entries)


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
        today_str = _now().strftime("%Y-%m-%d")
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Delete", callback_data=f"sdel_{today_str}_{timestamp}")]
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

    # Format: sdel_YYYY-MM-DD_HH:MM
    parts = data[5:].rsplit("_", 1)
    if len(parts) != 2:
        await query.answer("Invalid data", show_alert=True)
        return
    date_str, timestamp = parts

    try:
        deleted = await _delete_entry(date_str, timestamp)
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

    print(f"Story bot starting... (saving to {FILEPATH})")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
