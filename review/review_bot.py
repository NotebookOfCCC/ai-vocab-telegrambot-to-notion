"""
Vocabulary Review Bot
Sends scheduled vocabulary review messages from Notion database.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import io
import json
import re
import html
import asyncio
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from shared.notion_handler import NotionHandler
from review.review_stats_handler import ReviewStatsHandler
from review.obsidian_review_stats_handler import ObsidianReviewStatsHandler

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
REVIEW_BOT_TOKEN = os.getenv("REVIEW_BOT_TOKEN")
REVIEW_USER_ID = os.getenv("REVIEW_USER_ID")
NOTION_KEY = os.getenv("NOTION_API_KEY")
NOTION_DB_ID = os.getenv("NOTION_DATABASE_ID")
TIMEZONE = os.getenv("TIMEZONE", "Europe/London")
REVIEW_STATS_DB_ID = os.getenv("REVIEW_STATS_DB_ID")
CONFIG_DB_ID = os.getenv("CONFIG_DB_ID")

# Additional database IDs for review (comma-separated)
# Example: ADDITIONAL_DATABASE_IDS=db_id_2,db_id_3
ADDITIONAL_DB_IDS_RAW = os.getenv("ADDITIONAL_DATABASE_IDS", "")
ADDITIONAL_DB_IDS = [db_id.strip() for db_id in ADDITIONAL_DB_IDS_RAW.split(",") if db_id.strip()]

# Schedule configuration from environment variables
# REVIEW_HOURS: comma-separated hours (e.g., "8,13,17,19,22")
# WORDS_PER_BATCH: number of words per review session (e.g., "20")
def get_default_config() -> dict:
    """Get default config from environment variables."""
    hours_str = os.getenv("REVIEW_HOURS", "8,13,17,19,22")
    words_str = os.getenv("WORDS_PER_BATCH", "20")

    try:
        hours = [int(h.strip()) for h in hours_str.split(",") if h.strip()]
        hours = [h for h in hours if 0 <= h <= 23]
        if not hours:
            hours = [8, 13, 17, 19, 22]
    except ValueError:
        hours = [8, 13, 17, 19, 22]

    try:
        words = int(words_str)
        if words < 1 or words > 50:
            words = 20
    except ValueError:
        words = 20

    return {"review_hours": sorted(set(hours)), "words_per_batch": words}


REVIEW_CONFIG_KEY = "__CONFIG_review_schedule__"


def load_config() -> dict:
    """Load review config from central config DB, falling back to env var defaults."""
    default = get_default_config()
    if not config_handler:
        return default
    try:
        config = config_handler.load(REVIEW_CONFIG_KEY)
        if not config:
            return default
        # Validate
        hours = config.get("review_hours")
        words = config.get("words_per_batch")
        if not isinstance(hours, list) or not all(isinstance(h, int) and 0 <= h <= 23 for h in hours):
            hours = default["review_hours"]
        if not isinstance(words, int) or words < 1 or words > 50:
            words = default["words_per_batch"]
        return {
            "review_hours": sorted(set(hours)),
            "words_per_batch": words,
            "is_paused": config.get("is_paused", False),
        }
    except Exception:
        return default


def save_config(config: dict) -> bool:
    """Save review config to central config DB + GitHub backup. Returns True if successful."""
    if config_handler:
        saved = config_handler.save(REVIEW_CONFIG_KEY, config)
        # Best-effort GitHub backup
        from shared.github_config_backup import save_config_to_github
        asyncio.create_task(save_config_to_github(config, ".review_bot_config.json", "review-bot"))
        return saved
    return False


# Global state
notion_handler = None
config_handler = None  # Separate handler for central config DB
scheduler = None
application = None
is_paused = False
review_config = None
stats_handler = None
obsidian_stats_handler = None
sent_but_unrated: dict = {}  # page_id → {"entry": entry, "sent_at": datetime}; accumulates across batches, expires after 2 days

def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Persistent reply keyboard with the two most-used actions."""
    return ReplyKeyboardMarkup(
        [["📖 Review", "📊 Due", "📋 Pending", "📈 Stats"]],
        resize_keyboard=True,
        is_persistent=True,
    )



def _clean_phrase_for_tts(english: str) -> str:
    """Strip /phonetics/ and (pos.) from english field, return clean phrase."""
    return re.split(r'\s+[/(]', english)[0].strip()


async def generate_chunked_audio(entries: list, chunk_size: int = 10) -> list:
    """Generate audio in chunks of chunk_size phrases each.

    Returns list of (audio_buf, caption) tuples, e.g.:
        [(buf, "🔊 1–10"), (buf, "🔊 11–20"), ...]
    Phrases that fail are skipped so the rest still play.
    """
    try:
        import edge_tts
    except ImportError:
        logger.warning("edge-tts not installed, skipping audio")
        return []

    voice = "en-GB-SoniaNeural"
    phrases = [_clean_phrase_for_tts(e.get("english", "")) for e in entries]
    phrases = [p for p in phrases if p]
    if not phrases:
        return []

    results = []
    for chunk_start in range(0, len(phrases), chunk_size):
        chunk = phrases[chunk_start:chunk_start + chunk_size]
        chunk_end = chunk_start + len(chunk)
        label = f"🔊 {chunk_start + 1}–{chunk_end}"

        combined = io.BytesIO()
        for phrase in chunk:
            try:
                buf = io.BytesIO()
                async for audio_chunk in edge_tts.Communicate(phrase, voice).stream():
                    if audio_chunk["type"] == "audio":
                        buf.write(audio_chunk["data"])
                audio = buf.getvalue()
                if audio:
                    combined.write(audio)
                    logger.info(f"TTS OK: '{phrase}' → {len(audio)} bytes")
                else:
                    logger.warning(f"TTS empty for: '{phrase}'")
            except Exception as e:
                logger.error(f"TTS error for '{phrase}': {e}")

        combined.seek(0)
        total_bytes = combined.getbuffer().nbytes
        if total_bytes > 0:
            results.append((combined, label))
            logger.info(f"Chunk '{label}': {total_bytes} bytes for {len(chunk)} phrases")
        else:
            logger.warning(f"Chunk '{label}' produced no audio")

    return results


def format_entry_for_review(entry: dict, index: int, total: int) -> str:
    """Format a flashcard with spoiler-hidden answer (HTML).

    English word is visible; Chinese, explanation, examples are hidden
    behind Telegram's native spoiler tap-to-reveal.
    """
    english = html.escape(entry.get("english", ""))
    chinese = html.escape(entry.get("chinese", ""))
    explanation = html.escape(entry.get("explanation", ""))
    example = html.escape(entry.get("example", ""))
    category = html.escape(entry.get("category", ""))
    review_count = entry.get("review_count", 0) or 0
    last_reviewed = entry.get("last_reviewed")

    if not last_reviewed:
        status = "🆕 New"
    elif review_count <= 3:
        status = f"📖 Review #{review_count + 1}"
    else:
        status = f"✅ Review #{review_count + 1}"

    lines = [f"Review {index}/{total}  •  {status}", "", f"<b>{english}</b>"]

    # Build answer section (hidden behind spoiler)
    answer_lines = []
    if chinese:
        answer_lines.append(chinese)
    if explanation:
        answer_lines.extend(["", f"<b>Explanation:</b>", explanation])
    if example:
        answer_lines.extend(["", f"<b>Example:</b>", example])
    if category:
        answer_lines.extend(["", f"Category: {category}"])

    if answer_lines:
        answer_text = "\n".join(answer_lines)
        lines.extend(["", f"<tg-spoiler>{answer_text}</tg-spoiler>"])

    return "\n".join(lines)


async def send_review_batch(manual: bool = False):
    """Fetch entries using spaced repetition and send review messages.

    Args:
        manual: If True, bypass the pause check (for /review command)
    """
    global is_paused

    import datetime
    now = datetime.datetime.now()
    trigger_type = "manual" if manual else "scheduled"
    logger.info(f"send_review_batch triggered ({trigger_type}) at {now.strftime('%Y-%m-%d %H:%M:%S')}")

    if is_paused and not manual:
        logger.info("Review is paused, skipping scheduled batch")
        return

    if not REVIEW_USER_ID:
        logger.error("REVIEW_USER_ID not configured")
        return

    try:
        # Use smart selection with spaced repetition
        batch_size = review_config["words_per_batch"] if review_config else get_default_config()["words_per_batch"]
        entries = notion_handler.fetch_entries_for_review(batch_size, smart=True)

        if not entries:
            logger.warning("No entries fetched from Notion")
            await application.bot.send_message(
                chat_id=REVIEW_USER_ID,
                text="No vocabulary entries found in the database."
            )
            return

        # Accumulate sent cards; expire entries older than 2 days; never overwrite existing ones
        global sent_but_unrated
        cutoff = now - datetime.timedelta(days=2)
        sent_but_unrated = {pid: v for pid, v in sent_but_unrated.items() if v["sent_at"] >= cutoff}
        for entry in entries:
            pid = entry.get("page_id", "")
            if pid and pid not in sent_but_unrated:
                sent_but_unrated[pid] = {"entry": entry, "sent_at": now}

        total = len(entries)
        for i, entry in enumerate(entries, 1):
            message = format_entry_for_review(entry, i, total)
            page_id = entry.get("page_id", "")

            # Rating buttons shown alongside spoiler-hidden answer
            keyboard = [[
                InlineKeyboardButton("🔴 Again", callback_data=f"again_{page_id}"),
                InlineKeyboardButton("🟡 Good", callback_data=f"good_{page_id}"),
                InlineKeyboardButton("🟢 Easy", callback_data=f"easy_{page_id}"),
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)

            await application.bot.send_message(
                chat_id=REVIEW_USER_ID,
                text=message,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )

        logger.info(f"Sent {total} review entries to user {REVIEW_USER_ID}")

        # Send pronunciation audio in chunks of 10
        audio_chunks = await generate_chunked_audio(entries)
        if audio_chunks:
            for audio_buf, caption in audio_chunks:
                await application.bot.send_audio(
                    chat_id=REVIEW_USER_ID,
                    audio=audio_buf,
                    filename=f"{now.strftime('%Y-%m-%d_%H-%M')}.mp3",
                    caption=caption,
                )
        else:
            logger.warning("Batch audio generation skipped or failed")
            await application.bot.send_message(
                chat_id=REVIEW_USER_ID,
                text="⚠️ Audio generation failed (edge-tts unavailable)",
            )

    except Exception as e:
        logger.error(f"Error sending review batch: {e}")


async def send_pending_resend():
    """Resend all cards sent in the last 2 days that haven't been rated yet."""
    if not REVIEW_USER_ID:
        logger.error("REVIEW_USER_ID not configured")
        return

    if not sent_but_unrated:
        await application.bot.send_message(
            chat_id=REVIEW_USER_ID,
            text="✅ All caught up! No pending cards.",
        )
        return

    entries = [v["entry"] for v in sent_but_unrated.values()]
    total = len(entries)
    logger.info(f"Resending {total} pending cards from last 2 days")

    import datetime
    now = datetime.datetime.now()
    chunk_size = 10

    for chunk_idx, chunk_start in enumerate(range(0, total, chunk_size), 1):
        chunk = entries[chunk_start:chunk_start + chunk_size]

        # Send the cards in this chunk
        for i, entry in enumerate(chunk, chunk_start + 1):
            message = format_entry_for_review(entry, i, total)
            page_id = entry.get("page_id", "")
            keyboard = [[
                InlineKeyboardButton("🔴 Again", callback_data=f"again_{page_id}"),
                InlineKeyboardButton("🟡 Good", callback_data=f"good_{page_id}"),
                InlineKeyboardButton("🟢 Easy", callback_data=f"easy_{page_id}"),
            ]]
            await application.bot.send_message(
                chat_id=REVIEW_USER_ID,
                text=message,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML",
            )

        # Send audio for this chunk immediately after
        audio_chunks = await generate_chunked_audio(chunk)
        if audio_chunks:
            audio_buf, caption = audio_chunks[0]
            filename = f"{now.strftime('%Y-%m-%d_%H-%M')}_part{chunk_idx}.mp3"
            await application.bot.send_audio(
                chat_id=REVIEW_USER_ID,
                audio=audio_buf,
                filename=filename,
                caption=caption,
            )


async def send_weekly_report():
    """Send weekly review report every Sunday."""
    if not stats_handler or not REVIEW_USER_ID:
        return

    from datetime import date, timedelta
    today = date.today()
    # Mon-Sun of the current week (report runs on Sunday)
    start = today - timedelta(days=6)  # Monday
    end = today  # Sunday

    days = stats_handler.get_date_range(start, end)
    total = sum(d["reviewed"] for d in days)
    total_again = sum(d["again"] for d in days)
    total_good = sum(d["good"] for d in days)
    total_easy = sum(d["easy"] for d in days)
    active_days = sum(1 for d in days if d["reviewed"] > 0)
    avg = total / 7 if total else 0

    # Bar chart
    max_val = max(d["reviewed"] for d in days) if days else 1
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    lines = [f"📊 Weekly Review Report"]
    lines.append(f"{start.strftime('%b %d')} – {end.strftime('%b %d')}")
    lines.append("")
    for i, d in enumerate(days):
        bar_len = int(d["reviewed"] / max(max_val, 1) * 10)
        bar = "█" * bar_len
        lines.append(f"{day_names[i]}: {d['reviewed']:>3}  {bar}")
    lines.append("")
    lines.append(f"Total: {total} words | Avg: {avg:.0f}/day")
    lines.append(f"🔴 {total_again} | 🟡 {total_good} | 🟢 {total_easy}")
    lines.append(f"Active: {active_days}/7 days")

    await application.bot.send_message(
        chat_id=REVIEW_USER_ID,
        text="\n".join(lines),
    )


async def send_monthly_report():
    """Send monthly review report on the 1st of each month."""
    if not stats_handler or not REVIEW_USER_ID:
        return

    from datetime import date, timedelta
    today = date.today()
    # Last month
    last_month_end = today - timedelta(days=1)
    last_month_start = last_month_end.replace(day=1)
    num_days = (last_month_end - last_month_start).days + 1

    days = stats_handler.get_date_range(last_month_start, last_month_end)
    total = sum(d["reviewed"] for d in days)
    total_again = sum(d["again"] for d in days)
    total_good = sum(d["good"] for d in days)
    total_easy = sum(d["easy"] for d in days)
    active_days = sum(1 for d in days if d["reviewed"] > 0)
    best = max(days, key=lambda d: d["reviewed"])
    avg = total / num_days if total else 0

    # Previous month for comparison
    prev_month_end = last_month_start - timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)
    prev_days = stats_handler.get_date_range(prev_month_start, prev_month_end)
    prev_total = sum(d["reviewed"] for d in prev_days)

    month_name = last_month_start.strftime("%B %Y")
    lines = [f"📊 Monthly Review Report — {month_name}"]
    lines.append("")
    lines.append(f"Total: {total} words | Avg: {avg:.1f}/day")
    lines.append(f"🔴 Again: {total_again} ({total_again*100//max(total,1)}%)"
                 f" | 🟡 Good: {total_good} ({total_good*100//max(total,1)}%)"
                 f" | 🟢 Easy: {total_easy} ({total_easy*100//max(total,1)}%)")
    lines.append(f"Best day: {best['date']} ({best['reviewed']} words)")
    lines.append(f"Active: {active_days}/{num_days} days")

    if prev_total > 0:
        diff = total - prev_total
        pct = diff * 100 // prev_total
        sign = "+" if diff >= 0 else ""
        lines.append(f"\nvs {prev_month_start.strftime('%B')}: {sign}{diff} words ({sign}{pct}%)")

    await application.bot.send_message(
        chat_id=REVIEW_USER_ID,
        text="\n".join(lines),
    )


async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /myid command - show user's Telegram ID for setup."""
    user_id = update.effective_user.id
    await update.message.reply_text(f"Your Telegram ID: {user_id}\n\nSet this as REVIEW_USER_ID in Railway.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    user_id = str(update.effective_user.id)
    logger.info(f"/start from user {user_id}, expected {REVIEW_USER_ID}")
    if user_id != REVIEW_USER_ID:
        await update.message.reply_text(f"Sorry, this bot is private.\n\nYour ID: {user_id}\nUse /myid to get your ID for setup.")
        return

    info_message = f"""
Vocabulary Review Bot

{format_schedule_text(review_config)}

Commands:
/review - Get review batch now
/due - See pending reviews count
/schedule - View/edit review schedule
/stop - Pause scheduled reviews
/resume - Resume scheduled reviews
/status - Check bot status

Buttons:
🔴 Again - Review tomorrow
🟡 Good - Normal interval
🟢 Easy - Longer interval
"""
    await update.message.reply_text(info_message, reply_markup=get_main_keyboard())


async def review_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /review command - manual trigger (works even when paused)."""
    user_id = str(update.effective_user.id)
    logger.info(f"/review from user {user_id}, expected {REVIEW_USER_ID}")
    if user_id != REVIEW_USER_ID:
        await update.message.reply_text(f"Sorry, this bot is private. Your ID: {user_id}")
        return

    await update.message.reply_text("Fetching review entries...")
    await send_review_batch(manual=True)


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stop command - pause scheduled reviews."""
    global is_paused

    if str(update.effective_user.id) != REVIEW_USER_ID:
        await update.message.reply_text("Sorry, this bot is private.")
        return

    is_paused = True
    # Persist pause state to Notion so it survives restarts
    saved = False
    if review_config is not None:
        review_config["is_paused"] = True
        saved = save_config(review_config)

    if saved:
        await update.message.reply_text("⏸ Scheduled reviews paused (saved). Use /resume to continue.")
    else:
        await update.message.reply_text("⏸ Scheduled reviews paused for this session.\n⚠️ Config save failed — pause may not survive a restart.")
    logger.info(f"Scheduled reviews paused (persisted={saved})")


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /resume command - resume scheduled reviews."""
    global is_paused

    if str(update.effective_user.id) != REVIEW_USER_ID:
        await update.message.reply_text("Sorry, this bot is private.")
        return

    is_paused = False
    # Persist resume state to Notion so it survives restarts
    saved = False
    if review_config is not None:
        review_config["is_paused"] = False
        saved = save_config(review_config)

    if saved:
        await update.message.reply_text("▶️ Scheduled reviews resumed!")
    else:
        await update.message.reply_text("▶️ Scheduled reviews resumed for this session.\n⚠️ Config save failed — may revert after restart.")
    logger.info(f"Scheduled reviews resumed (persisted={saved})")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command - show bot status."""
    if str(update.effective_user.id) != REVIEW_USER_ID:
        await update.message.reply_text("Sorry, this bot is private.")
        return

    status = "paused" if is_paused else "active"
    jobs = scheduler.get_jobs() if scheduler else []

    status_message = f"""
Bot Status: {status}
Timezone: {TIMEZONE}
Scheduled jobs: {len(jobs)}

{format_schedule_text(review_config)}

Review Algorithm: Spaced Repetition
- 🔴 Again: Review tomorrow, reset progress
- 🟡 Good: Normal interval (1→2→4→8→16 days)
- 🟢 Easy: Longer interval, skip ahead

Commands: /review /due /schedule /stop /resume
"""
    await update.message.reply_text(status_message)


async def due_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /due command - show how many words are due for review."""
    if str(update.effective_user.id) != REVIEW_USER_ID:
        await update.message.reply_text("Sorry, this bot is private.")
        return

    await update.message.reply_text("Checking due words...")

    try:
        stats = notion_handler.get_review_stats()
        due_today = stats.get("due_today", 0)
        overdue = stats.get("overdue", 0)
        new_words = stats.get("new_words", 0)
        mastered = stats.get("mastered", 0)
        total_words = stats.get("total", 0)

        message = f"""📊 Review Stats

🔴 Overdue: {overdue}
🟡 Due today: {due_today}
🆕 New: {new_words}
🎓 Mastered: {mastered}
📚 Total: {total_words}"""
        await update.message.reply_text(message)

    except Exception as e:
        logger.error(f"Error getting review stats: {e}")
        await update.message.reply_text("Failed to get stats.")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stats command — show this week's review stats."""
    if str(update.effective_user.id) != REVIEW_USER_ID:
        await update.message.reply_text("Sorry, this bot is private.")
        return

    if not stats_handler:
        await update.message.reply_text("Stats tracking not configured (REVIEW_STATS_DB_ID missing).")
        return

    from datetime import date, timedelta
    today = date.today()
    # Current week (Mon-today)
    monday = today - timedelta(days=today.weekday())
    days = stats_handler.get_date_range(monday, today)
    total = sum(d["reviewed"] for d in days)
    total_again = sum(d["again"] for d in days)
    total_good = sum(d["good"] for d in days)
    total_easy = sum(d["easy"] for d in days)
    avg = total / len(days) if days else 0

    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    max_val = max((d["reviewed"] for d in days), default=1) or 1
    lines = ["📊 This Week's Reviews"]
    lines.append("")
    for i, d in enumerate(days):
        bar_len = int(d["reviewed"] / max_val * 10)
        bar = "█" * bar_len
        lines.append(f"{day_names[i]}: {d['reviewed']:>3}  {bar}")
    lines.append("")
    lines.append(f"Total: {total} | Avg: {avg:.0f}/day")
    lines.append(f"🔴 {total_again} | 🟡 {total_good} | 🟢 {total_easy}")

    await update.message.reply_text("\n".join(lines))


def format_schedule_text(config: dict) -> str:
    """Format current schedule config as a display string."""
    if not config:
        config = get_default_config()
    default = get_default_config()
    hours = config.get("review_hours", default["review_hours"])
    words = config.get("words_per_batch", default["words_per_batch"])
    hours_str = ", ".join(f"{h:02d}:00" for h in hours)
    return f"Schedule: {hours_str} ({TIMEZONE})\nWords per batch: {words}"


def get_next_review_time() -> str:
    """Get the next scheduled review time from the scheduler."""
    if not scheduler:
        return ""
    review_jobs = [j for j in scheduler.get_jobs() if j.id.startswith("review_")]
    next_times = [getattr(j, 'next_run_time', None) for j in review_jobs]
    next_times = [t for t in next_times if t]
    if not next_times:
        return ""
    next_time = min(next_times)
    return next_time.strftime("%Y-%m-%d %H:%M")


async def send_schedule_display(message_or_query, config: dict, edit: bool = False) -> None:
    """Show current schedule with Edit Times / Edit Word Count buttons."""
    text = f"⚙️ Review Schedule\n\n{format_schedule_text(config)}"
    next_run = get_next_review_time()
    if next_run:
        text += f"\n\nNext review: {next_run}"
    keyboard = [[
        InlineKeyboardButton("Edit Times", callback_data="sched_edit_times"),
        InlineKeyboardButton("Edit Word Count", callback_data="sched_edit_words"),
    ]]
    markup = InlineKeyboardMarkup(keyboard)
    if edit:
        await message_or_query.edit_message_text(text=text, reply_markup=markup)
    else:
        await message_or_query.reply_text(text, reply_markup=markup)


def build_hour_grid(active_hours: list) -> InlineKeyboardMarkup:
    """Build 3-row grid of hour buttons (7-12, 13-18, 19-23) + Done/Back."""
    rows = []
    for row_hours in [(7, 8, 9, 10, 11, 12), (13, 14, 15, 16, 17, 18), (19, 20, 21, 22, 23)]:
        row = []
        for h in row_hours:
            label = f"✅ {h:02d}" if h in active_hours else f"{h:02d}"
            row.append(InlineKeyboardButton(label, callback_data=f"sched_toggle_{h}"))
        rows.append(row)
    rows.append([
        InlineKeyboardButton("Done", callback_data="sched_done_times"),
        InlineKeyboardButton("Back", callback_data="sched_back"),
    ])
    return InlineKeyboardMarkup(rows)


def build_word_options(current: int) -> InlineKeyboardMarkup:
    """Build word count option buttons."""
    options = [5, 10, 15, 20, 30]
    row = []
    for n in options:
        label = f"✅ {n}" if n == current else str(n)
        row.append(InlineKeyboardButton(label, callback_data=f"sched_words_{n}"))
    return InlineKeyboardMarkup([row, [InlineKeyboardButton("Back", callback_data="sched_back")]])


def parse_schedule_text(text: str):
    """Parse free-form schedule text like '20 words at 8 13 17 19 22'."""
    result = {}
    # Match words count
    words_match = re.search(r'(\d+)\s*words?', text, re.IGNORECASE)
    if words_match:
        n = int(words_match.group(1))
        if 1 <= n <= 50:
            result["words_per_batch"] = n
    # Match hours (series of numbers, possibly after "at")
    hours_match = re.search(r'(?:at\s+)?((?:\d{1,2}\s*[,\s]\s*)*\d{1,2})\s*$', text.strip())
    if hours_match:
        nums = re.findall(r'\d{1,2}', hours_match.group(1))
        hours = [int(h) for h in nums if 0 <= int(h) <= 23]
        if hours:
            result["review_hours"] = sorted(set(hours))
    return result if result else None


async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /schedule command - view or update review schedule."""
    global review_config

    logger.info(f"/schedule from user {update.effective_user.id}")

    if str(update.effective_user.id) != REVIEW_USER_ID:
        await update.message.reply_text("Sorry, this bot is private.")
        return

    # If args provided, parse as text command
    if context.args:
        text = " ".join(context.args)
        parsed = parse_schedule_text(text)
        if not parsed:
            await update.message.reply_text("Could not parse schedule. Try: /schedule 20 words at 8 13 17 19 22")
            return
        review_config.update(parsed)
        save_config(review_config)
        if scheduler:
            apply_schedule(scheduler, review_config)
        next_run = get_next_review_time()
        msg = f"✅ Schedule updated!\n\n{format_schedule_text(review_config)}"
        if next_run:
            msg += f"\n\nNext review: {next_run}"
        await update.message.reply_text(msg)
        return

    # No args - show interactive display
    await send_schedule_display(update.message, review_config)


async def handle_schedule_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle schedule-related callback buttons."""
    global review_config

    query = update.callback_query

    if str(query.from_user.id) != REVIEW_USER_ID:
        await query.answer()
        return

    data = query.data

    if data == "sched_edit_times":
        await query.answer("Tap hours to toggle on/off, then press Done", show_alert=True)
        await query.edit_message_text(
            text="Select review hours (tap to toggle):",
            reply_markup=build_hour_grid(review_config["review_hours"])
        )

    elif data.startswith("sched_toggle_"):
        await query.answer()
        hour = int(data.split("_")[-1])
        hours = review_config["review_hours"]
        if hour in hours:
            if len(hours) > 1:  # Keep at least one hour
                hours.remove(hour)
        else:
            hours.append(hour)
            hours.sort()
        review_config["review_hours"] = hours
        await query.edit_message_reply_markup(reply_markup=build_hour_grid(hours))

    elif data == "sched_done_times":
        await query.answer()
        save_config(review_config)
        if scheduler:
            apply_schedule(scheduler, review_config)
        await send_schedule_display(query, review_config, edit=True)

    elif data == "sched_edit_words":
        await query.answer("Tap to select words per batch", show_alert=True)
        await query.edit_message_text(
            text="Select words per batch:",
            reply_markup=build_word_options(review_config["words_per_batch"])
        )

    elif data.startswith("sched_words_"):
        await query.answer()
        n = int(data.split("_")[-1])
        review_config["words_per_batch"] = n
        save_config(review_config)
        await send_schedule_display(query, review_config, edit=True)

    elif data == "sched_back":
        await query.answer()
        await send_schedule_display(query, review_config, edit=True)


def _unspoiler_html(message) -> str:
    """Strip spoiler formatting from message to reveal full content."""
    text = message.text_html
    text = text.replace("<tg-spoiler>", "").replace("</tg-spoiler>", "")
    text = re.sub(r'<span class="tg-spoiler">(.*?)</span>', r'\1', text, flags=re.DOTALL)
    return text


async def handle_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Again/Good/Easy button presses."""
    query = update.callback_query
    await query.answer()

    if str(query.from_user.id) != REVIEW_USER_ID:
        return

    data = query.data

    if data.startswith("again_"):
        page_id = data[6:]  # Remove "again_" prefix
        sent_but_unrated.pop(page_id, None)
        result = notion_handler.update_review_stats(page_id, response="again")
        if stats_handler:
            stats_handler.record_review("again")
        if obsidian_stats_handler:
            try:
                await obsidian_stats_handler.record_review("again")
            except Exception as e:
                logger.error(f"Obsidian stats save failed: {e}")
        revealed = _unspoiler_html(query.message)
        await query.edit_message_text(text=revealed, parse_mode="HTML", reply_markup=None)

    elif data.startswith("good_"):
        page_id = data[5:]  # Remove "good_" prefix
        sent_but_unrated.pop(page_id, None)
        result = notion_handler.update_review_stats(page_id, response="good")
        if stats_handler:
            stats_handler.record_review("good")
        if obsidian_stats_handler:
            try:
                await obsidian_stats_handler.record_review("good")
            except Exception as e:
                logger.error(f"Obsidian stats save failed: {e}")
        revealed = _unspoiler_html(query.message)
        await query.edit_message_text(text=revealed, parse_mode="HTML", reply_markup=None)
        if result.get("mastered"):
            word = query.message.text.split("\n")[2].strip() if query.message.text else ""
            await query.message.reply_text(f"🎓 Mastered: {word}")

    elif data.startswith("easy_"):
        page_id = data[5:]  # Remove "easy_" prefix
        sent_but_unrated.pop(page_id, None)
        result = notion_handler.update_review_stats(page_id, response="easy")
        if stats_handler:
            stats_handler.record_review("easy")
        if obsidian_stats_handler:
            try:
                await obsidian_stats_handler.record_review("easy")
            except Exception as e:
                logger.error(f"Obsidian stats save failed: {e}")
        revealed = _unspoiler_html(query.message)
        await query.edit_message_text(text=revealed, parse_mode="HTML", reply_markup=None)
        if result.get("mastered"):
            word = query.message.text.split("\n")[2].strip() if query.message.text else ""
            await query.message.reply_text(f"🎓 Mastered: {word}")


async def handle_keyboard_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle taps on the persistent reply keyboard buttons."""
    if str(update.effective_user.id) != REVIEW_USER_ID:
        return
    text = update.message.text.strip()
    if text == "📖 Review":
        await update.message.reply_text("Fetching review entries...")
        await send_review_batch(manual=True)
    elif text == "📊 Due":
        await due_command(update, context)
    elif text == "📋 Pending":
        await send_pending_resend()
    elif text == "📈 Stats":
        await stats_command(update, context)


def apply_schedule(sched, config: dict) -> None:
    """Apply review schedule from config, removing old review jobs first."""
    # Remove existing review jobs
    for job in sched.get_jobs():
        if job.id.startswith("review_"):
            sched.remove_job(job.id)

    # Add new jobs from config
    for hour in config["review_hours"]:
        job_id = f"review_{hour:02d}"
        sched.add_job(
            send_review_batch,
            CronTrigger(hour=hour, minute=0, timezone=TIMEZONE),
            id=job_id,
            name=f"Review ({hour:02d}:00)"
        )

    hours_str = ", ".join(f"{h:02d}:00" for h in config["review_hours"])
    logger.info(f"Schedule applied: {hours_str}, {config['words_per_batch']} words per batch")

    # Log next run times for debugging
    for job in sched.get_jobs():
        if job.id.startswith("review_"):
            next_time = getattr(job, 'next_run_time', None)
            if next_time:
                logger.info(f"Job '{job.name}' next run: {next_time}")


async def post_init(app: Application) -> None:
    """Initialize scheduler after application starts."""
    global scheduler

    scheduler = AsyncIOScheduler(timezone=TIMEZONE, misfire_grace_time=120)
    apply_schedule(scheduler, review_config)
    scheduler.start()

    # Weekly report — Sunday at first review hour (or 8:00)
    first_hour = review_config["review_hours"][0] if review_config["review_hours"] else 8
    scheduler.add_job(
        send_weekly_report,
        CronTrigger(day_of_week="sun", hour=first_hour, minute=0, second=0, timezone=TIMEZONE),
        id="weekly_report",
        name="Weekly Review Report",
        misfire_grace_time=300,
    )

    # Monthly report — 1st of month at 7:00 AM
    scheduler.add_job(
        send_monthly_report,
        CronTrigger(day=1, hour=7, minute=0, timezone=TIMEZONE),
        id="monthly_report",
        name="Monthly Review Report",
        misfire_grace_time=300,
    )

    logger.info(f"Scheduler started with timezone {TIMEZONE}")

    # Log next run times for debugging
    for job in scheduler.get_jobs():
        next_run = getattr(job, 'next_run_time', None)
        if next_run:
            logger.info(f"Job '{job.name}' next run: {next_run}")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors."""
    logger.error(f"Update {update} caused error {context.error}")


def main():
    """Main function to run the review bot."""
    global notion_handler, config_handler, application, review_config, is_paused, stats_handler, obsidian_stats_handler

    # Validate configuration
    if not REVIEW_BOT_TOKEN:
        print("ERROR: REVIEW_BOT_TOKEN not set in .env file")
        return
    if not REVIEW_USER_ID:
        print("ERROR: REVIEW_USER_ID not set in .env file")
        return
    if not NOTION_KEY:
        print("ERROR: NOTION_API_KEY not set in .env file")
        return

    # Initialize Notion handler with additional databases for review
    notion_handler = NotionHandler(NOTION_KEY, NOTION_DB_ID, additional_database_ids=ADDITIONAL_DB_IDS)

    # Initialize central config handler
    if CONFIG_DB_ID:
        from shared.config_handler import ConfigHandler
        config_handler = ConfigHandler(NOTION_KEY, CONFIG_DB_ID)
        print(f"Central config DB connected: {CONFIG_DB_ID[:8]}...")
    else:
        print("WARNING: CONFIG_DB_ID not set — config won't persist across restarts")

    # Test Notion connection
    notion_test = notion_handler.test_connection()
    if notion_test["success"]:
        print(f"Notion connected: {notion_test['database_title']}")
        if ADDITIONAL_DB_IDS:
            print(f"Additional databases for review: {len(ADDITIONAL_DB_IDS)} configured")
    else:
        print(f"WARNING: Notion connection issue: {notion_test['error']}")

    if REVIEW_STATS_DB_ID:
        stats_handler = ReviewStatsHandler(NOTION_KEY, REVIEW_STATS_DB_ID, timezone=TIMEZONE)
        logger.info("Review stats tracking enabled")
    else:
        logger.warning("REVIEW_STATS_DB_ID not set — stats tracking disabled")

    # Initialize Obsidian review stats handler (best-effort)
    try:
        obsidian_stats_handler = ObsidianReviewStatsHandler()
        print("Obsidian review stats handler initialized")
    except ValueError:
        obsidian_stats_handler = None
        logger.info("Obsidian review stats disabled (OBSIDIAN_GITHUB_TOKEN not set)")

    # Load schedule config (including pause state)
    review_config = load_config()
    is_paused = review_config.get("is_paused", False)
    print(f"Config loaded: hours={review_config['review_hours']}, words={review_config['words_per_batch']}, paused={is_paused}")

    # Create application
    application = Application.builder().token(REVIEW_BOT_TOKEN).post_init(post_init).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("myid", myid_command))
    application.add_handler(CommandHandler("review", review_command))
    application.add_handler(CommandHandler("due", due_command))
    application.add_handler(CommandHandler("schedule", schedule_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("resume", resume_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CallbackQueryHandler(handle_schedule_callback, pattern=r"^sched_"))
    application.add_handler(CallbackQueryHandler(handle_review_callback, pattern=r"^(again|good|easy)_"))
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r"^(📖 Review|📊 Due|📋 Pending|📈 Stats)$"),
        handle_keyboard_button
    ))

    # Add error handler
    application.add_error_handler(error_handler)

    # Start polling (drop pending updates to avoid processing old queued commands)
    print(f"Review bot starting with timezone {TIMEZONE}...")
    print(format_schedule_text(review_config))
    print("Press Ctrl+C to stop")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"FATAL ERROR in review_bot: {e}")
        import traceback
        traceback.print_exc()
