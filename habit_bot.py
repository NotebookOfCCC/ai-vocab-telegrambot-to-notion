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
Edit tasks: Type "edit 1" to edit task #1 (date, time, text, category, or delete).
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
import pytz

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

# Config file for user settings (day boundary, timezone)
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "task_config.json")

def get_default_config() -> dict:
    """Get default config."""
    return {
        "day_boundary": 4,  # 4am - day ends at this hour
        "timezone": TIMEZONE
    }

def load_config() -> dict:
    """Load task config from JSON file, falling back to defaults."""
    default = get_default_config()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
            # Merge with defaults
            return {**default, **config}
        except Exception as e:
            logger.error(f"Error loading config: {e}")
    return default

def save_config(config: dict) -> None:
    """Save task config to JSON file."""
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    logger.info(f"Config saved: {config}")

# Global state
habit_handler = None
scheduler = None
application = None
is_paused = False
task_config = None  # Loaded at startup

# Store current actionable tasks for number-based completion
current_actionable_tasks = []

# Store task being edited (task_id -> task_data)
editing_task = {}

# AI client for task parsing
ai_client = None


def get_effective_date() -> str:
    """Get the effective date considering day boundary.

    If current time is before the day boundary (e.g., 4am),
    treat it as still being "yesterday" for task purposes.

    Returns:
        Date string in YYYY-MM-DD format
    """
    import pytz

    tz = pytz.timezone(task_config.get("timezone", TIMEZONE) if task_config else TIMEZONE)
    now = datetime.now(tz)
    boundary = task_config.get("day_boundary", 4) if task_config else 4

    # If before boundary hour, use yesterday's date
    if now.hour < boundary:
        effective = now - timedelta(days=1)
    else:
        effective = now

    return effective.strftime("%Y-%m-%d")


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
    tz = pytz.timezone(task_config.get("timezone", TIMEZONE) if task_config else TIMEZONE)
    current_hour = datetime.now(tz).hour

    # Timeline section with date header (combines greeting + schedule)
    timeline = schedule.get("timeline", [])
    effective_date = get_effective_date()
    date_display = datetime.strptime(effective_date, "%Y-%m-%d").strftime("%b %d")  # e.g., "Feb 05"

    if is_morning:
        lines.append(f"🌅 Good morning! Schedule for {date_display}:")
    else:
        lines.append(f"📅 Schedule ({date_display}):")

    if timeline:
        # Filter timeline items first
        filtered_timeline = []
        for task in timeline:
            start = task.get("start_time", "")
            category = task.get("category", "")
            task_hour = int(start.split(":")[0]) if start else 0
            is_past = task_hour < current_hour and not show_all

            # Skip past Block tasks in check-ins (they're time blocks, not tasks)
            if is_past and (category or "").lower() == "block":
                continue
            filtered_timeline.append(task)

        # Number the schedule items
        for i, task in enumerate(filtered_timeline, 1):
            start = task.get("start_time", "")
            end = task.get("end_time", "")
            text = task.get("text", "")
            category = (task.get("category") or "").lower()

            # Format time range
            if start and end:
                time_str = f"{start}-{end}"
            elif start:
                time_str = start
            else:
                time_str = "All day"

            # Mark done tasks or show block icon
            if category == "block":
                suffix = " ☀️"  # Sun icon for time blocks
            elif task.get("done"):
                suffix = " ✅"
            else:
                suffix = ""

            lines.append(f"{i}. {time_str}  {text}{suffix}")

        # Separator line between sections
        lines.append("\n─────────────────────────────")

    # Actionable tasks section (numbered for easy completion)
    actionable = schedule.get("actionable_tasks", [])
    unfinished = [t for t in actionable if not t.get("done")]
    finished = [t for t in actionable if t.get("done")]

    # Sort unfinished tasks by start_time
    def get_sort_time(task):
        start = task.get("start_time", "")
        if start:
            try:
                return int(start.replace(":", ""))
            except:
                return 9999
        return 9999  # Tasks without time go to the end

    unfinished.sort(key=get_sort_time)

    # Store for number-based completion
    current_actionable_tasks = unfinished.copy()

    if unfinished:
        lines.append("\n📝 Tasks needing action:")
        for i, task in enumerate(unfinished, 1):
            # Format time for actionable tasks
            start = task.get("start_time", "")
            end = task.get("end_time", "")
            if start and end:
                time_str = f" {start}-{end}"
            elif start:
                time_str = f" {start}"
            else:
                time_str = ""
            lines.append(f"{i}. {task.get('text', '')}{time_str}")

        lines.append("\n→ Mark done: \"1 3\"")

    # Show completed tasks with their own section
    if finished:
        # Sort finished tasks by time too
        finished.sort(key=get_sort_time)

        lines.append("\n✅ Tasks completed:")
        for i, task in enumerate(finished, 1):
            start = task.get("start_time", "")
            end = task.get("end_time", "")
            if start and end:
                time_str = f" {start}-{end}"
            elif start:
                time_str = f" {start}"
            else:
                time_str = ""
            lines.append(f"{i}. {task.get('text', '')}{time_str}")

        # Encouraging message based on progress
        total = len(actionable)
        done = len(finished)
        if done > 0 and unfinished:
            pct = int((done / total) * 100)
            if pct >= 75:
                lines.append(f"\nAlmost there! {done}/{total} ({pct}%)")
            elif pct >= 50:
                lines.append(f"\nGreat progress! {done}/{total} ({pct}%)")
            elif pct >= 25:
                lines.append(f"\nGood start! {done}/{total} ({pct}%)")
            else:
                lines.append(f"\nKeep going! {done}/{total} ({pct}%)")

    # All done message
    if not unfinished and actionable:
        lines.append("\n🎉 All tasks done for today!")

    return "\n".join(lines)


def build_schedule_message_for_date(schedule: dict, date_str: str) -> str:
    """Build schedule message for a specific date (for date selector).

    Args:
        schedule: Output from habit_handler.get_schedule_for_date()
        date_str: Date in YYYY-MM-DD format

    Returns:
        Formatted message string
    """
    global current_actionable_tasks

    lines = []

    # Format date display
    from datetime import datetime
    date_display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%b %d (%a)")
    effective_today = get_effective_date()

    if date_str == effective_today:
        lines.append(f"📅 Schedule ({date_display}) - Today:")
    else:
        lines.append(f"📅 Schedule ({date_display}):")

    # Timeline section
    timeline = schedule.get("timeline", [])
    if timeline:
        for i, task in enumerate(timeline, 1):
            start = task.get("start_time", "")
            end = task.get("end_time", "")
            text = task.get("text", "")
            category = (task.get("category") or "").lower()

            if start and end:
                time_str = f"{start}-{end}"
            elif start:
                time_str = start
            else:
                time_str = "All day"

            # Mark done tasks or show block icon
            if category == "block":
                suffix = " ☀️"
            elif task.get("done"):
                suffix = " ✅"
            else:
                suffix = ""

            lines.append(f"{i}. {time_str}  {text}{suffix}")

        lines.append("\n─────────────────────────────")
    else:
        lines.append("No scheduled items.")
        lines.append("")

    # Actionable tasks section
    actionable = schedule.get("actionable_tasks", [])
    unfinished = [t for t in actionable if not t.get("done")]
    finished = [t for t in actionable if t.get("done")]

    # Sort by time
    def get_sort_time(task):
        start = task.get("start_time", "")
        if start:
            try:
                return int(start.replace(":", ""))
            except:
                return 9999
        return 9999

    unfinished.sort(key=get_sort_time)

    # Only store actionable tasks if viewing today (effective date)
    if date_str == effective_today:
        current_actionable_tasks = unfinished.copy()

    if unfinished:
        lines.append("\n📝 Tasks needing action:")
        for i, task in enumerate(unfinished, 1):
            start = task.get("start_time", "")
            end = task.get("end_time", "")
            if start and end:
                time_str = f" {start}-{end}"
            elif start:
                time_str = f" {start}"
            else:
                time_str = ""
            lines.append(f"{i}. {task.get('text', '')}{time_str}")

        if date_str == effective_today:
            lines.append("\n→ Mark done: \"1 3\"")

    # Completed tasks
    if finished:
        finished.sort(key=get_sort_time)
        lines.append("\n✅ Tasks completed:")
        for i, task in enumerate(finished, 1):
            start = task.get("start_time", "")
            end = task.get("end_time", "")
            if start and end:
                time_str = f" {start}-{end}"
            elif start:
                time_str = f" {start}"
            else:
                time_str = ""
            lines.append(f"{i}. {task.get('text', '')}{time_str}")

    if not unfinished and not finished:
        lines.append("No tasks for this day.")

    return "\n".join(lines)


def calculate_daily_score(schedule: dict) -> dict:
    """Calculate daily score based on all actionable task completion.

    All categories are graded except "Block" (which isn't in actionable_tasks anyway).

    Returns:
        Dictionary with completed, total, percentage, grade
    """
    actionable = schedule.get("actionable_tasks", [])

    # All actionable tasks are gradeable (Block is already excluded)
    gradeable = actionable

    if not gradeable:
        return {"completed": 0, "total": 0, "percentage": 100, "grade": "N/A"}

    completed = len([t for t in gradeable if t.get("done")])
    total = len(gradeable)
    percentage = int((completed / total) * 100) if total > 0 else 100

    # Assign grade
    if percentage >= 90:
        grade = "A"
    elif percentage >= 70:
        grade = "B"
    elif percentage >= 50:
        grade = "C"
    else:
        grade = "D"

    return {
        "completed": completed,
        "total": total,
        "percentage": percentage,
        "grade": grade
    }


def build_evening_message(schedule: dict) -> str:
    """Build evening wind-down message with daily score."""
    lines = []
    lines.append("🌙 Time to wind down...\n")

    # Calculate daily score (Study/Work only)
    score = calculate_daily_score(schedule)

    # Check what's done (all actionable tasks)
    actionable = schedule.get("actionable_tasks", [])
    finished = [t for t in actionable if t.get("done")]
    unfinished = [t for t in actionable if not t.get("done")]

    # Show score if there were gradeable tasks
    if score["total"] > 0:
        grade_emoji = {"A": "🌟", "B": "👍", "C": "📈", "D": "💪"}.get(score["grade"], "")
        lines.append(f"📊 Today's Score: {score['grade']} {grade_emoji}")
        lines.append(f"   Tasks: {score['completed']}/{score['total']} ({score['percentage']}%)")
        lines.append("")

    if finished:
        lines.append(f"✅ Completed {len(finished)} task(s) today.")

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
        # Get today's schedule (using effective date for day boundary)
        effective = get_effective_date()
        schedule = habit_handler.get_today_schedule(effective_date=effective)

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
        # Get today's schedule (using effective date for day boundary)
        effective = get_effective_date()
        schedule = habit_handler.get_today_schedule(effective_date=effective)

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
        effective = get_effective_date()
        schedule = habit_handler.get_today_schedule(effective_date=effective)
        message = build_evening_message(schedule)

        await application.bot.send_message(
            chat_id=HABITS_USER_ID,
            text=message
        )
        logger.info("Sent evening winddown")

    except Exception as e:
        logger.error(f"Error sending evening winddown: {e}")


async def send_weekly_summary():
    """Send weekly progress summary on Sunday."""
    global is_paused

    if is_paused:
        logger.info("Task bot paused, skipping weekly summary")
        return

    if not HABITS_USER_ID:
        return

    try:
        # Get weekly stats from habit_handler
        stats = habit_handler.get_weekly_task_stats()

        lines = ["📊 Weekly Summary\n"]

        # Overall stats
        lines.append(f"Total tasks completed: {stats['total_completed']}/{stats['total_tasks']}")

        if stats['total_tasks'] > 0:
            avg_pct = int((stats['total_completed'] / stats['total_tasks']) * 100)
            lines.append(f"Average completion: {avg_pct}%")

        # Daily breakdown
        if stats['daily_scores']:
            lines.append("\n📅 Daily Scores:")
            for day in stats['daily_scores']:
                grade_emoji = {"A": "🌟", "B": "👍", "C": "📈", "D": "💪", "N/A": "➖"}.get(day['grade'], "")
                lines.append(f"  {day['date']}: {day['grade']} {grade_emoji} ({day['completed']}/{day['total']})")

        # Streak
        if stats['streak'] > 0:
            lines.append(f"\n🔥 Current streak: {stats['streak']} day(s) with 70%+ completion")

        # Encouragement based on average
        if stats['total_tasks'] > 0:
            avg_pct = int((stats['total_completed'] / stats['total_tasks']) * 100)
            if avg_pct >= 80:
                lines.append("\n🎉 Excellent week! Keep it up!")
            elif avg_pct >= 60:
                lines.append("\n👍 Good progress! Room for improvement.")
            else:
                lines.append("\n💪 Keep pushing! Next week will be better.")

        await application.bot.send_message(
            chat_id=HABITS_USER_ID,
            text="\n".join(lines)
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

    tz = task_config.get("timezone", TIMEZONE) if task_config else TIMEZONE
    boundary = task_config.get("day_boundary", 4) if task_config else 4

    info_message = f"""Daily Task Reminder Bot

Schedule ({tz}):
• 6:00 AM - Create recurring blocks (next 7 days)
• 8:00 AM - Morning schedule
• 12:00 PM - Check-in
• 7:00 PM - Check-in
• 10:00 PM - Evening wind-down + daily score
• Sunday 8:00 AM - Weekly summary (Mon-Sat)

⏰ Day Boundary: {boundary}:00 AM
Work done before {boundary}am counts for the previous day.

📊 Daily Scoring:
All tasks are graded (A/B/C/D) except time blocks (☀️).

✅ Mark Tasks Done:
Reply with numbers like "1 3" to mark done.

💬 Add New Tasks (AI-powered):
Send natural language like "4pm to 5pm job application"
AI parses date, time, category automatically.
Use Edit button to modify after creating.

Commands:
/tasks - Today's schedule (with date selector)
/blocks - Create recurring blocks for next 7 days
/settings - Day boundary & timezone
/stop /resume /status"""

    await update.message.reply_text(info_message)


async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /tasks command - show today's schedule with date selector."""
    if str(update.effective_user.id) != HABITS_USER_ID:
        await update.message.reply_text("Sorry, this bot is private.")
        return

    # Show today's schedule with date selector buttons
    effective = get_effective_date()
    schedule = habit_handler.get_today_schedule(effective_date=effective)
    message = build_schedule_message(schedule, show_all=True, is_morning=False)

    # Add date selector buttons
    keyboard = build_date_selector_keyboard()
    await update.message.reply_text(message, reply_markup=keyboard)




async def blocks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /blocks command - manually create recurring blocks for next 7 days."""
    if str(update.effective_user.id) != HABITS_USER_ID:
        await update.message.reply_text("Sorry, this bot is private.")
        return

    await update.message.reply_text("Creating recurring blocks for the next 7 days...")

    try:
        import os
        config_path = os.path.join(os.path.dirname(__file__), "schedule_config.json")
        result = habit_handler.create_recurring_blocks(config_path, days_ahead=7)

        created = result.get("created", 0)
        skipped = result.get("skipped", 0)
        source = result.get("source", "unknown")

        if created > 0:
            await update.message.reply_text(
                f"✅ Created {created} recurring block(s) for the next 7 days!\n"
                f"Source: {source}\n"
                f"Skipped: {skipped} (already exist or disabled)"
            )
        else:
            await update.message.reply_text(
                f"No new blocks created.\n"
                f"Skipped: {skipped} (already exist or disabled)\n"
                f"Source: {source}"
            )
    except Exception as e:
        logger.error(f"Error creating blocks: {e}")
        await update.message.reply_text(f"Error creating blocks: {str(e)}")


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
    tz = task_config.get("timezone", TIMEZONE) if task_config else TIMEZONE
    boundary = task_config.get("day_boundary", 4) if task_config else 4
    effective = get_effective_date()

    message = f"""Task Bot Status

Status: {status}
Timezone: {tz}
Day boundary: {boundary}:00 AM
Effective date: {effective}
Scheduled jobs: {len(jobs)}
Task parser: {ai_status}

Commands: /tasks /blocks /settings /stop /resume"""

    await update.message.reply_text(message)


# Common timezone options for settings
TIMEZONE_OPTIONS = [
    ("🇬🇧 London", "Europe/London"),
    ("🇫🇷 Paris", "Europe/Paris"),
    ("🇨🇳 Shanghai", "Asia/Shanghai"),
    ("🇯🇵 Tokyo", "Asia/Tokyo"),
    ("🇺🇸 New York", "America/New_York"),
    ("🇺🇸 Los Angeles", "America/Los_Angeles"),
]


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /settings command - view or update bot settings."""
    if str(update.effective_user.id) != HABITS_USER_ID:
        await update.message.reply_text("Sorry, this bot is private.")
        return

    await send_settings_display(update.message, task_config)


async def send_settings_display(message_or_query, config: dict, edit: bool = False) -> None:
    """Show current settings with Edit buttons."""
    tz = config.get("timezone", TIMEZONE)
    boundary = config.get("day_boundary", 4)

    text = f"""⚙️ Task Bot Settings

🕐 Day Boundary: {boundary}:00 AM
   (Day ends at {boundary}am - late night work counts for previous day)

🌍 Timezone: {tz}
   (Used for all scheduling)"""

    keyboard = [[
        InlineKeyboardButton("Edit Day Boundary", callback_data="settings_boundary"),
        InlineKeyboardButton("Edit Timezone", callback_data="settings_timezone"),
    ]]
    markup = InlineKeyboardMarkup(keyboard)

    if edit:
        await message_or_query.edit_message_text(text=text, reply_markup=markup)
    else:
        await message_or_query.reply_text(text, reply_markup=markup)


def build_boundary_options(current: int) -> InlineKeyboardMarkup:
    """Build day boundary hour options (3am-6am)."""
    options = [3, 4, 5, 6]
    row = []
    for h in options:
        label = f"✅ {h}am" if h == current else f"{h}am"
        row.append(InlineKeyboardButton(label, callback_data=f"settings_boundary_{h}"))
    return InlineKeyboardMarkup([row, [InlineKeyboardButton("← Back", callback_data="settings_back")]])


def build_timezone_options(current: str) -> InlineKeyboardMarkup:
    """Build timezone selection buttons."""
    rows = []
    for i in range(0, len(TIMEZONE_OPTIONS), 2):
        row = []
        for label, tz in TIMEZONE_OPTIONS[i:i+2]:
            display = f"✅ {label}" if tz == current else label
            row.append(InlineKeyboardButton(display, callback_data=f"settings_tz_{tz}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("← Back", callback_data="settings_back")])
    return InlineKeyboardMarkup(rows)


def build_edit_menu(task_id: str, task: dict) -> InlineKeyboardMarkup:
    """Build the main edit menu for a task."""
    rows = [
        [
            InlineKeyboardButton("📅 Date", callback_data=f"edit_date_{task_id}"),
            InlineKeyboardButton("🕐 Time", callback_data=f"edit_time_{task_id}"),
        ],
        [
            InlineKeyboardButton("📝 Text", callback_data=f"edit_text_{task_id}"),
            InlineKeyboardButton("📁 Category", callback_data=f"edit_cat_{task_id}"),
        ],
        [
            InlineKeyboardButton("🗑 Delete", callback_data=f"edit_delete_{task_id}"),
            InlineKeyboardButton("✖ Cancel", callback_data="edit_cancel"),
        ],
    ]
    return InlineKeyboardMarkup(rows)


def build_date_picker(task_id: str) -> InlineKeyboardMarkup:
    """Build date selection buttons."""
    today = datetime.now()
    rows = []
    # Today, Tomorrow, Day after tomorrow
    for i in range(3):
        d = today + timedelta(days=i)
        label = ["Today", "Tomorrow", d.strftime("%a")][i] if i < 2 else d.strftime("%a %d")
        date_str = d.strftime("%Y-%m-%d")
        rows.append([InlineKeyboardButton(label, callback_data=f"edit_setdate_{task_id}_{date_str}")])
    # Next 4 days
    row = []
    for i in range(3, 7):
        d = today + timedelta(days=i)
        label = d.strftime("%a %d")
        date_str = d.strftime("%Y-%m-%d")
        row.append(InlineKeyboardButton(label, callback_data=f"edit_setdate_{task_id}_{date_str}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("← Back", callback_data=f"edit_back_{task_id}")])
    return InlineKeyboardMarkup(rows)


def build_time_picker(task_id: str) -> InlineKeyboardMarkup:
    """Build time selection buttons."""
    times = [
        ("Morning", [("08:00", "8am"), ("09:00", "9am"), ("10:00", "10am"), ("11:00", "11am")]),
        ("Afternoon", [("12:00", "12pm"), ("13:00", "1pm"), ("14:00", "2pm"), ("15:00", "3pm")]),
        ("Evening", [("16:00", "4pm"), ("17:00", "5pm"), ("18:00", "6pm"), ("19:00", "7pm")]),
        ("Night", [("20:00", "8pm"), ("21:00", "9pm"), ("22:00", "10pm"), ("23:00", "11pm")]),
    ]
    rows = []
    for period, slots in times:
        row = []
        for time_val, label in slots:
            row.append(InlineKeyboardButton(label, callback_data=f"edit_settime_{task_id}_{time_val}"))
        rows.append(row)
    rows.append([
        InlineKeyboardButton("No time", callback_data=f"edit_settime_{task_id}_none"),
        InlineKeyboardButton("← Back", callback_data=f"edit_back_{task_id}")
    ])
    return InlineKeyboardMarkup(rows)


def build_category_picker(task_id: str) -> InlineKeyboardMarkup:
    """Build category selection buttons."""
    categories = ["Study", "Work", "Life", "Health", "Other"]
    rows = []
    row = []
    for cat in categories:
        row.append(InlineKeyboardButton(cat, callback_data=f"edit_setcat_{task_id}_{cat}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("← Back", callback_data=f"edit_back_{task_id}")])
    return InlineKeyboardMarkup(rows)


def build_date_selector_keyboard(selected_date: str = None) -> InlineKeyboardMarkup:
    """Build date selector buttons: Today (✅), Tomorrow, Others."""
    effective_today = get_effective_date()
    tz = pytz.timezone(task_config.get("timezone", TIMEZONE) if task_config else TIMEZONE)
    now = datetime.now(tz)

    # Calculate tomorrow relative to effective date
    effective_dt = datetime.strptime(effective_today, "%Y-%m-%d")
    tomorrow_str = (effective_dt + timedelta(days=1)).strftime("%Y-%m-%d")

    # Determine which is selected (default to today)
    if selected_date is None:
        selected_date = effective_today

    # Build labels with selection indicator
    today_label = "✅ Today" if selected_date == effective_today else "Today"
    tomorrow_label = "✅ Tomorrow" if selected_date == tomorrow_str else "Tomorrow"

    # Check if selected date is one of the "others"
    is_other_selected = selected_date not in (effective_today, tomorrow_str)
    others_label = "✅ Others" if is_other_selected else "Others"

    row = [
        InlineKeyboardButton(today_label, callback_data=f"tasks_date_{effective_today}"),
        InlineKeyboardButton(tomorrow_label, callback_data=f"tasks_date_{tomorrow_str}"),
        InlineKeyboardButton(others_label, callback_data="tasks_others"),
    ]

    return InlineKeyboardMarkup([row])


def build_others_date_keyboard(selected_date: str = None) -> InlineKeyboardMarkup:
    """Build expanded date selector showing next 5 days (after tomorrow)."""
    effective_today = get_effective_date()
    effective_dt = datetime.strptime(effective_today, "%Y-%m-%d")

    rows = []
    row = []
    for i in range(2, 7):
        d = effective_dt + timedelta(days=i)
        date_str = d.strftime("%Y-%m-%d")
        label = d.strftime("%a %d")  # e.g., "Mon 10"

        if selected_date == date_str:
            label = f"✅ {label}"

        row.append(InlineKeyboardButton(label, callback_data=f"tasks_date_{date_str}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    # Back button
    rows.append([InlineKeyboardButton("← Back", callback_data="tasks_back")])

    return InlineKeyboardMarkup(rows)


async def handle_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle settings-related callback buttons."""
    global task_config

    query = update.callback_query
    await query.answer()

    if str(query.from_user.id) != HABITS_USER_ID:
        return

    data = query.data

    if data == "settings_boundary":
        current = task_config.get("day_boundary", 4)
        await query.edit_message_text(
            text="Select when your day ends:\n\n(Late night work before this hour counts for the previous day)",
            reply_markup=build_boundary_options(current)
        )

    elif data.startswith("settings_boundary_"):
        hour = int(data.split("_")[-1])
        task_config["day_boundary"] = hour
        save_config(task_config)
        await query.edit_message_text(
            text=f"✅ Day boundary updated to {hour}:00 AM\n\nWork done before {hour}am now counts for the previous day.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← Back to Settings", callback_data="settings_back")]])
        )

    elif data == "settings_timezone":
        current = task_config.get("timezone", TIMEZONE)
        await query.edit_message_text(
            text="Select your timezone:",
            reply_markup=build_timezone_options(current)
        )

    elif data.startswith("settings_tz_"):
        tz = data.replace("settings_tz_", "")
        task_config["timezone"] = tz
        save_config(task_config)

        # Restart scheduler with new timezone
        if scheduler:
            scheduler.remove_all_jobs()
            setup_scheduler_jobs(scheduler, tz)
            logger.info(f"Scheduler restarted with timezone {tz}")

        await query.edit_message_text(
            text=f"✅ Timezone updated to {tz}\n\nAll schedules now use this timezone.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("← Back to Settings", callback_data="settings_back")]])
        )

    elif data == "settings_back":
        await send_settings_display(query, task_config, edit=True)


def setup_scheduler_jobs(sched: AsyncIOScheduler, timezone: str) -> None:
    """Set up all scheduler jobs with given timezone."""
    # Create daily recurring blocks at 6:00 AM
    sched.add_job(
        create_daily_blocks,
        CronTrigger(hour=6, minute=0, timezone=timezone),
        id="daily_blocks",
        name="Daily Blocks (6:00)"
    )

    # Morning reminder at 8:00 AM
    sched.add_job(
        send_morning_reminder,
        CronTrigger(hour=8, minute=0, timezone=timezone),
        id="morning_reminder",
        name="Morning Reminder (8:00)"
    )

    # Check-in at 12:00 PM
    sched.add_job(
        send_practice_checkin,
        CronTrigger(hour=12, minute=0, timezone=timezone),
        id="checkin_noon",
        name="Noon Check-in (12:00)"
    )

    # Check-in at 7:00 PM
    sched.add_job(
        send_practice_checkin,
        CronTrigger(hour=19, minute=0, timezone=timezone),
        id="checkin_evening",
        name="Evening Check-in (19:00)"
    )

    # Evening wind-down at 10:00 PM (with daily score)
    sched.add_job(
        send_evening_winddown,
        CronTrigger(hour=22, minute=0, timezone=timezone),
        id="evening_winddown",
        name="Evening Wind-down (22:00)"
    )

    # Weekly summary on Sunday at 8:00 AM
    sched.add_job(
        send_weekly_summary,
        CronTrigger(day_of_week="sun", hour=8, minute=0, timezone=timezone),
        id="weekly_summary",
        name="Weekly Summary (Sunday 08:00)"
    )

    # Monthly cleanup on 1st of each month at 3 AM
    sched.add_job(
        run_monthly_cleanup,
        CronTrigger(day=1, hour=3, minute=0, timezone=timezone),
        id="monthly_cleanup",
        name="Monthly Cleanup (1st of month, 3:00)"
    )


# /blocks command removed - recurring blocks are created automatically at 6am for next 7 days


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle natural language task input OR number-based task completion."""
    global current_actionable_tasks, editing_task

    if str(update.effective_user.id) != HABITS_USER_ID:
        await update.message.reply_text("Sorry, this bot is private.")
        return

    text = update.message.text.strip()

    # Handle pending text edit
    if editing_task.get("field") == "text" and editing_task.get("id"):
        task_id = editing_task["id"]
        success = habit_handler.update_reminder(task_id, text=text)
        editing_task = {}
        if success:
            # Get updated task details and show full confirmation with buttons
            task_details = habit_handler.get_reminder_by_id(task_id)
            if task_details:
                lines = ["✅ Task updated!", ""]
                if task_details.get("start_time"):
                    time_str = f"• 时间：{task_details.get('date', '')} {task_details['start_time']}"
                    if task_details.get("end_time"):
                        time_str += f"-{task_details['end_time']}"
                    lines.append(time_str)
                elif task_details.get("date"):
                    lines.append(f"• 日期：{task_details['date']}")
                lines.append(f"• 事项：{task_details.get('text', text)}")
                lines.append(f"• 类别：{task_details.get('category', 'Other')}")

                keyboard = [[
                    InlineKeyboardButton("✏️ Edit", callback_data=f"edit_menu_{task_id}"),
                    InlineKeyboardButton("🗑 Delete", callback_data=f"edit_delete_{task_id}"),
                ]]
                markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text("\n".join(lines), reply_markup=markup)
            else:
                await update.message.reply_text(f"✅ Task updated to: {text}")
        else:
            await update.message.reply_text("Failed to update task text.")
        return

    # Check for "edit N" command
    import re
    edit_match = re.match(r'^edit\s+(\d+)$', text.lower())
    if edit_match:
        num = int(edit_match.group(1))
        if not current_actionable_tasks:
            await update.message.reply_text("No tasks loaded. Use /tasks first.")
            return
        if 1 <= num <= len(current_actionable_tasks):
            task = current_actionable_tasks[num - 1]
            task_id = task.get("id")
            task_text = task.get("text", "Task")
            editing_task = {"id": task_id, "task": task}
            await update.message.reply_text(
                f"Editing: {task_text}\n\nSelect what to change:",
                reply_markup=build_edit_menu(task_id, task)
            )
        else:
            await update.message.reply_text(f"Task #{num} not found.")
        return

    # Check if this is a number-based completion (e.g., "1 3" or "1, 2, 3")
    numbers = re.findall(r'\d+', text)

    # If message is primarily numbers, treat as task completion
    if numbers and len(text.replace(" ", "").replace(",", "")) == sum(len(n) for n in numbers):
        if not current_actionable_tasks:
            await update.message.reply_text("No tasks loaded. Use /tasks first to see your tasks.")
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
                effective = get_effective_date()
                success = habit_handler.mark_task_done(task_id, effective_date=effective)
                if success:
                    completed.append(f"✅ {task_name}")
                else:
                    errors.append(f"Failed to save: {task_name}")
            else:
                errors.append(f"#{num} not found")

        # Send confirmation
        if completed:
            await update.message.reply_text("Marked as done:\n" + "\n".join(completed))

            # Refresh the actionable tasks list
            effective = get_effective_date()
            schedule = habit_handler.get_today_schedule(effective_date=effective)
            current_actionable_tasks = [t for t in schedule.get("actionable_tasks", []) if not t.get("done")]

        if errors:
            await update.message.reply_text("Errors: " + ", ".join(errors))

        return

    # Otherwise, treat as new task input - use AI parser
    parsed = parse_task_with_ai(text, TIMEZONE)
    logger.info(f"AI Parsed task: {parsed}")

    # Check for conflicts (tasks at the same time on the same date)
    conflict_warning = ""
    if parsed.get("date") and parsed.get("start_time"):
        existing_tasks = habit_handler.get_all_reminders(for_date=parsed["date"])
        for existing in existing_tasks:
            if existing.get("start_time") == parsed["start_time"]:
                conflict_warning = f"\n\n⚠️ Note: You already have \"{existing['text']}\" at {parsed['start_time']}"
                break

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
        task_id = result.get("page_id")

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

        if conflict_warning:
            lines.append(conflict_warning)

        # Add Edit button
        keyboard = [[
            InlineKeyboardButton("✏️ Edit", callback_data=f"edit_menu_{task_id}"),
            InlineKeyboardButton("🗑 Delete", callback_data=f"edit_delete_{task_id}"),
        ]]
        markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text("\n".join(lines), reply_markup=markup)
    else:
        await update.message.reply_text(f"保存失败: {result.get('error', 'Unknown error')}")


async def handle_tasks_date_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle date selection for viewing different days' schedules."""
    query = update.callback_query
    await query.answer()

    if str(query.from_user.id) != HABITS_USER_ID:
        return

    data = query.data

    # Handle "Others" button - show expanded date options
    if data == "tasks_others":
        await query.edit_message_text(
            text=query.message.text,
            reply_markup=build_others_date_keyboard()
        )
        return

    # Handle "Back" button - return to Today/Tomorrow/Others
    if data == "tasks_back":
        effective = get_effective_date()
        schedule = habit_handler.get_today_schedule(effective_date=effective)
        message = build_schedule_message(schedule, show_all=True, is_morning=False)
        keyboard = build_date_selector_keyboard()
        await query.edit_message_text(message, reply_markup=keyboard)
        return

    # Extract date from callback data: tasks_date_YYYY-MM-DD
    date_str = data.replace("tasks_date_", "")

    # Get schedule for the selected date
    effective_today = get_effective_date()
    if date_str == effective_today:
        schedule = habit_handler.get_today_schedule(effective_date=effective_today)
        message = build_schedule_message(schedule, show_all=True, is_morning=False)
    else:
        schedule = habit_handler.get_schedule_for_date(date_str)
        message = build_schedule_message_for_date(schedule, date_str)

    # Determine which keyboard to show based on whether it's an "others" date
    effective_dt = datetime.strptime(effective_today, "%Y-%m-%d")
    tomorrow_str = (effective_dt + timedelta(days=1)).strftime("%Y-%m-%d")

    if date_str in (effective_today, tomorrow_str):
        keyboard = build_date_selector_keyboard(selected_date=date_str)
    else:
        keyboard = build_others_date_keyboard(selected_date=date_str)

    await query.edit_message_text(message, reply_markup=keyboard)


async def handle_edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle edit-related callback buttons."""
    global editing_task

    query = update.callback_query
    await query.answer()

    if str(query.from_user.id) != HABITS_USER_ID:
        return

    data = query.data

    try:
        # Cancel editing
        if data == "edit_cancel":
            editing_task = {}
            await query.edit_message_text("Edit cancelled.")
            return

        # Extract task_id from most edit callbacks
        parts = data.split("_")

        # Show edit menu (from task creation confirmation)
        if data.startswith("edit_menu_"):
            task_id = "_".join(parts[2:])
            editing_task = {"id": task_id, "task": {}}
            await query.edit_message_text(
                text="Select what to change:",
                reply_markup=build_edit_menu(task_id, {})
            )

        # Show date picker
        elif data.startswith("edit_date_"):
            task_id = "_".join(parts[2:])
            await query.edit_message_text(
                text="Select new date:",
                reply_markup=build_date_picker(task_id)
            )

        # Show time picker
        elif data.startswith("edit_time_"):
            task_id = "_".join(parts[2:])
            await query.edit_message_text(
                text="Select new time:",
                reply_markup=build_time_picker(task_id)
            )

        # Show category picker
        elif data.startswith("edit_cat_"):
            task_id = "_".join(parts[2:])
            await query.edit_message_text(
                text="Select category:",
                reply_markup=build_category_picker(task_id)
            )

        # Prompt for text edit
        elif data.startswith("edit_text_"):
            task_id = "_".join(parts[2:])
            editing_task = {"id": task_id, "field": "text"}
            await query.edit_message_text(
                "Type the new task text:\n\n(Send a message with the new text)"
            )

        # Delete task
        elif data.startswith("edit_delete_"):
            task_id = "_".join(parts[2:])
            success = habit_handler.delete_reminder(task_id)
            if success:
                await query.edit_message_text("🗑 Task deleted.")
            else:
                await query.edit_message_text("Failed to delete task.")
            editing_task = {}

        # Back to edit menu
        elif data.startswith("edit_back_"):
            task_id = "_".join(parts[2:])
            task = editing_task.get("task", {})
            text = task.get("text", "Task")
            await query.edit_message_text(
                text=f"Editing: {text}\n\nSelect what to change:",
                reply_markup=build_edit_menu(task_id, task)
            )

        # Set date
        elif data.startswith("edit_setdate_"):
            # Format: edit_setdate_TASKID_DATE
            date_str = parts[-1]
            task_id = "_".join(parts[2:-1])
            success = habit_handler.update_reminder(task_id, date=date_str)
            if success:
                await query.edit_message_text(f"✅ Date updated to {date_str}")
            else:
                await query.edit_message_text("Failed to update date.")
            editing_task = {}

        # Set time
        elif data.startswith("edit_settime_"):
            # Format: edit_settime_TASKID_TIME
            time_str = parts[-1]
            task_id = "_".join(parts[2:-1])
            if time_str == "none":
                success = habit_handler.update_reminder(task_id, start_time=None)
            else:
                success = habit_handler.update_reminder(task_id, start_time=time_str)
            if success:
                msg = "Time removed" if time_str == "none" else f"Time updated to {time_str}"
                await query.edit_message_text(f"✅ {msg}")
            else:
                await query.edit_message_text("Failed to update time.")
            editing_task = {}

        # Set category
        elif data.startswith("edit_setcat_"):
            # Format: edit_setcat_TASKID_CATEGORY
            category = parts[-1]
            task_id = "_".join(parts[2:-1])
            success = habit_handler.update_reminder(task_id, category=category)
            if success:
                await query.edit_message_text(f"✅ Category updated to {category}")
            else:
                await query.edit_message_text("Failed to update category.")
            editing_task = {}

    except Exception as e:
        logger.error(f"Edit callback error: {e}")
        await query.edit_message_text(f"Error: {str(e)}")
        editing_task = {}


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
                effective = get_effective_date()
                habit_handler.mark_task_done(task_id, effective_date=effective)
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

    tz = task_config.get("timezone", TIMEZONE) if task_config else TIMEZONE
    scheduler = AsyncIOScheduler(timezone=tz)

    # Set up all scheduled jobs
    setup_scheduler_jobs(scheduler, tz)

    scheduler.start()
    logger.info(f"Scheduler started with timezone {tz}")

    for job in scheduler.get_jobs():
        next_run = job.next_run_time
        logger.info(f"Job '{job.name}' next run: {next_run}")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors."""
    logger.error(f"Update {update} caused error {context.error}")


def main():
    """Main function to run the task bot."""
    global habit_handler, application, task_config

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

    # Load task config (day boundary, timezone)
    task_config = load_config()
    tz = task_config.get("timezone", TIMEZONE)
    boundary = task_config.get("day_boundary", 4)
    print(f"Config loaded: timezone={tz}, day_boundary={boundary}am")

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
    application.add_handler(CommandHandler("blocks", blocks_command))
    application.add_handler(CommandHandler("settings", settings_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("resume", resume_command))
    application.add_handler(CommandHandler("status", status_command))

    # Callback handlers - specific patterns first
    application.add_handler(CallbackQueryHandler(handle_settings_callback, pattern="^settings_"))
    application.add_handler(CallbackQueryHandler(handle_tasks_date_callback, pattern="^tasks_"))
    application.add_handler(CallbackQueryHandler(handle_edit_callback, pattern="^edit_"))
    application.add_handler(CallbackQueryHandler(handle_callback))

    # Add message handler for natural language tasks (must be last)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Add error handler
    application.add_error_handler(error_handler)

    # Start polling
    print(f"Task bot starting with timezone {tz}...")
    print(f"Day boundary: {boundary}:00 AM (late night work counts for previous day)")
    print("Schedule: 8:00 (morning), 12:00/19:00 (check-ins), 22:00 (wind-down), Sunday 20:00 (weekly)")
    print("Send any message to add a task using natural language!")
    print("Press Ctrl+C to stop")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
