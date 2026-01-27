"""
Vocabulary Review Bot
Sends scheduled vocabulary review messages from Notion database.
"""
import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from notion_handler import NotionHandler

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

# Global state
notion_handler = None
scheduler = None
application = None
is_paused = False


def format_entry_for_review(entry: dict, index: int, total: int) -> str:
    """Format a single entry for display in review message."""
    english = entry.get("english", "")
    chinese = entry.get("chinese", "")
    explanation = entry.get("explanation", "")
    example = entry.get("example", "")
    category = entry.get("category", "")

    lines = [f"Review {index}/{total}", "", f"{english}"]

    if chinese:
        lines.append(chinese)

    if explanation:
        lines.extend(["", "Explanation:", explanation])

    if example:
        lines.extend(["", "Example:", example])

    if category:
        lines.extend(["", f"Category: {category}"])

    return "\n".join(lines)


async def send_review_batch(manual: bool = False):
    """Fetch random entries and send review messages.

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
        entries = notion_handler.fetch_random_entries(10)

        if not entries:
            logger.warning("No entries fetched from Notion")
            await application.bot.send_message(
                chat_id=REVIEW_USER_ID,
                text="No vocabulary entries found in the database."
            )
            return

        total = len(entries)
        for i, entry in enumerate(entries, 1):
            message = format_entry_for_review(entry, i, total)
            await application.bot.send_message(
                chat_id=REVIEW_USER_ID,
                text=message
            )

        logger.info(f"Sent {total} review entries to user {REVIEW_USER_ID}")

    except Exception as e:
        logger.error(f"Error sending review batch: {e}")


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

Schedule: 8:00, 13:00, 19:00, 22:00 ({TIMEZONE})
Entries per batch: 10

Commands:
/start - Show this message
/review - Get review batch now
/stop - Pause scheduled reviews
/resume - Resume scheduled reviews
/status - Check bot status
"""
    await update.message.reply_text(info_message)


async def review_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /review command - manual trigger (works even when paused)."""
    user_id = str(update.effective_user.id)
    logger.info(f"/review from user {user_id}")
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
    await update.message.reply_text("Scheduled reviews paused. Use /resume to continue.")
    logger.info("Scheduled reviews paused by user")


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /resume command - resume scheduled reviews."""
    global is_paused

    if str(update.effective_user.id) != REVIEW_USER_ID:
        await update.message.reply_text("Sorry, this bot is private.")
        return

    is_paused = False
    await update.message.reply_text("Scheduled reviews resumed!")
    logger.info("Scheduled reviews resumed by user")


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

Next reviews:
- 8:00
- 13:00
- 19:00
- 22:00
"""
    await update.message.reply_text(status_message)


async def post_init(app: Application) -> None:
    """Initialize scheduler after application starts."""
    global scheduler

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    # Schedule review batches at 8:00, 13:00, 19:00, and 22:00
    scheduler.add_job(
        send_review_batch,
        CronTrigger(hour=8, minute=0, timezone=TIMEZONE),
        id="review_morning",
        name="Morning Review (8:00)"
    )
    scheduler.add_job(
        send_review_batch,
        CronTrigger(hour=13, minute=0, timezone=TIMEZONE),
        id="review_noon",
        name="Noon Review (13:00)"
    )
    scheduler.add_job(
        send_review_batch,
        CronTrigger(hour=19, minute=0, timezone=TIMEZONE),
        id="review_evening",
        name="Evening Review (19:00)"
    )
    scheduler.add_job(
        send_review_batch,
        CronTrigger(hour=22, minute=0, timezone=TIMEZONE),
        id="review_night",
        name="Night Review (22:00)"
    )

    scheduler.start()
    logger.info(f"Scheduler started with timezone {TIMEZONE}")
    logger.info("Scheduled jobs: 8:00, 13:00, 19:00, 22:00")

    # Log next run times for debugging
    for job in scheduler.get_jobs():
        next_run = job.next_run_time
        logger.info(f"Job '{job.name}' next run: {next_run}")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors."""
    logger.error(f"Update {update} caused error {context.error}")


def main():
    """Main function to run the review bot."""
    global notion_handler, application

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

    # Initialize Notion handler
    notion_handler = NotionHandler(NOTION_KEY, NOTION_DB_ID)

    # Test Notion connection
    notion_test = notion_handler.test_connection()
    if notion_test["success"]:
        print(f"Notion connected: {notion_test['database_title']}")
    else:
        print(f"WARNING: Notion connection issue: {notion_test['error']}")

    # Create application
    application = Application.builder().token(REVIEW_BOT_TOKEN).post_init(post_init).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("myid", myid_command))
    application.add_handler(CommandHandler("review", review_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("resume", resume_command))
    application.add_handler(CommandHandler("status", status_command))

    # Add error handler
    application.add_error_handler(error_handler)

    # Start polling
    print(f"Review bot starting with timezone {TIMEZONE}...")
    print("Schedule: 8:00, 13:00, 19:00, 22:00")
    print("Press Ctrl+C to stop")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
