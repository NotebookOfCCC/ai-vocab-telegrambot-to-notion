"""
Grammar Drill Bot

A Telegram bot for English grammar drills powered by Obsidian markdown files
synced via a private GitHub repo. Two practice modes:
  - Fill-in-the-blank (grammar errors, weeks 1-7)
  - Chinese-to-English phrase production (week 8)

Spaced repetition with status tracking written back to GitHub.
"""

import os
import logging
import re
import random
from datetime import datetime, date, timedelta

from dotenv import load_dotenv
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from github_handler import GitHubHandler, CATEGORY_NAMES

load_dotenv()

# Logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Config
BOT_TOKEN = os.getenv("GRAMMAR_BOT_TOKEN")
USER_ID = int(os.getenv("GRAMMAR_USER_ID", "0"))
TIMEZONE = os.getenv("TIMEZONE", "Europe/London")
START_DATE = date(2026, 3, 16)  # Monday of week 1

# Reply keyboard
REPLY_KEYBOARD = ReplyKeyboardMarkup(
    [["Practice"]],
    resize_keyboard=True,
)

# Globals
github: GitHubHandler = None
scheduler: AsyncIOScheduler = None
bot_config: dict = {}

# Session state per user
sessions: dict = {}


def get_week_number() -> int:
    """Get current week number (0-7) in the 8-week rotation."""
    today = date.today()
    if today < START_DATE:
        return 0
    days = (today - START_DATE).days
    return (days // 7) % 8


def get_day_in_week() -> int:
    """Get current day within the week (1-7)."""
    today = date.today()
    if today < START_DATE:
        return 1
    days = (today - START_DATE).days
    return (days % 7) + 1


def is_authorized(update: Update) -> bool:
    """Check if the user is authorized."""
    return update.effective_user.id == USER_ID


def select_cards(cards: list[dict], count: int) -> list[dict]:
    """Select cards for a drill session based on spaced repetition priority."""
    today = date.today()
    eligible = []

    for card in cards:
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
                if nr <= today:
                    priority = 180 + (today - nr).days * 5
                else:
                    priority = 50
            else:
                priority = 180
        elif status == "good":
            if next_review:
                nr = date.fromisoformat(next_review)
                if nr <= today:
                    priority = 150 + (today - nr).days * 3
                else:
                    priority = 30
            else:
                priority = 150
        elif status == "easy":
            if next_review:
                nr = date.fromisoformat(next_review)
                if nr <= today:
                    priority = 100
                else:
                    priority = 10
            else:
                priority = 100

        if priority > 0:
            eligible.append((card, priority))

    # Sort by priority descending, pick top candidates
    eligible.sort(key=lambda x: x[1], reverse=True)

    # Take top candidates with some randomness among equal priorities
    if len(eligible) <= count:
        selected = [c for c, _ in eligible]
    else:
        # Take from top pool (2x count) with weighted random
        pool_size = min(len(eligible), count * 2)
        pool = eligible[:pool_size]
        weights = [p for _, p in pool]
        selected = []
        pool_copy = list(pool)
        weights_copy = list(weights)
        for _ in range(min(count, len(pool_copy))):
            if not pool_copy:
                break
            chosen = random.choices(pool_copy, weights=weights_copy, k=1)[0]
            idx = pool_copy.index(chosen)
            selected.append(chosen[0])
            pool_copy.pop(idx)
            weights_copy.pop(idx)

    random.shuffle(selected)
    return selected


def check_answer(user_answer: str, correct_answer: str) -> bool:
    """Check if the user's answer matches the correct answer (grammar cards)."""
    user = user_answer.strip().strip('"\'').lower()
    correct = correct_answer.strip().strip('"\'').lower()

    # Zero article variants
    zero_variants = {"nothing", "none", "∅", "zero", "-", "", "no article"}
    if correct in zero_variants or correct.startswith("(no"):
        return user in zero_variants or user.startswith("(no")

    # Normalize whitespace
    user = " ".join(user.split())
    correct = " ".join(correct.split())

    return user == correct


def update_card_status(card: dict, rating: str):
    """Update card status based on user rating."""
    today = date.today().isoformat()
    card["last_reviewed"] = today

    if rating == "again":
        card["status"] = "again"
        card["next_review"] = (date.today() + timedelta(days=1)).isoformat()
        card["easy_streak"] = 0
    elif rating == "good":
        card["status"] = "good"
        card["next_review"] = (date.today() + timedelta(days=4)).isoformat()
        card["easy_streak"] = 0
    elif rating == "easy":
        card["status"] = "easy"
        card["next_review"] = (date.today() + timedelta(days=14)).isoformat()
        card["easy_streak"] = card.get("easy_streak", 0) + 1
        # Auto-retire after 3 consecutive easy
        if card["easy_streak"] >= 3:
            card["status"] = "retired"
            card["next_review"] = ""


async def send_card(update_or_context, chat_id: int, session: dict):
    """Send the current card to the user."""
    idx = session["current_index"]
    total = len(session["selected_cards"])
    card = session["selected_cards"][idx]
    week = session["week_number"]
    category = CATEGORY_NAMES[week]

    if card["type"] == "phrase":
        text = (
            f"📝 *Phrase Drill* \\({_escape_md(category)}\\) — {idx + 1}/{total}\n\n"
            f"用英语表达这个意思：\n"
            f"*\"{_escape_md(card['chinese_prompt'])}\"*\n\n"
            f"💡 Keyword: *{_escape_md(card['keyword_hint'])}*"
        )
    else:
        text = (
            f"📝 *Grammar Drill* \\({_escape_md(category)}\\) — {idx + 1}/{total}\n\n"
            f"Fill in the blank:\n"
            f"\"{_escape_md(card['question'])}\""
        )

    # Determine how to send
    if hasattr(update_or_context, 'bot'):
        # It's a context object (from scheduler)
        await update_or_context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="MarkdownV2",
        )
    else:
        # It's an Update object
        await update_or_context.effective_message.reply_text(
            text=text,
            parse_mode="MarkdownV2",
        )

    session["awaiting_answer"] = True


async def show_result(update: Update, card: dict, user_answer: str, is_correct: bool | None):
    """Show the result after user answers, with rating buttons."""
    card_id = f"{card['num']}_{sessions[update.effective_user.id]['week_number']}"

    if card["type"] == "phrase":
        # No auto-judging for phrases — just show the target
        text = (
            f"🎯 *Target phrase:* {_escape_md(card['answer'])}\n"
            f"💬 \"{_escape_md(card['example_sentence'])}\"\n\n"
            f"Your answer: {_escape_md(user_answer)}"
        )
    else:
        if is_correct:
            text = f"✅ *Correct\\!*\n"
        else:
            text = (
                f"❌ *Not quite\\!*\n\n"
                f"Your answer: {_escape_md(user_answer)}\n"
                f"✅ Correct answer: *{_escape_md(card['answer'])}*\n"
            )
        text += (
            f"❌ You originally wrote: {_escape_md(card['wrong'])}\n"
            f"📖 Rule: {_escape_md(card['rule'])}"
        )

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔴 Again", callback_data=f"rate_again_{card_id}"),
        InlineKeyboardButton("🟡 Good", callback_data=f"rate_good_{card_id}"),
        InlineKeyboardButton("🟢 Easy", callback_data=f"rate_easy_{card_id}"),
    ]])

    await update.effective_message.reply_text(
        text=text,
        parse_mode="MarkdownV2",
        reply_markup=keyboard,
    )


async def show_summary(update_or_context, chat_id: int, session: dict):
    """Show daily summary after all cards are done."""
    correct = session.get("correct_count", 0)
    total = len(session["selected_cards"])
    week = session["week_number"]
    category = CATEGORY_NAMES[week]
    day = get_day_in_week()

    text = f"📊 *Today's Results*\n\n"
    text += f"✅ {correct}/{total} correct\n"

    # Show mistakes
    mistakes = session.get("mistakes", [])
    if mistakes:
        text += f"\nMistakes to review:\n"
        for m in mistakes:
            if m["type"] == "phrase":
                text += f"• {_escape_md(m['chinese_prompt'])} → {_escape_md(m['answer'])}\n"
            else:
                text += f"• \"{_escape_md(m['question'])}\" → {_escape_md(m['answer'])} \\({_escape_md(m['rule'])}\\)\n"

    text += f"\nThis week's focus: *{_escape_md(category)}* \\(Day {day}/7\\)"

    if hasattr(update_or_context, 'bot'):
        await update_or_context.bot.send_message(
            chat_id=chat_id, text=text, parse_mode="MarkdownV2",
            reply_markup=REPLY_KEYBOARD,
        )
    else:
        await update_or_context.effective_message.reply_text(
            text=text, parse_mode="MarkdownV2",
            reply_markup=REPLY_KEYBOARD,
        )

    # Write back updated cards to GitHub
    try:
        await github.write_back_cards(
            session["all_cards"],
            session["pre_table"],
            session["post_table"],
            session["filepath"],
            is_phrases=(week == 7),
        )
    except Exception as e:
        logger.error(f"Failed to write back cards: {e}")

    # Clean up session
    if chat_id in sessions:
        del sessions[chat_id]


def _escape_md(text: str) -> str:
    """Escape special characters for MarkdownV2."""
    if not text:
        return ""
    special = r"_*[]()~`>#+-=|{}.!\\"
    return re.sub(f"([{re.escape(special)}])", r"\\\1", str(text))


def _get_push_time_str() -> str:
    """Get push time display string."""
    if bot_config.get("paused"):
        return "paused"
    h = bot_config.get("push_hour", 9)
    m = bot_config.get("push_minute", 0)
    return f"{h:02d}:{m:02d}"


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
        f"Practice your English grammar with daily drills\\!\n\n"
        f"Current week: *{_escape_md(category)}* \\(Day {day}/7\\)\n\n"
        f"Commands:\n"
        f"/settings \\- Change push time & card count\n"
        f"/status \\- Current week & stats\n"
        f"/stop \\- Pause daily pushes\n"
        f"/resume \\- Resume daily pushes\n\n"
        f"Tap *Practice* to start a drill session\\!"
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
        total = len(cards)
        new_count = sum(1 for c in cards if c["status"] == "new")
        again_count = sum(1 for c in cards if c["status"] == "again")
        good_count = sum(1 for c in cards if c["status"] == "good")
        easy_count = sum(1 for c in cards if c["status"] == "easy")
        retired_count = sum(1 for c in cards if c["status"] == "retired")

        text = (
            f"📊 *Status*\n\n"
            f"Week: *{_escape_md(category)}* \\(Day {day}/7\\)\n\n"
            f"Cards: {total} total\n"
            f"🆕 New: {new_count}\n"
            f"🔴 Again: {again_count}\n"
            f"🟡 Good: {good_count}\n"
            f"🟢 Easy: {easy_count}\n"
            f"✅ Retired: {retired_count}\n\n"
            f"Push: {_get_push_time_str()}\n"
            f"Cards per session: {bot_config.get('cards_per_session', 5)}"
        )
    except Exception as e:
        logger.error(f"Status error: {e}")
        text = f"❌ Error fetching status: {_escape_md(str(e))}"

    await update.message.reply_text(
        text=text, parse_mode="MarkdownV2", reply_markup=REPLY_KEYBOARD,
    )


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return

    args = context.args
    if not args:
        text = (
            f"⚙️ *Settings*\n\n"
            f"Current: {bot_config.get('cards_per_session', 5)} cards at "
            f"{bot_config.get('push_hour', 9):02d}:{bot_config.get('push_minute', 0):02d}\n\n"
            f"Usage:\n"
            f"`/settings 5 cards at 9:00`\n"
            f"`/settings 3 cards`\n"
            f"`/settings at 8:30`"
        )
        await update.message.reply_text(text=text, parse_mode="MarkdownV2")
        return

    text = " ".join(args).lower()

    # Parse card count
    count_match = re.search(r"(\d+)\s*cards?", text)
    if count_match:
        count = int(count_match.group(1))
        if 1 <= count <= 20:
            bot_config["cards_per_session"] = count

    # Parse time
    time_match = re.search(r"(?:at\s+)?(\d{1,2}):(\d{2})", text)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            bot_config["push_hour"] = hour
            bot_config["push_minute"] = minute
            # Reschedule
            _apply_schedule()

    # Save config
    try:
        await github.save_config(bot_config)
    except Exception as e:
        logger.error(f"Failed to save config: {e}")

    await update.message.reply_text(
        text=(
            f"✅ Updated\\!\n"
            f"Cards: {bot_config['cards_per_session']}\n"
            f"Push time: {bot_config['push_hour']:02d}:{bot_config['push_minute']:02d}"
        ),
        parse_mode="MarkdownV2",
        reply_markup=REPLY_KEYBOARD,
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
    await update.message.reply_text("⏸ Daily pushes paused. /resume to restart.",
                                     reply_markup=REPLY_KEYBOARD)


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update):
        return
    bot_config["paused"] = False
    try:
        await github.save_config(bot_config)
    except Exception as e:
        logger.error(f"Failed to save config: {e}")
    _apply_schedule()
    await update.message.reply_text(
        f"▶️ Daily pushes resumed at {bot_config.get('push_hour', 9):02d}:{bot_config.get('push_minute', 0):02d}.",
        reply_markup=REPLY_KEYBOARD,
    )


# ── Practice Session ──────────────────────────────────────────────

async def start_practice(update_or_context, chat_id: int):
    """Start a new drill session."""
    global sessions

    week = get_week_number()
    try:
        cards, pre_table, post_table, filepath = await github.fetch_cards(week)
    except Exception as e:
        logger.error(f"Failed to fetch cards: {e}")
        if hasattr(update_or_context, 'bot'):
            await update_or_context.bot.send_message(
                chat_id=chat_id,
                text=f"❌ Failed to fetch cards: {e}",
            )
        else:
            await update_or_context.effective_message.reply_text(
                f"❌ Failed to fetch cards: {e}",
            )
        return

    count = bot_config.get("cards_per_session", 5)
    selected = select_cards(cards, count)

    if not selected:
        text = "No cards available for practice today! All cards may be retired or not yet due."
        if hasattr(update_or_context, 'bot'):
            await update_or_context.bot.send_message(chat_id=chat_id, text=text,
                                                       reply_markup=REPLY_KEYBOARD)
        else:
            await update_or_context.effective_message.reply_text(text, reply_markup=REPLY_KEYBOARD)
        return

    session = {
        "week_number": week,
        "all_cards": cards,
        "selected_cards": selected,
        "pre_table": pre_table,
        "post_table": post_table,
        "filepath": filepath,
        "current_index": 0,
        "correct_count": 0,
        "mistakes": [],
        "awaiting_answer": False,
    }
    sessions[chat_id] = session

    await send_card(update_or_context, chat_id, session)


async def handle_practice_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the Practice reply keyboard button."""
    if not is_authorized(update):
        return

    chat_id = update.effective_user.id
    if chat_id in sessions:
        await update.message.reply_text(
            "You already have an active session! Finish it first or wait for it to end.",
            reply_markup=REPLY_KEYBOARD,
        )
        return

    await start_practice(update, chat_id)


async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user's answer to a card."""
    if not is_authorized(update):
        return

    chat_id = update.effective_user.id
    session = sessions.get(chat_id)
    if not session or not session.get("awaiting_answer"):
        return

    session["awaiting_answer"] = False
    user_answer = update.message.text.strip()
    card = session["selected_cards"][session["current_index"]]

    if card["type"] == "phrase":
        # No auto-judging — just show the answer
        await show_result(update, card, user_answer, None)
    else:
        is_correct = check_answer(user_answer, card["answer"])
        if is_correct:
            session["correct_count"] += 1
        else:
            session["mistakes"].append(card)
        await show_result(update, card, user_answer, is_correct)


async def handle_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Again/Good/Easy rating buttons."""
    query = update.callback_query
    await query.answer()

    chat_id = query.from_user.id
    session = sessions.get(chat_id)
    if not session:
        return

    data = query.data  # e.g., "rate_again_5_0"
    parts = data.split("_")
    rating = parts[1]  # again, good, easy

    # Update card status
    card = session["selected_cards"][session["current_index"]]
    update_card_status(card, rating)

    # Also update in all_cards list
    for i, c in enumerate(session["all_cards"]):
        if c["num"] == card["num"]:
            session["all_cards"][i] = card
            break

    # Move to next card
    session["current_index"] += 1

    if session["current_index"] >= len(session["selected_cards"]):
        # Session complete
        await show_summary(context, chat_id, session)
    else:
        await send_card(context, chat_id, session)


# ── Scheduled Push ────────────────────────────────────────────────

async def scheduled_push(context: ContextTypes.DEFAULT_TYPE):
    """Send daily drill push."""
    if bot_config.get("paused"):
        return
    logger.info("Sending scheduled grammar drill push")
    await start_practice(context, USER_ID)


def _apply_schedule():
    """Apply/update the daily push schedule."""
    global scheduler
    if not scheduler:
        return

    # Remove existing job if any
    if scheduler.get_job("daily_push"):
        scheduler.remove_job("daily_push")

    if bot_config.get("paused"):
        return

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


# ── Application Setup ─────────────────────────────────────────────

async def post_init(app: Application):
    """Initialize after application starts."""
    global github, scheduler, bot_config

    print(f"Grammar bot post_init: USER_ID={USER_ID}, TIMEZONE={TIMEZONE}")
    print(f"Grammar bot post_init: OBSIDIAN_GITHUB_TOKEN={'set' if os.getenv('OBSIDIAN_GITHUB_TOKEN') else 'NOT SET'}")

    try:
        github = GitHubHandler()
    except Exception as e:
        print(f"Grammar bot ERROR: GitHubHandler init failed: {e}")
        logger.error(f"GitHubHandler init failed: {e}")
        github = None

    # Load config from GitHub
    if github:
        try:
            bot_config = await github.fetch_config()
            logger.info(f"Loaded config: {bot_config}")
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            bot_config = {"push_hour": 9, "push_minute": 0, "cards_per_session": 5, "paused": False}
    else:
        bot_config = {"push_hour": 9, "push_minute": 0, "cards_per_session": 5, "paused": False}

    # Start scheduler
    tz = pytz.timezone(TIMEZONE)
    scheduler = AsyncIOScheduler(timezone=tz, misfire_grace_time=120)
    _apply_schedule()
    scheduler.start()

    print(f"Grammar Drill Bot initialized successfully")
    logger.info("Grammar Drill Bot initialized")


def main():
    if not BOT_TOKEN:
        print("ERROR: GRAMMAR_BOT_TOKEN not set")
        return

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # Command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("resume", cmd_resume))

    # Callback handler for rating buttons
    app.add_handler(CallbackQueryHandler(handle_rating, pattern=r"^rate_"))

    # Practice button (reply keyboard)
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r"^Practice$") & ~filters.COMMAND,
        handle_practice_button,
    ))

    # Answer handler (any text when awaiting answer)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_answer,
    ))

    print("Grammar Drill Bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
