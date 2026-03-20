"""
Grammar Drill Bot

Telegram bot for English grammar drills from Obsidian markdown files via GitHub.
- Flashcard style: spoiler-masked answers, self-assessment (Again/Good/Easy)
- Weekly grammar rotation (7 categories) + daily Top Phrases
- Status tracking buffered daily, synced to GitHub once per day
"""

import os
import logging
import re
import random
from datetime import datetime, date, timedelta

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

from github_handler import GitHubHandler, CATEGORY_NAMES, CATEGORY_FILES

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Config
BOT_TOKEN = os.getenv("GRAMMAR_BOT_TOKEN")
USER_ID = int(os.getenv("GRAMMAR_USER_ID", "0"))
TIMEZONE = os.getenv("TIMEZONE", "Europe/London")
START_DATE = date(2026, 3, 16)

# Reply keyboard
REPLY_KEYBOARD = ReplyKeyboardMarkup(
    [["Practice", "Schedule"]],
    resize_keyboard=True,
)

# Globals
github: GitHubHandler = None
scheduler: AsyncIOScheduler = None
bot_config: dict = {}
app_instance: Application = None
daily_buffer: dict = {}  # In-memory buffer: {filename: {card_num: {status, ...}}}


def get_week_number() -> int:
    today = date.today()
    if today < START_DATE:
        return 0
    return ((today - START_DATE).days // 7) % 8


def get_day_in_week() -> int:
    today = date.today()
    if today < START_DATE:
        return 1
    return (today - START_DATE).days % 7 + 1


def is_authorized(update: Update) -> bool:
    return update.effective_user.id == USER_ID


def _escape_md(text: str) -> str:
    if not text:
        return ""
    special = r"_*[]()~`>#+-=|{}.!\\"
    return re.sub(f"([{re.escape(special)}])", r"\\\1", str(text))


# ── Card Selection ────────────────────────────────────────────────

def select_cards(cards: list[dict], count: int, buffer: dict, filename: str) -> list[dict]:
    """Select cards based on spaced repetition priority, applying buffer overrides."""
    today = date.today()
    file_buffer = buffer.get(filename, {})
    eligible = []

    for card in cards:
        # Apply buffer override if exists
        card_key = str(card["num"])
        if card_key in file_buffer:
            buf = file_buffer[card_key]
            card["status"] = buf.get("status", card["status"])
            card["next_review"] = buf.get("next_review", card["next_review"])
            card["easy_streak"] = buf.get("easy_streak", card["easy_streak"])

        status = card["status"]
        if status == "retired":
            continue

        next_review = card.get("next_review", "")
        priority = 0

        if status == "new":
            priority = 200
        elif status == "again":
            if next_review:
                nr = date.fromisoformat(next_review)
                priority = 180 + max(0, (today - nr).days) * 5 if nr <= today else 50
            else:
                priority = 180
        elif status == "good":
            if next_review:
                nr = date.fromisoformat(next_review)
                priority = 150 + max(0, (today - nr).days) * 3 if nr <= today else 30
            else:
                priority = 150
        elif status == "easy":
            if next_review:
                nr = date.fromisoformat(next_review)
                priority = 100 if nr <= today else 10
            else:
                priority = 100

        if priority > 0:
            eligible.append((card, priority))

    eligible.sort(key=lambda x: x[1], reverse=True)

    if len(eligible) <= count:
        selected = [c for c, _ in eligible]
    else:
        pool_size = min(len(eligible), count * 2)
        pool = eligible[:pool_size]
        selected = []
        pool_copy = list(pool)
        for _ in range(min(count, len(pool_copy))):
            if not pool_copy:
                break
            weights = [p for _, p in pool_copy]
            chosen = random.choices(pool_copy, weights=weights, k=1)[0]
            idx = pool_copy.index(chosen)
            selected.append(chosen[0])
            pool_copy.pop(idx)

    random.shuffle(selected)
    return selected


def compute_new_status(rating: str, card: dict) -> dict:
    """Compute new status fields based on rating. Returns update dict."""
    today_str = date.today().isoformat()
    update = {"last_reviewed": today_str}

    if rating == "again":
        update["status"] = "again"
        update["next_review"] = (date.today() + timedelta(days=1)).isoformat()
        update["easy_streak"] = 0
    elif rating == "good":
        update["status"] = "good"
        update["next_review"] = (date.today() + timedelta(days=4)).isoformat()
        update["easy_streak"] = 0
    elif rating == "easy":
        easy_streak = card.get("easy_streak", 0) + 1
        update["easy_streak"] = easy_streak
        if easy_streak >= 3:
            update["status"] = "retired"
            update["next_review"] = ""
        else:
            update["status"] = "easy"
            update["next_review"] = (date.today() + timedelta(days=14)).isoformat()

    return update


def buffer_rating(filename: str, card_num: int, update: dict):
    """Store a card rating in the in-memory daily buffer."""
    global daily_buffer
    if filename not in daily_buffer:
        daily_buffer[filename] = {}
    daily_buffer[filename][str(card_num)] = update


# ── Send Cards (Flashcard Style) ─────────────────────────────────

async def send_flashcards(bot, chat_id: int, cards: list[dict], category: str, card_type: str):
    """Send all cards at once as flashcards with spoiler answers."""
    for i, card in enumerate(cards):
        try:
            if card_type == "phrase":
                # Top Phrases: Chinese prompt + keyword, spoiler answer
                text = (
                    f"*{_escape_md(category)} {i + 1}/{len(cards)}*\n\n"
                    f"{_escape_md(card['chinese_prompt'])}\n"
                    f"💡 {_escape_md(card['keyword_hint'])}\n\n"
                    f"||{_escape_md(card['answer'])}||"
                )
            else:
                # Grammar: sentence with blank, spoiler answer + spoiler rule
                text = (
                    f"*{_escape_md(category)} {i + 1}/{len(cards)}*\n\n"
                    f"{_escape_md(card['question'])}\n\n"
                    f"||{_escape_md(card['answer'])}||\n"
                    f"||{_escape_md(card['rule'])}||"
                )

            cb_prefix = f"{card['_filename']}:{card['num']}"

            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔴 Again", callback_data=f"r_a_{cb_prefix}"),
                InlineKeyboardButton("🟡 Good", callback_data=f"r_g_{cb_prefix}"),
                InlineKeyboardButton("🟢 Easy", callback_data=f"r_e_{cb_prefix}"),
            ]])

            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="MarkdownV2",
                reply_markup=keyboard,
            )
        except Exception as e:
            logger.error(f"Failed to send card {card.get('num')}: {e}", exc_info=True)
            # Try sending without MarkdownV2 as fallback
            try:
                plain = f"{category} {i + 1}/{len(cards)}\n\n"
                if card_type == "phrase":
                    plain += f"{card.get('chinese_prompt', '')}\n💡 {card.get('keyword_hint', '')}\n\nAnswer: {card.get('answer', '')}"
                else:
                    plain += f"{card.get('question', '')}\n\nAnswer: {card.get('answer', '')}\nRule: {card.get('rule', '')}"
                await bot.send_message(chat_id=chat_id, text=plain, reply_markup=keyboard)
            except Exception:
                pass


# ── Command Handlers ──────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print(f"Grammar bot /start from user {update.effective_user.id}, authorized={is_authorized(update)}")
    if not is_authorized(update):
        return

    week = get_week_number()
    category = CATEGORY_NAMES[week]
    day = get_day_in_week()

    text = (
        f"📝 *Grammar Drill Bot*\n\n"
        f"Current week: *{_escape_md(category)}* \\(Day {day}/7\\)\n\n"
        f"Tap *Practice* to start a drill session\n"
        f"Tap *Schedule* to change settings"
    )
    await update.message.reply_text(
        text=text, parse_mode="MarkdownV2", reply_markup=REPLY_KEYBOARD,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    await cmd_start(update, context)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    week = get_week_number()
    category = CATEGORY_NAMES[week]
    day = get_day_in_week()

    try:
        cards, _, _, _ = await github.fetch_cards(week)
        # Apply buffer
        filename = CATEGORY_FILES[week]
        cards = github.apply_buffer_to_cards(cards, daily_buffer, filename)

        total = len(cards)
        counts = {}
        for c in cards:
            counts[c["status"]] = counts.get(c["status"], 0) + 1

        gc = bot_config.get("grammar_count", 5)
        pc = bot_config.get("phrase_count", 3)
        push_str = "paused" if bot_config.get("paused") else f"{bot_config.get('push_hour', 9):02d}:{bot_config.get('push_minute', 0):02d}"

        text = (
            f"📊 *Status*\n\n"
            f"Week: *{_escape_md(category)}* \\(Day {day}/7\\)\n"
            f"Cards: {total} total\n"
            f"🆕 {counts.get('new', 0)} 🔴 {counts.get('again', 0)} "
            f"🟡 {counts.get('good', 0)} 🟢 {counts.get('easy', 0)} "
            f"✅ {counts.get('retired', 0)}\n\n"
            f"Push: {_escape_md(push_str)}\n"
            f"Grammar: {gc} / Phrases: {pc}"
        )
    except Exception as e:
        logger.error(f"Status error: {e}")
        text = f"❌ Error: {_escape_md(str(e))}"

    await update.message.reply_text(text=text, parse_mode="MarkdownV2", reply_markup=REPLY_KEYBOARD)


def _format_schedule_text() -> str:
    """Format current schedule settings as display text."""
    gc = bot_config.get("grammar_count", 5)
    pc = bot_config.get("phrase_count", 3)
    h = bot_config.get("push_hour", 9)
    m = bot_config.get("push_minute", 0)
    paused = bot_config.get("paused", False)
    status = " (paused)" if paused else ""
    return (
        f"⚙️ Grammar Drill Schedule\n\n"
        f"Push time: {h:02d}:{m:02d}{status}\n"
        f"Grammar cards: {gc}\n"
        f"Top phrases: {pc}"
    )


async def send_schedule_display(message_or_query, edit: bool = False):
    """Show current schedule with inline edit buttons."""
    text = _format_schedule_text()
    keyboard = [
        [
            InlineKeyboardButton("Edit Time", callback_data="gsched_edit_time"),
            InlineKeyboardButton("Edit Grammar Count", callback_data="gsched_edit_grammar"),
        ],
        [
            InlineKeyboardButton("Edit Phrase Count", callback_data="gsched_edit_phrase"),
        ],
    ]
    markup = InlineKeyboardMarkup(keyboard)
    if edit:
        await message_or_query.edit_message_text(text=text, reply_markup=markup)
    else:
        await message_or_query.reply_text(text, reply_markup=markup)


def _build_hour_grid() -> InlineKeyboardMarkup:
    """Build hour grid for push time selection (7-23) + minute selector."""
    current_hour = bot_config.get("push_hour", 9)
    rows = []
    for row_hours in [(7, 8, 9, 10, 11, 12), (13, 14, 15, 16, 17, 18), (19, 20, 21, 22, 23)]:
        row = []
        for h in row_hours:
            label = f"✅ {h:02d}" if h == current_hour else f"{h:02d}"
            row.append(InlineKeyboardButton(label, callback_data=f"gsched_hour_{h}"))
        rows.append(row)
    rows.append([
        InlineKeyboardButton("Back", callback_data="gsched_back"),
    ])
    return InlineKeyboardMarkup(rows)


def _build_minute_grid(hour: int) -> InlineKeyboardMarkup:
    """Build minute selector for a chosen hour."""
    current_hour = bot_config.get("push_hour", 9)
    current_min = bot_config.get("push_minute", 0)
    options = [0, 15, 30, 45]
    row = []
    for m in options:
        label = f"✅ {hour:02d}:{m:02d}" if (hour == current_hour and m == current_min) else f"{hour:02d}:{m:02d}"
        row.append(InlineKeyboardButton(label, callback_data=f"gsched_min_{hour}_{m}"))
    return InlineKeyboardMarkup([row, [InlineKeyboardButton("Back", callback_data="gsched_edit_time")]])


def _build_count_options(setting_key: str) -> InlineKeyboardMarkup:
    """Build count option buttons for grammar or phrase count."""
    current = bot_config.get(setting_key, 5)
    options = [3, 5, 8, 10, 15]
    prefix = "gsched_gc" if setting_key == "grammar_count" else "gsched_pc"
    row = []
    for n in options:
        label = f"✅ {n}" if n == current else str(n)
        row.append(InlineKeyboardButton(label, callback_data=f"{prefix}_{n}"))
    return InlineKeyboardMarkup([row, [InlineKeyboardButton("Back", callback_data="gsched_back")]])


async def handle_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the Schedule button — show interactive settings."""
    if not is_authorized(update):
        return
    await send_schedule_display(update.message)


async def handle_schedule_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all gsched_* callback buttons for schedule settings."""
    global bot_config
    query = update.callback_query

    if query.from_user.id != USER_ID:
        await query.answer()
        return

    data = query.data

    if data == "gsched_edit_time":
        await query.answer("Tap an hour, then pick minutes", show_alert=True)
        await query.edit_message_text(
            text="Select push hour:",
            reply_markup=_build_hour_grid(),
        )

    elif data.startswith("gsched_hour_"):
        await query.answer()
        hour = int(data.split("_")[-1])
        await query.edit_message_text(
            text=f"Selected {hour:02d}:xx — pick minutes:",
            reply_markup=_build_minute_grid(hour),
        )

    elif data.startswith("gsched_min_"):
        await query.answer()
        parts = data.split("_")
        hour, minute = int(parts[2]), int(parts[3])
        bot_config["push_hour"] = hour
        bot_config["push_minute"] = minute
        _apply_schedule()
        try:
            await github.save_config(bot_config)
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
        await send_schedule_display(query, edit=True)

    elif data == "gsched_edit_grammar":
        await query.answer("Tap to select grammar cards per session", show_alert=True)
        await query.edit_message_text(
            text="Select grammar cards per session:",
            reply_markup=_build_count_options("grammar_count"),
        )

    elif data.startswith("gsched_gc_"):
        await query.answer()
        n = int(data.split("_")[-1])
        bot_config["grammar_count"] = n
        try:
            await github.save_config(bot_config)
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
        await send_schedule_display(query, edit=True)

    elif data == "gsched_edit_phrase":
        await query.answer("Tap to select phrases per session", show_alert=True)
        await query.edit_message_text(
            text="Select top phrases per session:",
            reply_markup=_build_count_options("phrase_count"),
        )

    elif data.startswith("gsched_pc_"):
        await query.answer()
        n = int(data.split("_")[-1])
        bot_config["phrase_count"] = n
        try:
            await github.save_config(bot_config)
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
        await send_schedule_display(query, edit=True)

    elif data == "gsched_back":
        await query.answer()
        await send_schedule_display(query, edit=True)


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    args = context.args
    if not args:
        await handle_schedule(update, context)
        return

    text = " ".join(args).lower()

    # Parse grammar count
    gm = re.search(r"(\d+)\s*grammar", text)
    if gm:
        count = int(gm.group(1))
        if 1 <= count <= 20:
            bot_config["grammar_count"] = count

    # Parse phrase count
    pm = re.search(r"(\d+)\s*phrases?", text)
    if pm:
        count = int(pm.group(1))
        if 1 <= count <= 20:
            bot_config["phrase_count"] = count

    # Parse time
    tm = re.search(r"(?:at\s+)?(\d{1,2}):(\d{2})", text)
    if tm:
        hour, minute = int(tm.group(1)), int(tm.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            bot_config["push_hour"] = hour
            bot_config["push_minute"] = minute
            _apply_schedule()

    try:
        await github.save_config(bot_config)
    except Exception as e:
        logger.error(f"Failed to save config: {e}")

    gc = bot_config.get("grammar_count", 5)
    pc = bot_config.get("phrase_count", 3)
    h = bot_config.get("push_hour", 9)
    m = bot_config.get("push_minute", 0)

    await update.message.reply_text(
        f"✅ Updated\\!\nGrammar: {gc} / Phrases: {pc}\nPush: {h:02d}:{m:02d}",
        parse_mode="MarkdownV2", reply_markup=REPLY_KEYBOARD,
    )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    bot_config["paused"] = True
    try:
        await github.save_config(bot_config)
    except Exception as e:
        logger.error(f"Failed to save config: {e}")
    if scheduler and scheduler.get_job("daily_push"):
        scheduler.remove_job("daily_push")
    await update.message.reply_text("⏸ Paused. /resume to restart.", reply_markup=REPLY_KEYBOARD)


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    bot_config["paused"] = False
    try:
        await github.save_config(bot_config)
    except Exception as e:
        logger.error(f"Failed to save config: {e}")
    _apply_schedule()
    h = bot_config.get("push_hour", 9)
    m = bot_config.get("push_minute", 0)
    await update.message.reply_text(f"▶️ Resumed at {h:02d}:{m:02d}.", reply_markup=REPLY_KEYBOARD)


# ── Practice Session ──────────────────────────────────────────────

async def start_practice(bot_or_update, chat_id: int):
    """Start a drill session: grammar cards + top phrases, all sent at once."""
    if hasattr(bot_or_update, 'get_bot'):
        bot = bot_or_update.get_bot()
    elif hasattr(bot_or_update, 'bot'):
        bot = bot_or_update.bot
    else:
        bot = bot_or_update

    if not github:
        logger.error("Practice failed: github handler not initialized")
        raise RuntimeError("GitHub handler not initialized — check OBSIDIAN_GITHUB_TOKEN")

    week = get_week_number()
    grammar_count = bot_config.get("grammar_count", 5)
    phrase_count = bot_config.get("phrase_count", 3)

    # Fetch grammar cards for current week
    grammar_cards = []
    grammar_filename = CATEGORY_FILES[week]
    try:
        cards, _, _, _ = await github.fetch_cards(week)
        selected = select_cards(cards, grammar_count, daily_buffer, grammar_filename)
        for c in selected:
            c["_filename"] = grammar_filename
            c["_week"] = week
        grammar_cards = selected
    except Exception as e:
        logger.error(f"Failed to fetch grammar cards: {e}", exc_info=True)

    # Fetch top phrases (always)
    phrase_cards = []
    phrase_filename = CATEGORY_FILES[7]
    if week != 7:  # Don't double-fetch if this week IS phrases week
        try:
            pcards, _, _, _ = await github.fetch_phrase_cards()
            selected_p = select_cards(pcards, phrase_count, daily_buffer, phrase_filename)
            for c in selected_p:
                c["_filename"] = phrase_filename
                c["_week"] = 7
            phrase_cards = selected_p
        except Exception as e:
            logger.error(f"Failed to fetch phrase cards: {e}", exc_info=True)
    else:
        # Phrases week — all cards are phrases, use grammar_count + phrase_count
        total = grammar_count + phrase_count
        try:
            pcards, _, _, _ = await github.fetch_phrase_cards()
            selected_p = select_cards(pcards, total, daily_buffer, phrase_filename)
            for c in selected_p:
                c["_filename"] = phrase_filename
                c["_week"] = 7
            phrase_cards = selected_p
            grammar_cards = []  # No separate grammar on phrases week
        except Exception as e:
            logger.error(f"Failed to fetch phrase cards: {e}", exc_info=True)

    if not grammar_cards and not phrase_cards:
        if hasattr(bot_or_update, 'effective_message'):
            await bot_or_update.effective_message.reply_text(
                "No cards available today!", reply_markup=REPLY_KEYBOARD)
        else:
            await bot.send_message(chat_id=chat_id,
                text="No cards available today!", reply_markup=REPLY_KEYBOARD)
        return

    category = CATEGORY_NAMES[week]

    # Send grammar cards
    if grammar_cards:
        await send_flashcards(bot, chat_id, grammar_cards, category, "grammar")

    # Send phrase cards
    if phrase_cards:
        await send_flashcards(bot, chat_id, phrase_cards, "Phrases", "phrase")


async def handle_practice_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    try:
        await start_practice(update, update.effective_user.id)
    except Exception as e:
        logger.error(f"Practice error: {e}", exc_info=True)
        try:
            await update.effective_message.reply_text(
                f"❌ Practice error: {e}", reply_markup=REPLY_KEYBOARD)
        except Exception:
            pass


async def handle_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Again/Good/Easy rating buttons."""
    query = update.callback_query
    await query.answer()

    if query.from_user.id != USER_ID:
        return

    # Parse callback: r_a_filename:num, r_g_filename:num, r_e_filename:num
    data = query.data
    parts = data.split("_", 2)
    if len(parts) < 3:
        return

    rating_code = parts[1]  # a, g, e
    rating_map = {"a": "again", "g": "good", "e": "easy"}
    rating = rating_map.get(rating_code)
    if not rating:
        return

    file_card = parts[2]  # filename:num
    if ":" not in file_card:
        return
    filename, card_num_str = file_card.rsplit(":", 1)

    # Get current card state from buffer or default
    file_buf = daily_buffer.get(filename, {})
    current = file_buf.get(card_num_str, {"easy_streak": 0})

    # Compute new status
    update_data = compute_new_status(rating, current)

    # Store in buffer
    buffer_rating(filename, int(card_num_str), update_data)

    # Update the button to show which was selected
    rating_labels = {"again": "🔴 Again ✓", "good": "🟡 Good ✓", "easy": "🟢 Easy ✓"}
    new_keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            rating_labels[r] if r == rating else label,
            callback_data="noop"
        )
        for r, label in [("again", "🔴 Again"), ("good", "🟡 Good"), ("easy", "🟢 Easy")]
    ]])

    try:
        await query.edit_message_reply_markup(reply_markup=new_keyboard)
    except Exception:
        pass  # Message may be too old to edit


# ── Scheduled Jobs ────────────────────────────────────────────────

async def scheduled_push():
    """Send daily drill push."""
    if bot_config.get("paused"):
        return
    logger.info("Sending scheduled grammar drill push")
    await start_practice(app_instance, USER_ID)


async def scheduled_sync():
    """Daily sync: write buffer to .md files on GitHub, clear buffer."""
    global daily_buffer
    if not github:
        return
    if not daily_buffer:
        logger.info("No buffer data to sync")
        return

    logger.info(f"Starting daily sync, buffer has {sum(len(v) for v in daily_buffer.values())} updates")

    try:
        # Save buffer to GitHub first (backup)
        await github.save_buffer(daily_buffer)
        # Now sync to .md files
        await github.sync_buffer_to_markdown()
        # Clear in-memory buffer
        daily_buffer = {}
        logger.info("Daily sync complete")
    except Exception as e:
        logger.error(f"Daily sync failed: {e}")


def _apply_schedule():
    """Apply/update scheduled jobs."""
    global scheduler
    if not scheduler:
        return

    # Daily push
    if scheduler.get_job("daily_push"):
        scheduler.remove_job("daily_push")
    if not bot_config.get("paused"):
        hour = bot_config.get("push_hour", 9)
        minute = bot_config.get("push_minute", 0)
        tz = pytz.timezone(TIMEZONE)
        scheduler.add_job(
            scheduled_push,
            CronTrigger(hour=hour, minute=minute, timezone=tz),
            id="daily_push",
            misfire_grace_time=120,
        )
        logger.info(f"Scheduled daily push at {hour:02d}:{minute:02d}")

    # Daily sync at 3:03 AM (offset from round numbers to avoid Obsidian sync)
    if not scheduler.get_job("daily_sync"):
        tz = pytz.timezone(TIMEZONE)
        scheduler.add_job(
            scheduled_sync,
            CronTrigger(hour=3, minute=3, timezone=tz),
            id="daily_sync",
            misfire_grace_time=300,
        )
        logger.info("Scheduled daily sync at 03:03")


# ── Application Setup ─────────────────────────────────────────────

async def post_init(app: Application):
    global github, scheduler, bot_config, app_instance, daily_buffer
    app_instance = app

    print(f"Grammar bot post_init: USER_ID={USER_ID}, TIMEZONE={TIMEZONE}")
    print(f"Grammar bot post_init: OBSIDIAN_GITHUB_TOKEN={'set' if os.getenv('OBSIDIAN_GITHUB_TOKEN') else 'NOT SET'}")

    try:
        github = GitHubHandler()
    except Exception as e:
        print(f"Grammar bot ERROR: GitHubHandler init failed: {e}")
        logger.error(f"GitHubHandler init failed: {e}")
        github = None

    if github:
        try:
            bot_config = await github.fetch_config()
            logger.info(f"Loaded config: {bot_config}")
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            bot_config = {"push_hour": 9, "push_minute": 0, "grammar_count": 5, "phrase_count": 3, "paused": False}

        # Load any unsynced buffer from previous run
        try:
            daily_buffer = await github.load_buffer()
            if daily_buffer:
                logger.info(f"Loaded unsynced buffer: {sum(len(v) for v in daily_buffer.values())} updates")
        except Exception as e:
            logger.error(f"Failed to load buffer: {e}")
            daily_buffer = {}
    else:
        bot_config = {"push_hour": 9, "push_minute": 0, "grammar_count": 5, "phrase_count": 3, "paused": False}

    tz = pytz.timezone(TIMEZONE)
    scheduler = AsyncIOScheduler(timezone=tz, misfire_grace_time=120)
    _apply_schedule()
    scheduler.start()

    print("Grammar Drill Bot initialized successfully")
    logger.info("Grammar Drill Bot initialized")


def main():
    if not BOT_TOKEN:
        print("ERROR: GRAMMAR_BOT_TOKEN not set")
        return

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("resume", cmd_resume))

    app.add_handler(CallbackQueryHandler(handle_schedule_callback, pattern=r"^gsched_"))
    app.add_handler(CallbackQueryHandler(handle_rating, pattern=r"^r_"))

    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r"^Practice$") & ~filters.COMMAND,
        handle_practice_button,
    ))
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r"^Schedule$") & ~filters.COMMAND,
        handle_schedule,
    ))

    print("Grammar Drill Bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
