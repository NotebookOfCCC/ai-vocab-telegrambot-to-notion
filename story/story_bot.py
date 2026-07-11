"""
Story Bot

Telegram bot for capturing fleeting thoughts and daily reflections.
- Send text -> saved to Obsidian via GitHub API with timestamp
- Delete button to remove last entry
- /today to view all entries for today
- Monthly files: 01. Daily Reflection/100. Story Bot/YYYY-MM.md
- Format: ## date headers > ### time sub-headers > story text + Revised + Notes
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import base64
import io
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

from story.ai_handler import StoryAIHandler

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
STORY_DIR = "01. Daily Reflection/100. Story Bot"


def _filepath_for(dt: datetime = None) -> str:
    """Return the file path for a given month (defaults to current month)."""
    if dt is None:
        dt = _now()
    return f"{STORY_DIR}/{dt.strftime('%Y-%m')}.md"

REPLY_KEYBOARD = ReplyKeyboardMarkup(
    [["Today"]],
    resize_keyboard=True,
    is_persistent=True,
)

# AI handler for text revision
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
_ai_handler = None
if ANTHROPIC_API_KEY:
    _ai_handler = StoryAIHandler(ANTHROPIC_API_KEY, OPENAI_API_KEY)
else:
    logger.warning("ANTHROPIC_API_KEY not set - Story AI revision disabled")

# SHA cache for GitHub conflict resolution
_sha_cache = {}


def is_authorized(update: Update) -> bool:
    return str(update.effective_user.id) == USER_ID


def _now() -> datetime:
    tz = pytz.timezone(TIMEZONE)
    return datetime.now(tz)


# -- GitHub operations --

async def _github_get(filepath: str) -> tuple[str | None, str | None]:
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
    """Append a timestamped entry to today's section. Returns (timestamp, today_str)."""
    now = _now()
    timestamp = now.strftime("%H:%M")
    today_str = now.strftime("%Y-%m-%d")
    filepath = _filepath_for(now)
    date_header = f"## {today_str}"
    time_header = f"### {timestamp}"
    new_entry = f"{time_header}\n{text}\n"

    existing, _ = await _github_get(filepath)

    if not existing:
        month_label = now.strftime("%Y-%m")
        content = f"# Story Bot - {month_label}\n\n{date_header}\n\n{new_entry}"
    elif date_header in existing:
        # Today's section exists — append entry at end of today's section
        lines = existing.split("\n")
        insert_idx = len(lines)
        in_today = False
        for i, line in enumerate(lines):
            if line.strip() == date_header:
                in_today = True
            elif in_today and line.startswith("## "):
                insert_idx = i
                break
        # Remove trailing empty lines before insert point
        while insert_idx > 0 and lines[insert_idx - 1].strip() == "":
            insert_idx -= 1
        # Add separator between entries
        lines.insert(insert_idx, f"\n---\n\n{new_entry}")
        content = "\n".join(lines)
        if not content.endswith("\n"):
            content += "\n"
    else:
        # New day — add section at the top (after # Story Bot - YYYY-MM header)
        lines = existing.split("\n")
        insert_idx = 1
        while insert_idx < len(lines) and lines[insert_idx].strip() == "":
            insert_idx += 1
        lines.insert(insert_idx, f"\n{date_header}\n\n{new_entry}")
        content = "\n".join(lines)
        if not content.endswith("\n"):
            content += "\n"

    await _github_put(filepath, content, f"story: {today_str} {timestamp}")
    return timestamp, today_str


async def _update_entry_revision(date_str: str, timestamp: str, revised: str, notes: str, phrases: list = None):
    """Add Revised, Notes, and Key Phrases under an existing entry's ### HH:MM section."""
    month_str = date_str[:7]
    filepath = f"{STORY_DIR}/{month_str}.md"
    content, _ = await _github_get(filepath)
    if not content:
        return

    time_header = f"### {timestamp}"
    if time_header not in content:
        return

    revision_block = f"\n**Revised:** {revised}\n\n**Notes:**\n{notes}\n"
    if phrases:
        phrases_text = "\n".join(f"- **{p['phrase']}** — {p['note']}" for p in phrases)
        revision_block += f"\n**Key Phrases:**\n{phrases_text}\n"

    lines = content.split("\n")
    in_target = False
    insert_idx = None
    for i, line in enumerate(lines):
        if line.strip() == time_header:
            in_target = True
        elif in_target and (line.startswith("### ") or line.startswith("## ") or line.strip() == "---"):
            insert_idx = i
            break
    if insert_idx is None and in_target:
        insert_idx = len(lines)

    if insert_idx is None:
        return

    # Remove trailing blank lines before insert
    while insert_idx > 0 and lines[insert_idx - 1].strip() == "":
        insert_idx -= 1

    lines.insert(insert_idx, revision_block)
    new_content = "\n".join(lines)
    if not new_content.endswith("\n"):
        new_content += "\n"
    await _github_put(filepath, new_content, f"story: revision {date_str} {timestamp}")


async def _delete_entry(date_str: str, timestamp: str) -> bool:
    """Delete a specific entry (### HH:MM section) by date and timestamp."""
    month_str = date_str[:7]
    filepath = f"{STORY_DIR}/{month_str}.md"
    content, _ = await _github_get(filepath)
    if not content:
        return False

    time_header = f"### {timestamp}"
    date_header = f"## {date_str}"
    if time_header not in content or date_header not in content:
        return False

    lines = content.split("\n")
    # Find the ### HH:MM section boundaries
    section_start = None
    section_end = None
    in_date = False
    for i, line in enumerate(lines):
        if line.strip() == date_header:
            in_date = True
        elif in_date and line.strip() == time_header:
            # Include preceding --- separator if present
            start = i
            while start > 0 and lines[start - 1].strip() in ("", "---"):
                start -= 1
            # But don't go past the date header
            if start >= 0 and lines[start].strip() == date_header:
                start = i
            section_start = start
        elif section_start is not None and (line.startswith("### ") or line.startswith("## ") or line.strip() == "---"):
            section_end = i
            break

    if section_start is None:
        return False
    if section_end is None:
        section_end = len(lines)

    del lines[section_start:section_end]

    # Check if date section is now empty (no ### entries left)
    has_entries = False
    in_date = False
    date_start = None
    date_end = None
    for i, line in enumerate(lines):
        if line.strip() == date_header:
            in_date = True
            date_start = i
        elif in_date and line.startswith("## "):
            date_end = i
            break
        elif in_date and line.startswith("### "):
            has_entries = True

    if not has_entries and date_start is not None:
        if date_end is None:
            date_end = len(lines)
        while date_start > 0 and lines[date_start - 1].strip() == "":
            date_start -= 1
        del lines[date_start:date_end]

    new_content = "\n".join(lines)
    if not new_content.endswith("\n"):
        new_content += "\n"

    await _github_put(filepath, new_content, f"story: delete {timestamp} on {date_str}")
    return True


async def _get_today_entries() -> str | None:
    """Get today's entries as readable text."""
    filepath = _filepath_for()
    content, _ = await _github_get(filepath)
    if not content:
        return None

    today_str = _now().strftime("%Y-%m-%d")
    date_header = f"## {today_str}"

    if date_header not in content:
        return None

    lines = content.split("\n")
    in_today = False
    entries = []
    current_entry = None

    for line in lines:
        if line.strip() == date_header:
            in_today = True
            continue
        if in_today and line.startswith("## "):
            break
        if not in_today:
            continue

        time_match = re.match(r"^### (\d{2}:\d{2})$", line.strip())
        if time_match:
            if current_entry:
                entries.append(current_entry)
            current_entry = {"time": time_match.group(1), "lines": []}
        elif current_entry is not None and line.strip() not in ("---", ""):
            current_entry["lines"].append(line)

    if current_entry:
        entries.append(current_entry)

    if not entries:
        return None

    result_parts = []
    for entry in entries:
        text = "\n".join(entry["lines"])
        result_parts.append(f"{entry['time']}\n{text}")

    return f"Today ({today_str}):\n\n" + "\n\n---\n\n".join(result_parts)


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
    """Save any text message as a story entry, then revise with AI."""
    if not is_authorized(update):
        return

    text = update.message.text.strip()
    if text in ("Today",):
        await today_command(update, context)
        return

    try:
        timestamp, today_str = await _append_entry(text)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Delete", callback_data=f"sdel_{today_str}_{timestamp}")]
        ])
        await update.message.reply_text(
            f"Saved ({timestamp})",
            reply_markup=keyboard,
        )

        # Call AI in background for revision
        if _ai_handler:
            context.application.create_task(
                _revise_and_reply(update, text, today_str, timestamp),
                update=update,
            )

    except Exception as e:
        logger.error(f"Failed to save entry: {e}")
        await update.message.reply_text(f"Failed to save: {e}")


async def _revise_and_reply(update: Update, text: str, date_str: str, timestamp: str):
    """Background task: call AI for revision, send result, update file."""
    try:
        result = await _ai_handler.revise_text(text)
        revised = result.get("revised")
        notes = result.get("notes")

        if revised and notes:
            phrases = result.get("phrases", [])
            msg = f"✍️ Revised:\n{revised}\n\n📝 Notes:\n{notes}"
            if phrases:
                phrases_text = "\n".join(f"• {p['phrase']} — {p['note']}" for p in phrases[:5])
                msg += f"\n\n🔑 Key Phrases:\n{phrases_text}"
            await update.message.reply_text(msg, reply_markup=REPLY_KEYBOARD)
            await _update_entry_revision(date_str, timestamp, revised, notes, phrases)

            # Send voice message for revised text
            audio_buf = await _generate_tts(revised)
            if audio_buf:
                await update.message.reply_voice(voice=audio_buf, reply_markup=REPLY_KEYBOARD)
        else:
            logger.warning(f"AI revision returned empty: revised={revised is not None}, notes={notes is not None}")
            await update.message.reply_text(
                "AI revision unavailable.",
                reply_markup=REPLY_KEYBOARD,
            )
    except Exception as e:
        logger.error(f"AI revision failed: {e}", exc_info=True)
        try:
            await update.message.reply_text(
                "AI revision unavailable.",
                reply_markup=REPLY_KEYBOARD,
            )
        except Exception:
            pass  # Message might be too old to reply to


async def _generate_tts(text: str) -> io.BytesIO | None:
    """Generate TTS audio for text using edge-tts. Returns BytesIO buffer or None."""
    try:
        import edge_tts
    except ImportError:
        logger.warning("edge-tts not installed, skipping voice")
        return None

    try:
        buf = io.BytesIO()
        async for chunk in edge_tts.Communicate(text, "en-GB-SoniaNeural").stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        if buf.getbuffer().nbytes > 0:
            buf.seek(0)
            return buf
        return None
    except Exception as e:
        logger.error(f"TTS error: {e}")
        return None


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

    print(f"Story bot starting... (saving to {STORY_DIR}/YYYY-MM.md)")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
