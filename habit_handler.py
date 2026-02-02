"""
Habit Handler

Business logic for habit tracking with Notion integration.
Manages two Notion databases:

1. Tracking Database - Daily habit entries
   Properties: Date (title), Listened (checkbox), Spoke (checkbox),
              Video (text), Tasks (text - JSON array of completed task IDs)

2. Reminders Database - User-defined tasks/reminders
   Properties: Reminder (title), Enabled (checkbox), Date (date - optional)

Key methods:
- get_or_create_today_habit(): Get or create today's tracking entry
- update_habit(field, value): Update Listened/Spoke checkboxes
- mark_task_done/undone(task_id): Track custom task completion
- get_weekly_stats(): Calculate 7-day progress statistics
- get_all_reminders(): Fetch enabled reminders from Notion
- create_reminder(text): Add a new reminder via bot
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Optional
from notion_client import Client

logger = logging.getLogger(__name__)


class HabitHandler:
    """Handles habit tracking operations with Notion database."""

    def __init__(self, notion_key: str, tracking_db_id: str, reminders_db_id: str):
        """Initialize habit handler.

        Args:
            notion_key: Notion API key
            tracking_db_id: Database ID for habit tracking
            reminders_db_id: Database ID for reminders
        """
        self.client = Client(auth=notion_key)
        self.tracking_db_id = tracking_db_id
        self.reminders_db_id = reminders_db_id

    def _get_today_date_str(self) -> str:
        """Get today's date as YYYY-MM-DD string."""
        return datetime.now().strftime("%Y-%m-%d")

    def get_or_create_today_habit(self) -> dict:
        """Get today's habit entry or create it if it doesn't exist.

        Returns:
            Dictionary with page_id, date, listened, spoke, video fields
        """
        today = self._get_today_date_str()

        # Search for existing entry
        try:
            response = self.client.databases.query(
                database_id=self.tracking_db_id,
                filter={
                    "property": "Date",
                    "title": {"equals": today}
                }
            )

            if response.get("results"):
                page = response["results"][0]
                return self._parse_habit_page(page)

            # Create new entry
            new_page = self.client.pages.create(
                parent={"database_id": self.tracking_db_id},
                properties={
                    "Date": {"title": [{"text": {"content": today}}]},
                    "Listened": {"checkbox": False},
                    "Spoke": {"checkbox": False},
                    "Video": {"rich_text": []}
                }
            )
            logger.info(f"Created new habit entry for {today}")
            return self._parse_habit_page(new_page)

        except Exception as e:
            logger.error(f"Error getting/creating habit entry: {e}")
            return {
                "page_id": None,
                "date": today,
                "listened": False,
                "spoke": False,
                "video": ""
            }

    def _parse_habit_page(self, page: dict) -> dict:
        """Parse Notion page into habit dictionary."""
        props = page.get("properties", {})

        # Get Date (title)
        date_prop = props.get("Date", {})
        date_title = date_prop.get("title", [])
        date = date_title[0]["text"]["content"] if date_title else ""

        # Get Listened (checkbox)
        listened = props.get("Listened", {}).get("checkbox", False)

        # Get Spoke (checkbox)
        spoke = props.get("Spoke", {}).get("checkbox", False)

        # Get Video (rich_text)
        video_prop = props.get("Video", {})
        video_text = video_prop.get("rich_text", [])
        video = video_text[0]["text"]["content"] if video_text else ""

        # Get Tasks (rich_text) - JSON list of completed task IDs
        tasks_prop = props.get("Tasks", {})
        tasks_text = tasks_prop.get("rich_text", [])
        tasks_json = tasks_text[0]["text"]["content"] if tasks_text else "[]"
        try:
            completed_tasks = json.loads(tasks_json)
        except json.JSONDecodeError:
            completed_tasks = []

        return {
            "page_id": page["id"],
            "date": date,
            "listened": listened,
            "spoke": spoke,
            "video": video,
            "completed_tasks": completed_tasks
        }

    def update_habit(self, field: str, value: bool, video_url: str = None) -> bool:
        """Update a habit field for today's entry.

        Args:
            field: 'listened' or 'spoke'
            value: True/False
            video_url: Optional video URL to store

        Returns:
            True if successful, False otherwise
        """
        habit = self.get_or_create_today_habit()
        page_id = habit.get("page_id")

        if not page_id:
            logger.error("No page_id for habit update")
            return False

        try:
            properties = {}

            if field == "listened":
                properties["Listened"] = {"checkbox": value}
            elif field == "spoke":
                properties["Spoke"] = {"checkbox": value}

            if video_url:
                properties["Video"] = {
                    "rich_text": [{"text": {"content": video_url}}]
                }

            self.client.pages.update(
                page_id=page_id,
                properties=properties
            )
            logger.info(f"Updated habit {field}={value} for page {page_id}")
            return True

        except Exception as e:
            logger.error(f"Error updating habit: {e}")
            return False

    def mark_both_done(self) -> bool:
        """Mark both listened and spoke as done for today."""
        habit = self.get_or_create_today_habit()
        page_id = habit.get("page_id")

        if not page_id:
            return False

        try:
            self.client.pages.update(
                page_id=page_id,
                properties={
                    "Listened": {"checkbox": True},
                    "Spoke": {"checkbox": True}
                }
            )
            return True
        except Exception as e:
            logger.error(f"Error marking both done: {e}")
            return False

    def mark_task_done(self, task_id: str) -> bool:
        """Mark a custom task as done for today.

        Args:
            task_id: The Notion page ID of the reminder/task

        Returns:
            True if successful
        """
        habit = self.get_or_create_today_habit()
        page_id = habit.get("page_id")
        completed_tasks = habit.get("completed_tasks", [])

        if not page_id:
            return False

        if task_id not in completed_tasks:
            completed_tasks.append(task_id)

        try:
            self.client.pages.update(
                page_id=page_id,
                properties={
                    "Tasks": {
                        "rich_text": [{"text": {"content": json.dumps(completed_tasks)}}]
                    }
                }
            )
            logger.info(f"Marked task {task_id} as done")
            return True
        except Exception as e:
            logger.error(f"Error marking task done: {e}")
            return False

    def mark_task_undone(self, task_id: str) -> bool:
        """Mark a custom task as not done for today.

        Args:
            task_id: The Notion page ID of the reminder/task

        Returns:
            True if successful
        """
        habit = self.get_or_create_today_habit()
        page_id = habit.get("page_id")
        completed_tasks = habit.get("completed_tasks", [])

        if not page_id:
            return False

        if task_id in completed_tasks:
            completed_tasks.remove(task_id)

        try:
            self.client.pages.update(
                page_id=page_id,
                properties={
                    "Tasks": {
                        "rich_text": [{"text": {"content": json.dumps(completed_tasks)}}]
                    }
                }
            )
            logger.info(f"Marked task {task_id} as undone")
            return True
        except Exception as e:
            logger.error(f"Error marking task undone: {e}")
            return False

    def is_task_done(self, task_id: str) -> bool:
        """Check if a task is done for today."""
        habit = self.get_or_create_today_habit()
        return task_id in habit.get("completed_tasks", [])

    def get_weekly_stats(self) -> dict:
        """Calculate 7-day statistics.

        Returns:
            Dictionary with listening_days, speaking_days, videos_watched, streak
        """
        today = datetime.now()
        start_date = today - timedelta(days=6)

        try:
            # Query last 7 days of entries
            response = self.client.databases.query(
                database_id=self.tracking_db_id,
                sorts=[{"property": "Date", "direction": "descending"}]
            )

            entries = []
            for page in response.get("results", []):
                habit = self._parse_habit_page(page)
                try:
                    entry_date = datetime.strptime(habit["date"], "%Y-%m-%d")
                    if start_date <= entry_date <= today:
                        entries.append(habit)
                except ValueError:
                    continue

            # Calculate stats
            listening_days = sum(1 for e in entries if e["listened"])
            speaking_days = sum(1 for e in entries if e["spoke"])
            videos_watched = sum(1 for e in entries if e["video"])

            # Calculate current streak (consecutive days with both done)
            streak = 0
            check_date = today
            date_map = {e["date"]: e for e in entries}

            for i in range(7):
                date_str = check_date.strftime("%Y-%m-%d")
                entry = date_map.get(date_str, {})
                if entry.get("listened") and entry.get("spoke"):
                    streak += 1
                    check_date -= timedelta(days=1)
                else:
                    break

            return {
                "listening_days": listening_days,
                "speaking_days": speaking_days,
                "videos_watched": videos_watched,
                "streak": streak,
                "total_days": 7
            }

        except Exception as e:
            logger.error(f"Error getting weekly stats: {e}")
            return {
                "listening_days": 0,
                "speaking_days": 0,
                "videos_watched": 0,
                "streak": 0,
                "total_days": 7
            }

    def fetch_reminders_for_time(self, time_str: str) -> list:
        """Fetch enabled reminders for a specific time.

        Args:
            time_str: Time in HH:MM format (e.g., "08:00")

        Returns:
            List of reminder text strings
        """
        try:
            response = self.client.databases.query(
                database_id=self.reminders_db_id,
                filter={
                    "and": [
                        {"property": "Enabled", "checkbox": {"equals": True}}
                    ]
                }
            )

            reminders = []
            for page in response.get("results", []):
                props = page.get("properties", {})

                # Get Time (date property)
                time_prop = props.get("Time", {})
                time_date = time_prop.get("date", {})
                time_value = time_date.get("start", "") if time_date else ""

                # Extract HH:MM from datetime string if present
                if time_value:
                    # Handle both date and datetime formats
                    if "T" in time_value:
                        # Format: 2024-01-01T08:00:00
                        page_time = time_value.split("T")[1][:5]
                    else:
                        # Just a date, no time component
                        continue

                    if page_time == time_str:
                        # Get Reminder (title)
                        reminder_prop = props.get("Reminder", {})
                        reminded_title = reminder_prop.get("title", [])
                        if reminded_title:
                            text = reminded_title[0]["text"]["content"]
                            reminders.append(text)

            return reminders

        except Exception as e:
            logger.error(f"Error fetching reminders: {e}")
            return []

    def get_all_reminders(self, for_today: bool = True) -> list:
        """Get enabled reminders.

        Args:
            for_today: If True, only return reminders for today or without a date.
                      If False, return all enabled reminders.

        Returns:
            List of reminder dictionaries with id, text, and date
        """
        try:
            response = self.client.databases.query(
                database_id=self.reminders_db_id,
                filter={"property": "Enabled", "checkbox": {"equals": True}}
            )

            today = self._get_today_date_str()
            reminders = []

            for page in response.get("results", []):
                props = page.get("properties", {})

                # Get Reminder (title)
                reminder_prop = props.get("Reminder", {})
                reminder_title = reminder_prop.get("title", [])
                text = reminder_title[0]["text"]["content"] if reminder_title else ""

                # Get Date
                date_prop = props.get("Date", {})
                date_value = date_prop.get("date", {})
                date_str = date_value.get("start", "") if date_value else ""

                if not text:
                    continue

                # Filter by date if requested
                if for_today:
                    # Include if: no date set, or date is today
                    if date_str and date_str[:10] != today:
                        continue

                reminders.append({
                    "id": page["id"],
                    "text": text,
                    "date": date_str
                })

            return reminders

        except Exception as e:
            logger.error(f"Error fetching all reminders: {e}")
            return []

    def create_reminder(self, text: str, date: str = None, start_time: str = None,
                        end_time: str = None, priority: str = None, category: str = None) -> dict:
        """Create a new reminder in the Reminders database.

        Args:
            text: The reminder text
            date: Optional date in YYYY-MM-DD format
            start_time: Optional start time in HH:MM format
            end_time: Optional end time in HH:MM format
            priority: Optional priority (High, Mid, Low) - ignored if property doesn't exist
            category: Optional category (Work, Life, Health, Study, Other) - ignored if property doesn't exist

        Returns:
            Dictionary with success status and page_id or error
        """
        # First, get the database schema to check which properties exist
        try:
            db = self.client.databases.retrieve(database_id=self.reminders_db_id)
            db_properties = db.get("properties", {})
            available_props = {name.lower(): name for name in db_properties.keys()}
        except Exception:
            available_props = {}

        try:
            properties = {
                "Reminder": {"title": [{"text": {"content": text}}]},
                "Enabled": {"checkbox": True}
            }

            # Add date with optional time - check actual property name
            if date:
                date_value = {"start": date}
                if start_time:
                    date_value["start"] = f"{date}T{start_time}:00"
                    if end_time:
                        date_value["end"] = f"{date}T{end_time}:00"
                # Find the actual Date property name in database
                date_prop_name = available_props.get("date", "Date")
                properties[date_prop_name] = {"date": date_value}
                logger.info(f"Setting date property '{date_prop_name}' to: {date_value}")

            # Add priority only if property exists in database
            if priority and "priority" in available_props:
                prop_name = available_props["priority"]
                properties[prop_name] = {"select": {"name": priority}}

            # Add category only if property exists in database
            if category and "category" in available_props:
                prop_name = available_props["category"]
                properties[prop_name] = {"select": {"name": category}}

            new_page = self.client.pages.create(
                parent={"database_id": self.reminders_db_id},
                properties=properties
            )
            logger.info(f"Created reminder: {text} (date: {date}, time: {start_time}-{end_time})")
            return {"success": True, "page_id": new_page["id"]}

        except Exception as e:
            logger.error(f"Error creating reminder: {e}")
            return {"success": False, "error": str(e)}

    def delete_reminder(self, page_id: str) -> bool:
        """Delete (archive) a reminder.

        Args:
            page_id: The Notion page ID to delete

        Returns:
            True if successful
        """
        try:
            self.client.pages.update(page_id=page_id, archived=True)
            logger.info(f"Deleted reminder {page_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting reminder: {e}")
            return False

    def test_connection(self) -> dict:
        """Test connection to Notion databases.

        Returns:
            Dictionary with success status and database info
        """
        try:
            # Test tracking database
            tracking_db = self.client.databases.retrieve(
                database_id=self.tracking_db_id
            )
            tracking_title = tracking_db.get("title", [])
            tracking_name = tracking_title[0]["text"]["content"] if tracking_title else "Unknown"

            # Test reminders database
            reminders_db = self.client.databases.retrieve(
                database_id=self.reminders_db_id
            )
            reminders_title = reminders_db.get("title", [])
            reminders_name = reminders_title[0]["text"]["content"] if reminders_title else "Unknown"

            return {
                "success": True,
                "tracking_db": tracking_name,
                "reminders_db": reminders_name
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
