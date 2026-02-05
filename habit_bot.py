"""
Daily Habit Reminder Bot

A Telegram bot for daily English practice reminders with:
- Morning video recommendations from YouTube
- Scheduled check-ins at 12:00, 19:00, 22:00
- Weekly progress summaries on Sundays
- Task management with Done/Not Yet buttons
- Integration with Notion for habit tracking
- Natural language task input with time blocking (shows in Notion Calendar)

Commands:
- /habits: View today's tasks
- /video: Get a random practice video
- /week: Weekly progress summary
- /stop, /resume: Pause/resume reminders
- /status: Bot status

Natural language: Just send a message like "明天下午3点开会" to create a task with time block.

Environment variables required:
- HABITS_BOT_TOKEN: Telegram bot token
- HABITS_USER_ID: Your Telegram user ID
- NOTION_API_KEY: Notion integration token
- HABITS_TRACKING_DB_ID: Notion database for daily tracking
- HABITS_REMINDERS_DB_ID: Notion database for reminders/tasks
- YOUTUBE_API_KEY: YouTube Data API key (optional)
- TIMEZONE: Timezone for scheduling (default: Europe/London)
"""
import os
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from habit_handler import HabitHandler
from youtube_handler import YouTubeHandler
from telegram.ext import MessageHandler, filters

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
HABITS_BOT_TOKEN = os.getenv("HABITS_BOT_TOKEN")
HABITS_USER_ID = os.getenv("HABITS_USER_ID", "").strip()
NOTION_KEY = os.getenv("NOTION_API_KEY")
TRACKING_DB_ID = os.getenv("HABITS_TRACKING_DB_ID")
REMINDERS_DB_ID = os.getenv("HABITS_REMINDERS_DB_ID")
RECURRING_BLOCKS_DB_ID = os.getenv("RECURRING_BLOCKS_DB_ID")  # Optional: Notion DB for recurring blocks
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TIMEZONE = os.getenv("TIMEZONE", "Europe/London")

# Global state
habit_handler = None
youtube_handler = None
scheduler = None
application = None
is_paused = False


def get_task_buttons(task_id: str) -> InlineKeyboardMarkup:
    """Generate Done / Not Yet buttons for a task."""
    keyboard = [[
        InlineKeyboardButton("Done", callback_data=f"done_{task_id}"),
        InlineKeyboardButton("Not Yet", callback_data=f"notyet_{task_id}")
    ]]
    return InlineKeyboardMarkup(keyboard)


async def send_task_messages(chat_id: str, include_finished: bool = True):
    """Send individual task messages.

    Args:
        chat_id: Telegram chat ID
        include_finished: If True, show all tasks. If False, only show unfinished.
    """
    habit = habit_handler.get_or_create_today_habit()
    completed_tasks = habit.get("completed_tasks", [])

    # Built-in habits: Listened, Spoke
    builtin_tasks = [
        {"id": "listened", "text": "Listened to English", "done": habit.get("listened", False)},
        {"id": "spoke", "text": "Spoke in English", "done": habit.get("spoke", False)},
    ]

    # Custom tasks from Notion
    reminders = habit_handler.get_all_reminders()
    custom_tasks = []
    for r in reminders:
        custom_tasks.append({
            "id": r["id"],
            "text": r["text"],
            "done": r["id"] in completed_tasks
        })

    all_tasks = builtin_tasks + custom_tasks

    # Separate finished and unfinished
    finished = [t for t in all_tasks if t["done"]]
    unfinished = [t for t in all_tasks if not t["done"]]

    # Send finished tasks as summary (if any and if include_finished)
    if finished and include_finished:
        finished_list = "\n".join([f"✅ {t['text']}" for t in finished])
        await application.bot.send_message(
            chat_id=chat_id,
            text=f"🎯 Completed:\n{finished_list}"
        )

    # Send each unfinished task as separate message with buttons
    for task in unfinished:
        reply_markup = get_task_buttons(task["id"])
        await application.bot.send_message(
            chat_id=chat_id,
            text=f"📌 {task['text']}",
            reply_markup=reply_markup
        )

    # If all done
    if not unfinished:
        await application.bot.send_message(
            chat_id=chat_id,
            text="🎉 All tasks done today! Great work!"
        )


async def send_morning_reminder():
    """Send morning reminder with video and tasks."""
    global is_paused

    if is_paused:
        logger.info("Habits bot paused, skipping morning reminder")
        return

    if not HABITS_USER_ID:
        logger.error("HABITS_USER_ID not configured")
        return

    try:
        # Get random video
        video = youtube_handler.get_random_video() if youtube_handler else None

        # Send greeting
        await application.bot.send_message(
            chat_id=HABITS_USER_ID,
            text="🌅 Good morning!"
        )

        # Send video if available
        if video:
            message = f"""🎧 Today's listening practice:
{video.get('playlist_name', 'Video')}: {video.get('title', 'Untitled')}

{video.get('url', '')}"""
            await application.bot.send_message(
                chat_id=HABITS_USER_ID,
                text=message
            )
            # Save video URL
            habit_handler.update_habit("listened", False, video_url=video.get("url"))

        # Send task messages
        await send_task_messages(HABITS_USER_ID, include_finished=False)
        logger.info("Sent morning reminder")

    except Exception as e:
        logger.error(f"Error sending morning reminder: {e}")


async def send_practice_checkin():
    """Send practice check-in - only unfinished tasks."""
    global is_paused

    if is_paused:
        logger.info("Habits bot paused, skipping check-in")
        return

    if not HABITS_USER_ID:
        return

    try:
        habit = habit_handler.get_or_create_today_habit()
        completed_tasks = habit.get("completed_tasks", [])

        # Check if all built-in tasks are done
        builtin_done = habit.get("listened", False) and habit.get("spoke", False)

        # Check if all custom tasks are done
        reminders = habit_handler.get_all_reminders()
        custom_done = all(r["id"] in completed_tasks for r in reminders)

        # If everything is done, just send encouragement
        if builtin_done and custom_done:
            await application.bot.send_message(
                chat_id=HABITS_USER_ID,
                text="🎉 Check-in: All tasks done today! Great work!"
            )
            return

        # Send header
        await application.bot.send_message(
            chat_id=HABITS_USER_ID,
            text="⏰ Practice Check-in\n\nHave you finished these?"
        )

        # Send only unfinished tasks
        await send_task_messages(HABITS_USER_ID, include_finished=False)
        logger.info("Sent practice check-in")

    except Exception as e:
        logger.error(f"Error sending check-in: {e}")


async def send_weekly_summary():
    """Send weekly progress summary on Sunday."""
    global is_paused

    if is_paused:
        logger.info("Habits bot paused, skipping weekly summary")
        return

    if not HABITS_USER_ID:
        return

    try:
        stats = habit_handler.get_weekly_stats()

        listening = stats.get("listening_days", 0)
        speaking = stats.get("speaking_days", 0)
        videos = stats.get("videos_watched", 0)
        streak = stats.get("streak", 0)
        total = stats.get("total_days", 7)

        listen_emoji = " ✅" if listening >= 5 else ""
        speak_emoji = " ✅" if speaking >= 5 else ""

        message = f"""Weekly Progress Report

Listening: {listening}/{total} days{listen_emoji}
Speaking: {speaking}/{total} days{speak_emoji}
Videos watched: {videos}
Current streak: {streak} days

"""
        if listening >= 5 and speaking >= 5:
            message += "Great work this week!"
        elif listening >= 3 or speaking >= 3:
            message += "Good progress! Keep it up!"
        else:
            message += "Let's do better next week!"

        await application.bot.send_message(
            chat_id=HABITS_USER_ID,
            text=message
        )
        logger.info("Sent weekly summary")

    except Exception as e:
        logger.error(f"Error sending weekly summary: {e}")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    user_id = str(update.effective_user.id)
    logger.info(f"/start from user {user_id}, expected {HABITS_USER_ID}")

    if user_id != HABITS_USER_ID:
        await update.message.reply_text(
            f"Sorry, this bot is private.\n\nYour ID: {user_id}"
        )
        return

    info_message = f"""Daily Practice Reminder Bot

Schedule ({TIMEZONE}):
• 6:00 AM - Create recurring time blocks
• 8:00 AM - Morning video + tasks
• 12:00 PM - Check-in
• 7:00 PM - Check-in
• 10:00 PM - Check-in
• Sunday 8 PM - Weekly summary

💬 Natural Language Tasks:
Just send a message like "今晚6点和Justin约饭" or "明天下午3点到5点听力练习" and I'll automatically parse time, priority, and category!

Time blocks will appear in your Notion Calendar.

Commands:
/habits - Today's tasks status
/blocks - Create today's recurring blocks now
/video - Get a random practice video
/week - Weekly progress summary
/stop - Pause reminders
/resume - Resume reminders
/status - Bot status"""

    await update.message.reply_text(info_message)


async def habits_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /habits command - show today's tasks."""
    if str(update.effective_user.id) != HABITS_USER_ID:
        await update.message.reply_text("Sorry, this bot is private.")
        return

    await update.message.reply_text("📋 Today's Tasks")
    await send_task_messages(update.effective_chat.id, include_finished=True)




async def video_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /video command - get random video."""
    if str(update.effective_user.id) != HABITS_USER_ID:
        await update.message.reply_text("Sorry, this bot is private.")
        return

    if not youtube_handler:
        await update.message.reply_text("YouTube not configured. Set YOUTUBE_API_KEY.")
        return

    video = youtube_handler.get_random_video()

    if video:
        message = f"""{video.get('playlist_name', 'Video')}:
{video.get('title', 'Untitled')}

{video.get('url', '')}"""
        await update.message.reply_text(message)
    else:
        await update.message.reply_text("No videos available. Check playlist configuration.")


async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /week command - show weekly summary."""
    if str(update.effective_user.id) != HABITS_USER_ID:
        await update.message.reply_text("Sorry, this bot is private.")
        return

    stats = habit_handler.get_weekly_stats()

    listening = stats.get("listening_days", 0)
    speaking = stats.get("speaking_days", 0)
    videos = stats.get("videos_watched", 0)
    streak = stats.get("streak", 0)
    total = stats.get("total_days", 7)

    message = f"""Weekly Progress

Listening: {listening}/{total} days
Speaking: {speaking}/{total} days
Videos: {videos}
Streak: {streak} days"""

    await update.message.reply_text(message)


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stop command - pause reminders."""
    global is_paused

    if str(update.effective_user.id) != HABITS_USER_ID:
        await update.message.reply_text("Sorry, this bot is private.")
        return

    is_paused = True
    await update.message.reply_text("Reminders paused. Use /resume to continue.")
    logger.info("Habit reminders paused")


async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /resume command - resume reminders."""
    global is_paused

    if str(update.effective_user.id) != HABITS_USER_ID:
        await update.message.reply_text("Sorry, this bot is private.")
        return

    is_paused = False
    await update.message.reply_text("Reminders resumed!")
    logger.info("Habit reminders resumed")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command - show bot status."""
    if str(update.effective_user.id) != HABITS_USER_ID:
        await update.message.reply_text("Sorry, this bot is private.")
        return

    status = "paused" if is_paused else "active"
    jobs = scheduler.get_jobs() if scheduler else []
    yt_status = "configured" if youtube_handler and YOUTUBE_API_KEY else "not configured"

    message = f"""Habit Bot Status

Status: {status}
Timezone: {TIMEZONE}
Scheduled jobs: {len(jobs)}
YouTube: {yt_status}

Commands: /habits /video /week /stop /resume"""

    await update.message.reply_text(message)


async def blocks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /blocks command - manually create today's recurring blocks."""
    if str(update.effective_user.id) != HABITS_USER_ID:
        await update.message.reply_text("Sorry, this bot is private.")
        return

    await update.message.reply_text("Creating recurring time blocks...")

    import os
    config_path = os.path.join(os.path.dirname(__file__), "schedule_config.json")
    result = habit_handler.create_recurring_blocks(config_path)

    if result.get("error"):
        await update.message.reply_text(f"Error: {result['error']}")
    else:
        source = result.get("source", "unknown")
        source_label = "Notion database" if source == "notion" else "JSON file" if source == "json" else "unknown"
        await update.message.reply_text(
            f"📅 Done! (from {source_label})\n"
            f"• Created: {result.get('created', 0)}\n"
            f"• Skipped: {result.get('skipped', 0)} (already exist or not scheduled today)"
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle natural language task input using FREE regex parser."""
    if str(update.effective_user.id) != HABITS_USER_ID:
        await update.message.reply_text("Sorry, this bot is private.")
        return

    text = update.message.text.strip()

    # Use FREE regex-based parser (no API cost!)
    from task_parser import TaskParser
    parser = TaskParser(TIMEZONE)
    parsed = parser.parse(text)

    # Log parsed result for debugging
    logger.info(f"Parsed task: {parsed}")

    # Create the reminder in Notion
    result = habit_handler.create_reminder(
        text=parsed.get("task", text),
        date=parsed.get("date"),
        start_time=parsed.get("start_time"),
        end_time=parsed.get("end_time"),
        priority=parsed.get("priority"),
        category=parsed.get("category")
    )

    if result["success"]:
        # Send confirmation message
        confirmation = parser.format_confirmation(parsed)
        await update.message.reply_text(confirmation)
    else:
        await update.message.reply_text(f"保存失败: {result.get('error', 'Unknown error')}")


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button presses."""
    query = update.callback_query

    if str(query.from_user.id) != HABITS_USER_ID:
        await query.answer()
        return

    data = query.data
    task_names = {
        "listened": "Listened to English",
        "spoke": "Spoke in English"
    }

    try:
        # Handle "Done" button
        if data.startswith("done_"):
            task_id = data[5:]  # Remove "done_" prefix

            if task_id in task_names:
                # Built-in habit
                habit_handler.update_habit(task_id, True)
                task_name = task_names[task_id]
            else:
                # Custom task
                habit_handler.mark_task_done(task_id)
                reminders = habit_handler.get_all_reminders()
                task_name = next((r["text"] for r in reminders if r["id"] == task_id), "Task")

            await query.answer()
            await query.edit_message_text(f"✅ {task_name}")

        # Handle "Not Yet" button - dismiss but don't mark done
        elif data.startswith("notyet_"):
            task_id = data[7:]  # Remove "notyet_" prefix

            if task_id in task_names:
                task_name = task_names[task_id]
            else:
                reminders = habit_handler.get_all_reminders()
                task_name = next((r["text"] for r in reminders if r["id"] == task_id), "Task")

            await query.answer()
            await query.edit_message_text(f"⏳ {task_name}")

        else:
            await query.answer()

    except Exception as e:
        logger.error(f"Callback error: {e}")
        await query.answer("Error processing request")


async def create_daily_blocks():
    """Create recurring time blocks from schedule config."""
    global is_paused

    if is_paused:
        logger.info("Habits bot paused, skipping daily block creation")
        return

    try:
        import os
        config_path = os.path.join(os.path.dirname(__file__), "schedule_config.json")
        result = habit_handler.create_recurring_blocks(config_path)
        logger.info(f"Daily blocks: created={result.get('created', 0)}, skipped={result.get('skipped', 0)}")

        # Notify user if blocks were created
        if result.get("created", 0) > 0 and HABITS_USER_ID:
            await application.bot.send_message(
                chat_id=HABITS_USER_ID,
                text=f"📅 Created {result['created']} time block(s) for today"
            )

    except Exception as e:
        logger.error(f"Error creating daily blocks: {e}")


async def post_init(app: Application) -> None:
    """Initialize scheduler after application starts."""
    global scheduler

    scheduler = AsyncIOScheduler(timezone=TIMEZONE)

    # Create daily recurring blocks at 6:00 AM
    scheduler.add_job(
        create_daily_blocks,
        CronTrigger(hour=6, minute=0, timezone=TIMEZONE),
        id="daily_blocks",
        name="Daily Blocks (6:00)"
    )

    # Morning reminder at 8:00 AM
    scheduler.add_job(
        send_morning_reminder,
        CronTrigger(hour=8, minute=0, timezone=TIMEZONE),
        id="morning_reminder",
        name="Morning Reminder (8:00)"
    )

    # Check-in at 12:00 PM
    scheduler.add_job(
        send_practice_checkin,
        CronTrigger(hour=12, minute=0, timezone=TIMEZONE),
        id="checkin_noon",
        name="Noon Check-in (12:00)"
    )

    # Check-in at 7:00 PM
    scheduler.add_job(
        send_practice_checkin,
        CronTrigger(hour=19, minute=0, timezone=TIMEZONE),
        id="checkin_evening",
        name="Evening Check-in (19:00)"
    )

    # Check-in at 10:00 PM
    scheduler.add_job(
        send_practice_checkin,
        CronTrigger(hour=22, minute=0, timezone=TIMEZONE),
        id="checkin_night",
        name="Night Check-in (22:00)"
    )

    # Weekly summary on Sunday at 8 PM
    scheduler.add_job(
        send_weekly_summary,
        CronTrigger(day_of_week="sun", hour=20, minute=0, timezone=TIMEZONE),
        id="weekly_summary",
        name="Weekly Summary (Sunday 20:00)"
    )

    scheduler.start()
    logger.info(f"Scheduler started with timezone {TIMEZONE}")

    for job in scheduler.get_jobs():
        next_run = job.next_run_time
        logger.info(f"Job '{job.name}' next run: {next_run}")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors."""
    logger.error(f"Update {update} caused error {context.error}")


def main():
    """Main function to run the habit bot."""
    global habit_handler, youtube_handler, application

    # Validate configuration
    if not HABITS_BOT_TOKEN:
        print("ERROR: HABITS_BOT_TOKEN not set")
        return
    if not HABITS_USER_ID:
        print("ERROR: HABITS_USER_ID not set")
        return
    if not NOTION_KEY:
        print("ERROR: NOTION_API_KEY not set")
        return
    if not TRACKING_DB_ID:
        print("ERROR: HABITS_TRACKING_DB_ID not set")
        return
    if not REMINDERS_DB_ID:
        print("ERROR: HABITS_REMINDERS_DB_ID not set")
        return

    # Initialize handlers
    habit_handler = HabitHandler(NOTION_KEY, TRACKING_DB_ID, REMINDERS_DB_ID, RECURRING_BLOCKS_DB_ID)

    # Initialize YouTube handler (optional)
    if YOUTUBE_API_KEY and YOUTUBE_API_KEY != "your_youtube_api_key_here":
        youtube_handler = YouTubeHandler(YOUTUBE_API_KEY)
        print("YouTube handler initialized")
    else:
        print("YouTube API key not configured - video features disabled")

    # Task parsing uses FREE regex-based parser (no API cost)
    print("Task parser ready - natural language task parsing enabled (FREE)")

    # Test Notion connection
    notion_test = habit_handler.test_connection()
    if notion_test["success"]:
        print(f"Notion connected: Tracking={notion_test['tracking_db']}, Reminders={notion_test['reminders_db']}")
    else:
        print(f"WARNING: Notion connection issue: {notion_test['error']}")

    # Create application
    application = Application.builder().token(HABITS_BOT_TOKEN).post_init(post_init).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("habits", habits_command))
    application.add_handler(CommandHandler("video", video_command))
    application.add_handler(CommandHandler("week", week_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("resume", resume_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("blocks", blocks_command))
    application.add_handler(CallbackQueryHandler(handle_callback))

    # Add message handler for natural language tasks (must be last)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Add error handler
    application.add_error_handler(error_handler)

    # Start polling
    print(f"Habit bot starting with timezone {TIMEZONE}...")
    print("Schedule: 8:00 (morning), 12:00/19:00/22:00 (check-ins), Sunday 20:00 (weekly)")
    print("Send any message to add a task using natural language!")
    print("Press Ctrl+C to stop")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
