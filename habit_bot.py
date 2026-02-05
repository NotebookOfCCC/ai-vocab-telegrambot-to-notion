"""
Daily Task Reminder Bot

A simplified Telegram bot for daily task reminders with:
- Consolidated schedule view (one message with timeline + tasks)
- Smart category handling (Life/Health tasks show in timeline only)
- Number-based task completion (reply "1 3" to mark tasks done)
- AI-powered natural language task parsing (Haiku)
- Evening wind-down reminders
- Monthly auto-cleanup of old tasks
- Integration with Notion Calendar for time blocking

All tasks come from Notion databases (Recurring Blocks + Reminders).

Commands:
- /tasks: View today's consolidated schedule
- /stop, /resume: Pause/resume reminders
- /status: Bot status

Mark tasks done: Reply with numbers like "1 3" to mark tasks #1 and #3 as done.
Add new tasks: Send natural language like "明天下午3点开会" to create tasks.

Environment variables required:
- HABITS_BOT_TOKEN: Telegram bot token
- HABITS_USER_ID: Your Telegram user ID
- NOTION_API_KEY: Notion integration token
- HABITS_TRACKING_DB_ID: Notion database for daily tracking
- HABITS_REMINDERS_DB_ID: Notion database for reminders/tasks
- RECURRING_BLOCKS_DB_ID: Notion database for recurring time blocks (optional)
- ANTHROPIC_API_KEY: Claude API key for AI task parsing (optional)
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
from telegram.ext import MessageHandler, filters
import anthropic
from datetime import datetime, timedelta
import json

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
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
TIMEZONE = os.getenv("TIMEZONE", "Europe/London")

# Global state
habit_handler = None
youtube_handler = None
scheduler = None
application = None
is_paused = False


# Store current actionable tasks for number-based completion
current_actionable_tasks = []

# AI client for task parsing
ai_client = None


def init_ai_client():
    """Initialize Anthropic client for AI task parsing."""
    global ai_client
    if ANTHROPIC_API_KEY:
        ai_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        logger.info("AI task parser initialized (Haiku)")
    else:
        logger.warning("ANTHROPIC_API_KEY not set - using regex parser fallback")


def parse_task_with_ai(text: str, timezone: str = "Europe/London") -> dict:
    """Parse task using Claude Haiku for accurate natural language understanding.

    Cost: ~$0.001 per task (very cheap)

    Args:
        text: Natural language task description
        timezone: Timezone for date calculations

    Returns:
        Dictionary with task, date, start_time, end_time, category, priority
    """
    if not ai_client:
        # Fallback to regex parser
        from task_parser import TaskParser
        parser = TaskParser(timezone)
        return parser.parse(text)

    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")
    tomorrow_str = (today + timedelta(days=1)).strftime("%Y-%m-%d")

    prompt = f"""Parse this task and extract structured information.

Task: "{text}"

Today's date: {today_str} ({today.strftime("%A")})
Tomorrow: {tomorrow_str}

Return a JSON object with these fields:
- task: Clean task description (just the action, not time/date info)
- date: Date in YYYY-MM-DD format (use {today_str} for "today", "this afternoon", "tonight", etc.)
- start_time: Start time in HH:MM format (24-hour), null if not specified
- end_time: End time in HH:MM format (24-hour), null if not specified
- category: One of Work, Life, Health, Study, Other
- priority: One of High, Mid, Low

Examples:
- "4 o'clock to 5 o'clock this afternoon to send a job application" → task: "Send a job application", date: "{today_str}", start_time: "16:00", end_time: "17:00", category: "Work"
- "明天下午3点开会" → task: "开会", date: "{tomorrow_str}", start_time: "15:00", end_time: "17:00", category: "Work"
- "tonight 8pm call mom" → task: "Call mom", date: "{today_str}", start_time: "20:00", end_time: null, category: "Life"

Return ONLY the JSON object, no other text."""

    try:
        response = ai_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )

        result_text = response.content[0].text.strip()

        # Parse JSON from response
        # Handle case where response might have markdown code blocks
        if "```json" in result_text:
            result_text = result_text.split("```json")[1].split("```")[0]
        elif "```" in result_text:
            result_text = result_text.split("```")[1].split("```")[0]

        parsed = json.loads(result_text)

        # Ensure all required fields exist
        return {
            "task": parsed.get("task", text),
            "date": parsed.get("date"),
            "start_time": parsed.get("start_time"),
            "end_time": parsed.get("end_time"),
            "category": parsed.get("category", "Other"),
            "priority": parsed.get("priority", "Mid"),
            "success": True
        }

    except Exception as e:
        logger.error(f"AI task parsing failed: {e}, falling back to regex")
        # Fallback to regex parser
        from task_parser import TaskParser
        parser = TaskParser(timezone)
        return parser.parse(text)


def get_category_emoji(category: str) -> str:
    """Get emoji for task category."""
    emojis = {
        "study": "📚",
        "work": "💼",
        "life": "👨‍👩‍👧",
        "health": "😴",
        "other": "📌"
    }
    return emojis.get((category or "other").lower(), "📌")


def build_schedule_message(schedule: dict, show_all: bool = False, is_morning: bool = False) -> str:
    """Build a consolidated schedule message.

    Args:
        schedule: Output from habit_handler.get_today_schedule()
        show_all: If True, show all tasks. If False, only upcoming/unfinished.
        is_morning: If True, show full day view with motivational message.

    Returns:
        Formatted message string
    """
    global current_actionable_tasks
    from datetime import datetime

    lines = []
    current_hour = datetime.now().hour

    # Greeting
    if is_morning:
        lines.append("🌅 Good morning! Every day is a fresh start.\n")
    else:
        lines.append("⏰ Schedule Check-in\n")

    # Timeline section
    timeline = schedule.get("timeline", [])
    if timeline:
        lines.append("📅 Today's Schedule:")
        lines.append("┌─────────────────────────────")

        for task in timeline:
            start = task.get("start_time", "")
            end = task.get("end_time", "")
            text = task.get("text", "")
            category = task.get("category", "")
            emoji = get_category_emoji(category)

            # Format time range
            if start and end:
                time_str = f"{start}-{end}"
            elif start:
                time_str = start
            else:
                time_str = "All day"

            # Check if this is upcoming or past
            task_hour = int(start.split(":")[0]) if start else 0
            is_past = task_hour < current_hour and not show_all

            # Skip past Life/Health tasks in check-ins (they happened automatically)
            if is_past and (category or "").lower() in ["life", "health"]:
                continue

            # Mark done tasks
            done_mark = " ✅" if task.get("done") else ""

            lines.append(f"│ {time_str}  {emoji} {text}{done_mark}")

        lines.append("└─────────────────────────────")
        lines.append("")

    # Actionable tasks section (numbered for easy completion)
    actionable = schedule.get("actionable_tasks", [])
    unfinished = [t for t in actionable if not t.get("done")]
    finished = [t for t in actionable if t.get("done")]

    # Store for number-based completion
    current_actionable_tasks = unfinished.copy()

    if unfinished:
        lines.append("📝 Tasks needing action:")
        for i, task in enumerate(unfinished, 1):
            emoji = get_category_emoji(task.get("category"))
            # Format time for actionable tasks
            start = task.get("start_time", "")
            end = task.get("end_time", "")
            if start and end:
                time_str = f" {start}-{end}"
            elif start:
                time_str = f" {start}"
            else:
                time_str = ""
            lines.append(f"  {i}. {emoji} {task.get('text', '')}{time_str}")

        lines.append("")
        lines.append("Reply with numbers to mark done (e.g., \"1 3\")")

    # Show completed count
    if finished:
        lines.append(f"\n✅ Completed: {len(finished)}/{len(actionable)} tasks")

    # All done message
    if not unfinished:
        lines.append("\n🎉 All tasks done today! Great work!")

    return "\n".join(lines)


def build_evening_message(schedule: dict) -> str:
    """Build evening wind-down message."""
    lines = []
    lines.append("🌙 Time to wind down...\n")

    # Check what's done
    actionable = schedule.get("actionable_tasks", [])
    finished = [t for t in actionable if t.get("done")]
    unfinished = [t for t in actionable if not t.get("done")]

    if finished:
        lines.append(f"✅ Great job! You completed {len(finished)} task(s) today.")

    if unfinished:
        lines.append(f"\n⏳ Still pending ({len(unfinished)}):")
        for t in unfinished[:3]:  # Show max 3
            lines.append(f"  • {t.get('text', '')}")
        if len(unfinished) > 3:
            lines.append(f"  ... and {len(unfinished) - 3} more")

    lines.append("\n😴 Rest well and recharge for tomorrow!")

    return "\n".join(lines)


async def send_morning_reminder():
    """Send morning reminder with consolidated schedule."""
    global is_paused

    if is_paused:
        logger.info("Habits bot paused, skipping morning reminder")
        return

    if not HABITS_USER_ID:
        logger.error("HABITS_USER_ID not configured")
        return

    try:
        # Get today's schedule
        schedule = habit_handler.get_today_schedule()

        # Build consolidated message
        message = build_schedule_message(schedule, show_all=True, is_morning=True)

        # Send schedule
        await application.bot.send_message(
            chat_id=HABITS_USER_ID,
            text=message
        )

        logger.info("Sent morning reminder")

    except Exception as e:
        logger.error(f"Error sending morning reminder: {e}")


async def send_practice_checkin():
    """Send practice check-in with consolidated schedule (time-aware)."""
    global is_paused

    if is_paused:
        logger.info("Habits bot paused, skipping check-in")
        return

    if not HABITS_USER_ID:
        return

    try:
        # Get today's schedule
        schedule = habit_handler.get_today_schedule()

        # Check if all actionable tasks are done
        actionable = schedule.get("actionable_tasks", [])
        all_done = all(t.get("done") for t in actionable)

        if all_done:
            await application.bot.send_message(
                chat_id=HABITS_USER_ID,
                text="🎉 Check-in: All tasks done today! Great work!"
            )
            return

        # Build consolidated message (only show upcoming/unfinished)
        message = build_schedule_message(schedule, show_all=False, is_morning=False)

        await application.bot.send_message(
            chat_id=HABITS_USER_ID,
            text=message
        )
        logger.info("Sent practice check-in")

    except Exception as e:
        logger.error(f"Error sending check-in: {e}")


async def send_evening_winddown():
    """Send evening wind-down reminder at 10 PM."""
    global is_paused

    if is_paused:
        logger.info("Habits bot paused, skipping evening winddown")
        return

    if not HABITS_USER_ID:
        return

    try:
        schedule = habit_handler.get_today_schedule()
        message = build_evening_message(schedule)

        await application.bot.send_message(
            chat_id=HABITS_USER_ID,
            text=message
        )
        logger.info("Sent evening winddown")

    except Exception as e:
        logger.error(f"Error sending evening winddown: {e}")


# Weekly summary disabled - using recurring blocks instead of built-in habit tracking
# async def send_weekly_summary():
#     """Send weekly progress summary on Sunday."""
#     pass


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
• 6:00 AM - Create recurring blocks (next 7 days)
• 8:00 AM - Morning schedule
• 12:00 PM - Check-in
• 7:00 PM - Check-in
• 10:00 PM - Evening wind-down
• Monthly - Auto-cleanup old tasks

📋 One Message, Full Schedule:
Your day's timeline + actionable tasks in one view.
Life/Health tasks (Family Time, Sleep) show in timeline only.

✅ Mark Tasks Done:
Reply with numbers like "1 3" to mark done.

💬 Add New Tasks (AI-powered):
Send natural language like "4pm to 5pm job application"
AI parses date, time, category automatically.

Commands:
/tasks - Today's schedule
/stop /resume /status"""

    await update.message.reply_text(info_message)


async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /tasks command - show today's consolidated schedule."""
    if str(update.effective_user.id) != HABITS_USER_ID:
        await update.message.reply_text("Sorry, this bot is private.")
        return

    schedule = habit_handler.get_today_schedule()
    message = build_schedule_message(schedule, show_all=True, is_morning=False)
    await update.message.reply_text(message)




# Video and weekly summary commands disabled - using recurring blocks instead
# async def video_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
#     pass
# async def week_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
#     pass


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
    ai_status = "Haiku" if ai_client else "regex fallback"

    message = f"""Habit Bot Status

Status: {status}
Timezone: {TIMEZONE}
Scheduled jobs: {len(jobs)}
Task parser: {ai_status}

Commands: /tasks /stop /resume"""

    await update.message.reply_text(message)


# /blocks command removed - recurring blocks are created automatically at 6am for next 7 days


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle natural language task input OR number-based task completion."""
    global current_actionable_tasks

    if str(update.effective_user.id) != HABITS_USER_ID:
        await update.message.reply_text("Sorry, this bot is private.")
        return

    text = update.message.text.strip()

    # Check if this is a number-based completion (e.g., "1 3" or "1, 2, 3")
    import re
    numbers = re.findall(r'\d+', text)

    # If message is primarily numbers, treat as task completion
    if numbers and len(text.replace(" ", "").replace(",", "")) == sum(len(n) for n in numbers):
        if not current_actionable_tasks:
            await update.message.reply_text("No tasks loaded. Use /habits first to see your tasks.")
            return

        completed = []
        errors = []

        for num_str in numbers:
            num = int(num_str)
            if 1 <= num <= len(current_actionable_tasks):
                task = current_actionable_tasks[num - 1]
                task_id = task.get("id")
                task_name = task.get("text", "Task")

                # Mark as done (all tasks are from Notion now)
                habit_handler.mark_task_done(task_id)
                completed.append(f"✅ {task_name}")
            else:
                errors.append(f"#{num} not found")

        # Send confirmation
        if completed:
            await update.message.reply_text("Marked as done:\n" + "\n".join(completed))

            # Refresh the actionable tasks list
            schedule = habit_handler.get_today_schedule()
            current_actionable_tasks = [t for t in schedule.get("actionable_tasks", []) if not t.get("done")]

        if errors:
            await update.message.reply_text("Errors: " + ", ".join(errors))

        return

    # Otherwise, treat as new task input - use AI parser
    parsed = parse_task_with_ai(text, TIMEZONE)
    logger.info(f"AI Parsed task: {parsed}")

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
        # Build confirmation message
        lines = ["✅ 已添加任务！", ""]
        if parsed.get("start_time"):
            time_str = f"• 时间：{parsed.get('date', '今天')} {parsed['start_time']}"
            if parsed.get("end_time"):
                time_str += f"-{parsed['end_time']}"
            lines.append(time_str)
        elif parsed.get("date"):
            lines.append(f"• 日期：{parsed['date']}")
        lines.append(f"• 事项：{parsed.get('task', text)}")
        lines.append(f"• 类别：{parsed.get('category', 'Other')}")
        await update.message.reply_text("\n".join(lines))
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


async def run_monthly_cleanup():
    """Run monthly cleanup of old reminders."""
    try:
        result = habit_handler.cleanup_old_reminders(months_old=3, max_items=1000)
        logger.info(f"Monthly cleanup: archived={result.get('archived', 0)}, total={result.get('total', 0)}")

        if result.get("archived", 0) > 0 and HABITS_USER_ID:
            await application.bot.send_message(
                chat_id=HABITS_USER_ID,
                text=f"🧹 Monthly cleanup: Archived {result['archived']} old reminder(s)"
            )

    except Exception as e:
        logger.error(f"Error in monthly cleanup: {e}")


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

    # Evening wind-down at 10:00 PM (instead of regular check-in)
    scheduler.add_job(
        send_evening_winddown,
        CronTrigger(hour=22, minute=0, timezone=TIMEZONE),
        id="evening_winddown",
        name="Evening Wind-down (22:00)"
    )

    # Weekly summary disabled - using recurring blocks instead
    # scheduler.add_job(
    #     send_weekly_summary,
    #     CronTrigger(day_of_week="sun", hour=20, minute=0, timezone=TIMEZONE),
    #     id="weekly_summary",
    #     name="Weekly Summary (Sunday 20:00)"
    # )

    # Monthly cleanup on 1st of each month at 3 AM
    scheduler.add_job(
        run_monthly_cleanup,
        CronTrigger(day=1, hour=3, minute=0, timezone=TIMEZONE),
        id="monthly_cleanup",
        name="Monthly Cleanup (1st of month, 3:00)"
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

    # Initialize AI client for task parsing
    init_ai_client()
    if ai_client:
        print("AI task parser initialized (Haiku) - accurate natural language parsing")
    else:
        print("AI not configured - using regex fallback for task parsing")

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
    application.add_handler(CommandHandler("tasks", tasks_command))
    # video and week commands disabled
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("resume", resume_command))
    application.add_handler(CommandHandler("status", status_command))
    # /blocks command removed - recurring blocks created automatically
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
