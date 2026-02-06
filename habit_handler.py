"""
Habit Handler

Business logic for habit tracking with Notion integration.
Manages Notion databases:

1. Tracking Database - Daily habit entries
   Properties: Date (title), Listened (checkbox), Spoke (checkbox),
              Video (text), Tasks (text - JSON array of completed task IDs)

2. Reminders Database - User-defined tasks/reminders
   Properties: Reminder (title), Enabled (checkbox), Date (date - optional)

3. Recurring Blocks Database (optional) - Auto-created time blocks
   Properties: Name (title), Start Time (text), End Time (text),
              Days (multi-select), Start Date (date), End Date (date),
              Category (select), Priority (select), Enabled (checkbox)

Key methods:
- get_or_create_today_habit(): Get or create today's tracking entry
- update_habit(field, value): Update Listened/Spoke checkboxes
- mark_task_done/undone(task_id): Track custom task completion
- get_weekly_stats(): Calculate 7-day progress statistics
- get_all_reminders(): Fetch enabled reminders from Notion
- create_reminder(text): Add a new reminder via bot
- create_recurring_blocks(): Create daily time blocks from config or Notion DB
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Optional
from notion_client import Client

logger = logging.getLogger(__name__)


class HabitHandler:
    """Handles habit tracking operations with Notion database."""

    def __init__(self, notion_key: str, tracking_db_id: str, reminders_db_id: str,
                 recurring_blocks_db_id: str = None):
        """Initialize habit handler.

        Args:
            notion_key: Notion API key
            tracking_db_id: Database ID for habit tracking
            reminders_db_id: Database ID for reminders
            recurring_blocks_db_id: Optional database ID for recurring time blocks
        """
        self.client = Client(auth=notion_key)
        self.tracking_db_id = tracking_db_id
        self.reminders_db_id = reminders_db_id
        self.recurring_blocks_db_id = recurring_blocks_db_id

    def _get_today_date_str(self) -> str:
        """Get today's date as YYYY-MM-DD string."""
        return datetime.now().strftime("%Y-%m-%d")

    def get_or_create_today_habit(self, effective_date: str = None) -> dict:
        """Get today's habit entry or create it if it doesn't exist.

        Args:
            effective_date: Override date (YYYY-MM-DD) for day boundary support.

        Returns:
            Dictionary with page_id, date, listened, spoke, video fields
        """
        today = effective_date or self._get_today_date_str()

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

            # Create new entry with only Date and Tasks (minimal schema)
            new_page = self.client.pages.create(
                parent={"database_id": self.tracking_db_id},
                properties={
                    "Date": {"title": [{"text": {"content": today}}]},
                    "Tasks": {"rich_text": [{"text": {"content": "[]"}}]}
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

    def mark_task_done(self, task_id: str, effective_date: str = None) -> bool:
        """Mark a custom task as done for today.

        Args:
            task_id: The Notion page ID of the reminder/task
            effective_date: Override date (YYYY-MM-DD) for day boundary support.

        Returns:
            True if successful
        """
        habit = self.get_or_create_today_habit(effective_date=effective_date)
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

    def get_weekly_task_stats(self) -> dict:
        """Calculate weekly task completion statistics (Mon-Sat only).

        Counts all tasks except "Block" category for scoring.
        Sunday is excluded from weekly summary since it's rest day.

        Returns:
            Dictionary with daily_scores, total_completed, total_tasks, streak
        """
        today = datetime.now()
        daily_scores = []
        total_completed = 0
        total_tasks = 0
        streak = 0
        streak_broken = False

        try:
            # Get last 7 days but skip Sunday
            for i in range(6, -1, -1):  # Start from 6 days ago to today
                check_date = today - timedelta(days=i)
                date_str = check_date.strftime("%Y-%m-%d")
                day_name = check_date.strftime("%a")  # Mon, Tue, etc.

                # Skip Sunday - only count Mon-Sat
                if day_name == "Sun":
                    continue

                # Get tasks for this date
                reminders = self.get_all_reminders(for_date=date_str)

                # Filter out Block category (all others are gradeable)
                gradeable = [r for r in reminders
                            if (r.get("category") or "").lower() != "block"]

                # Get completed tasks for this date
                try:
                    response = self.client.databases.query(
                        database_id=self.tracking_db_id,
                        filter={
                            "property": "Date",
                            "title": {"equals": date_str}
                        }
                    )
                    if response.get("results"):
                        page = response["results"][0]
                        habit = self._parse_habit_page(page)
                        completed_ids = habit.get("completed_tasks", [])
                    else:
                        completed_ids = []
                except Exception:
                    completed_ids = []

                # Count completed gradeable tasks
                completed = len([t for t in gradeable if t.get("id") in completed_ids])
                total = len(gradeable)

                total_completed += completed
                total_tasks += total

                # Calculate grade
                if total == 0:
                    grade = "N/A"
                    pct = 100
                else:
                    pct = int((completed / total) * 100)
                    if pct >= 90:
                        grade = "A"
                    elif pct >= 70:
                        grade = "B"
                    elif pct >= 50:
                        grade = "C"
                    else:
                        grade = "D"

                daily_scores.append({
                    "date": f"{day_name} {check_date.strftime('%m/%d')}",
                    "completed": completed,
                    "total": total,
                    "percentage": pct,
                    "grade": grade
                })

                # Calculate streak (70%+ completion)
                if not streak_broken and pct >= 70 and total > 0:
                    streak += 1
                elif total > 0:
                    streak_broken = True

            # Reverse streak count (we want consecutive days from today going back)
            # Recalculate from today backwards
            streak = 0
            for score in reversed(daily_scores):
                if score["total"] > 0 and score["percentage"] >= 70:
                    streak += 1
                elif score["total"] > 0:
                    break

            return {
                "daily_scores": daily_scores,
                "total_completed": total_completed,
                "total_tasks": total_tasks,
                "streak": streak
            }

        except Exception as e:
            logger.error(f"Error getting weekly task stats: {e}")
            return {
                "daily_scores": [],
                "total_completed": 0,
                "total_tasks": 0,
                "streak": 0
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

    def _get_date_property_name(self) -> str:
        """Get the date property name from database schema.

        Returns:
            The name of the date property to use
        """
        try:
            db = self.client.databases.retrieve(database_id=self.reminders_db_id)
            db_properties = db.get("properties", {})

            date_props_found = []
            for name, config in db_properties.items():
                prop_type = config.get("type", "")
                if prop_type == "date":
                    date_props_found.append(name)

            # Find the best date property (same logic as create_reminder)
            for prop in date_props_found:
                if prop.strip().lower() == "date":
                    return prop
            for prop in date_props_found:
                if "date" in prop.lower():
                    return prop
            if date_props_found:
                return date_props_found[0]

            return "Date"  # fallback
        except Exception as e:
            logger.error(f"Error getting date property name: {e}")
            return "Date"

    def get_all_reminders(self, for_today: bool = True, for_date: str = None) -> list:
        """Get enabled reminders with full details.

        Args:
            for_today: If True, only return reminders for today or without a date.
                      If False, return all enabled reminders.
            for_date: If provided (YYYY-MM-DD), return reminders for that specific date.
                      Overrides for_today if provided.

        Returns:
            List of reminder dictionaries with id, text, date, start_time, end_time, category, priority
        """
        try:
            # Get the correct date property name
            date_prop_name = self._get_date_property_name()
            logger.info(f"Reading reminders using date property: '{date_prop_name}'")

            response = self.client.databases.query(
                database_id=self.reminders_db_id,
                filter={"property": "Enabled", "checkbox": {"equals": True}}
            )

            # Determine target date
            if for_date:
                target_date = for_date
            else:
                target_date = self._get_today_date_str()

            reminders = []

            for page in response.get("results", []):
                props = page.get("properties", {})

                # Get Reminder (title)
                reminder_prop = props.get("Reminder", {})
                reminder_title = reminder_prop.get("title", [])
                text = reminder_title[0]["text"]["content"] if reminder_title else ""

                # Get Date using detected property name
                date_prop = props.get(date_prop_name, {})
                date_value = date_prop.get("date", {})
                date_str = date_value.get("start", "") if date_value else ""
                end_str = date_value.get("end", "") if date_value else ""

                # Parse start_time and end_time from date strings
                start_time = None
                end_time = None
                if date_str and "T" in date_str:
                    start_time = date_str.split("T")[1][:5]  # HH:MM
                if end_str and "T" in end_str:
                    end_time = end_str.split("T")[1][:5]  # HH:MM

                # Get Category (select)
                category_prop = props.get("Category", {})
                category_select = category_prop.get("select", {})
                category = category_select.get("name") if category_select else None

                # Get Priority (select)
                priority_prop = props.get("Priority", {})
                priority_select = priority_prop.get("select", {})
                priority = priority_select.get("name") if priority_select else None

                if not text:
                    continue

                # Filter by date if requested
                if for_today or for_date:
                    # Include if: no date set, or date matches target
                    if date_str and date_str[:10] != target_date:
                        continue

                reminders.append({
                    "id": page["id"],
                    "text": text,
                    "date": date_str[:10] if date_str else None,
                    "start_time": start_time,
                    "end_time": end_time,
                    "category": category,
                    "priority": priority
                })

            return reminders

        except Exception as e:
            logger.error(f"Error fetching all reminders: {e}")
            return []

    def get_reminder_by_id(self, page_id: str) -> dict:
        """Get a single reminder by its page ID.

        Args:
            page_id: The Notion page ID

        Returns:
            Dictionary with task details or None if not found
        """
        try:
            page = self.client.pages.retrieve(page_id=page_id)
            props = page.get("properties", {})

            # Get Reminder (title)
            reminder_prop = props.get("Reminder", {})
            reminder_title = reminder_prop.get("title", [])
            text = reminder_title[0]["text"]["content"] if reminder_title else ""

            # Get Date
            date_prop_name = self._get_date_property_name()
            date_prop = props.get(date_prop_name, {})
            date_value = date_prop.get("date", {})
            date_str = date_value.get("start", "") if date_value else ""
            end_str = date_value.get("end", "") if date_value else ""

            # Parse times
            start_time = None
            end_time = None
            if date_str and "T" in date_str:
                start_time = date_str.split("T")[1][:5]
            if end_str and "T" in end_str:
                end_time = end_str.split("T")[1][:5]

            # Get Category
            category_prop = props.get("Category", {})
            category_select = category_prop.get("select", {})
            category = category_select.get("name") if category_select else None

            # Get Priority
            priority_prop = props.get("Priority", {})
            priority_select = priority_prop.get("select", {})
            priority = priority_select.get("name") if priority_select else None

            return {
                "id": page_id,
                "text": text,
                "date": date_str[:10] if date_str else None,
                "start_time": start_time,
                "end_time": end_time,
                "category": category,
                "priority": priority
            }

        except Exception as e:
            logger.error(f"Error fetching reminder by ID: {e}")
            return None

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
        # Get the date property name using shared method
        date_prop_name = self._get_date_property_name()
        logger.info(f"Using date property: '{date_prop_name}'")

        # Get database schema for other properties (priority, category)
        try:
            db = self.client.databases.retrieve(database_id=self.reminders_db_id)
            db_properties = db.get("properties", {})
            available_props = {name.lower(): name for name in db_properties.keys()}

        except Exception as e:
            logger.error(f"Error getting database schema: {e}")
            available_props = {}
            date_prop_name = "Date"

        try:
            properties = {
                "Reminder": {"title": [{"text": {"content": text}}]},
                "Enabled": {"checkbox": True}
            }

            # Add date with optional time
            if date:
                logger.info(f"Input date='{date}', start_time='{start_time}', end_time='{end_time}'")
                if start_time:
                    # Include time in the date (Notion requires full ISO format)
                    date_str = f"{date}T{start_time}:00"
                    date_value = {"start": date_str}
                    if end_time:
                        date_value["end"] = f"{date}T{end_time}:00"
                else:
                    # Date only, no time - use just the date string
                    date_value = {"start": date}

                # Set the date property
                if date_prop_name:
                    properties[date_prop_name] = {"date": date_value}
                    logger.info(f"Setting property '{date_prop_name}' to date value: {date_value}")
                    logger.info(f"Full properties being set: {list(properties.keys())}")
                else:
                    logger.error("No date property name found, cannot set date!")
            else:
                logger.info(f"No date provided (date='{date}')")

            # Add priority only if property exists in database
            if priority and "priority" in available_props:
                prop_name = available_props["priority"]
                properties[prop_name] = {"select": {"name": priority}}

            # Add category only if property exists in database
            if category and "category" in available_props:
                prop_name = available_props["category"]
                properties[prop_name] = {"select": {"name": category}}

            logger.info(f"Creating page with properties: {properties}")
            new_page = self.client.pages.create(
                parent={"database_id": self.reminders_db_id},
                properties=properties
            )
            # Log the response to verify what was actually saved
            saved_date = new_page.get("properties", {}).get(date_prop_name, {})
            logger.info(f"Created reminder: {text}")
            logger.info(f"Saved date property: {saved_date}")
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

    def update_reminder(self, page_id: str, text: str = None, date: str = None,
                        start_time: str = None, end_time: str = None,
                        category: str = None, priority: str = None) -> bool:
        """Update an existing reminder.

        Args:
            page_id: The Notion page ID to update
            text: New task text (optional)
            date: New date in YYYY-MM-DD format (optional)
            start_time: New start time in HH:MM format (optional)
            end_time: New end time in HH:MM format (optional)
            category: New category (optional)
            priority: New priority (optional)

        Returns:
            True if successful
        """
        try:
            properties = {}

            # Update text (title)
            if text is not None:
                properties["Reminder"] = {"title": [{"text": {"content": text}}]}

            # Update date/time
            if date is not None or start_time is not None:
                date_prop_name = self._get_date_property_name()

                # Get current date if only updating time
                if date is None:
                    # Fetch current page to get existing date
                    page = self.client.pages.retrieve(page_id=page_id)
                    props = page.get("properties", {})
                    date_prop = props.get(date_prop_name, {})
                    date_value = date_prop.get("date", {})
                    current_date_str = date_value.get("start", "") if date_value else ""
                    if current_date_str:
                        date = current_date_str[:10]  # Extract YYYY-MM-DD
                    else:
                        from datetime import datetime
                        date = datetime.now().strftime("%Y-%m-%d")

                # Build date value
                if start_time:
                    date_str = f"{date}T{start_time}:00"
                    date_value = {"start": date_str}
                    if end_time:
                        date_value["end"] = f"{date}T{end_time}:00"
                else:
                    date_value = {"start": date}

                properties[date_prop_name] = {"date": date_value}

            # Update category
            if category is not None:
                properties["Category"] = {"select": {"name": category}}

            # Update priority
            if priority is not None:
                properties["Priority"] = {"select": {"name": priority}}

            if properties:
                self.client.pages.update(page_id=page_id, properties=properties)
                logger.info(f"Updated reminder {page_id}: {list(properties.keys())}")
                return True
            return False

        except Exception as e:
            logger.error(f"Error updating reminder: {e}")
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

    def check_block_exists(self, name: str, date: str) -> bool:
        """Check if a recurring block already exists for a specific date.

        Args:
            name: The block name (e.g., "Family Time")
            date: Date in YYYY-MM-DD format

        Returns:
            True if block exists, False otherwise
        """
        try:
            # Get the date property name
            date_prop_name = self._get_date_property_name()

            response = self.client.databases.query(
                database_id=self.reminders_db_id,
                filter={
                    "and": [
                        {"property": "Reminder", "title": {"equals": name}},
                        {"property": date_prop_name, "date": {"on_or_after": date}},
                        {"property": date_prop_name, "date": {"on_or_before": date}}
                    ]
                }
            )

            return len(response.get("results", [])) > 0

        except Exception as e:
            logger.error(f"Error checking block exists: {e}")
            return False

    def _get_blocks_from_notion(self) -> list:
        """Fetch recurring blocks configuration from Notion database.

        Expected database properties:
        - Name (title): Block name
        - Start Time (rich_text): HH:MM format
        - End Time (rich_text): HH:MM format
        - Days (multi_select): Mon, Tue, Wed, Thu, Fri, Sat, Sun
        - Start Date (date): When to start creating blocks
        - End Date (date): When to stop (empty = forever)
        - Category (select): Work, Life, Health, Study, Other
        - Priority (select): High, Mid, Low
        - Enabled (checkbox): Active/inactive

        Returns:
            List of block dictionaries
        """
        if not self.recurring_blocks_db_id:
            return []

        try:
            response = self.client.databases.query(
                database_id=self.recurring_blocks_db_id,
                filter={"property": "Enabled", "checkbox": {"equals": True}}
            )

            blocks = []
            for page in response.get("results", []):
                props = page.get("properties", {})

                # Get Name (title)
                name_prop = props.get("Name", {})
                name_title = name_prop.get("title", [])
                name = name_title[0]["text"]["content"] if name_title else ""

                if not name:
                    continue

                # Get Start Time (rich_text)
                start_time_prop = props.get("Start Time", {})
                start_time_text = start_time_prop.get("rich_text", [])
                start_time = start_time_text[0]["text"]["content"] if start_time_text else ""

                # Get End Time (rich_text)
                end_time_prop = props.get("End Time", {})
                end_time_text = end_time_prop.get("rich_text", [])
                end_time = end_time_text[0]["text"]["content"] if end_time_text else ""

                # Get Days (multi_select)
                days_prop = props.get("Days", {})
                days_select = days_prop.get("multi_select", [])
                days = [d["name"] for d in days_select] if days_select else []

                # Get Start Date (date)
                start_date_prop = props.get("Start Date", {})
                start_date_val = start_date_prop.get("date", {})
                start_date = start_date_val.get("start", "") if start_date_val else None

                # Get End Date (date)
                end_date_prop = props.get("End Date", {})
                end_date_val = end_date_prop.get("date", {})
                end_date = end_date_val.get("start", "") if end_date_val else None

                # Get Category (select)
                category_prop = props.get("Category", {})
                category_select = category_prop.get("select", {})
                category = category_select.get("name") if category_select else None

                # Get Priority (select)
                priority_prop = props.get("Priority", {})
                priority_select = priority_prop.get("select", {})
                priority = priority_select.get("name") if priority_select else None

                blocks.append({
                    "name": name,
                    "start_time": start_time,
                    "end_time": end_time,
                    "days": days if days else ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                    "start_date": start_date[:10] if start_date else None,
                    "end_date": end_date[:10] if end_date else None,
                    "category": category,
                    "priority": priority,
                    "enabled": True
                })

            logger.info(f"Loaded {len(blocks)} recurring blocks from Notion database")
            return blocks

        except Exception as e:
            logger.error(f"Error fetching blocks from Notion: {e}")
            return []

    def _get_blocks_from_json(self, config_path: str) -> list:
        """Load recurring blocks from JSON config file.

        Args:
            config_path: Path to schedule_config.json

        Returns:
            List of block dictionaries
        """
        import os

        if not os.path.exists(config_path):
            logger.warning(f"Schedule config not found: {config_path}")
            return []

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            blocks = config.get("recurring_blocks", [])
            logger.info(f"Loaded {len(blocks)} recurring blocks from JSON file")
            return blocks
        except Exception as e:
            logger.error(f"Error loading schedule config: {e}")
            return []

    def create_recurring_blocks(self, config_path: str = "schedule_config.json", days_ahead: int = 7) -> dict:
        """Create recurring time blocks for the next N days.

        Creates blocks for today + next 6 days (7 days total) so they appear
        in Notion Calendar for weekly planning.

        Tries to load blocks from:
        1. Notion database (if recurring_blocks_db_id is configured)
        2. JSON config file (fallback)

        Args:
            config_path: Path to the schedule config JSON file (fallback)
            days_ahead: Number of days to create blocks for (default: 7)

        Returns:
            Dictionary with created count, skipped count, and source
        """
        # Try Notion database first, then fall back to JSON
        if self.recurring_blocks_db_id:
            blocks = self._get_blocks_from_notion()
            source = "notion"
        else:
            blocks = []
            source = None

        # Fall back to JSON if no blocks from Notion
        if not blocks:
            blocks = self._get_blocks_from_json(config_path)
            source = "json" if blocks else None

        if not blocks:
            return {"created": 0, "skipped": 0, "source": None, "error": "No blocks configured"}

        created = 0
        skipped = 0

        # Create blocks for the next N days
        for day_offset in range(days_ahead):
            target_date = datetime.now() + timedelta(days=day_offset)
            target_str = target_date.strftime("%Y-%m-%d")
            day_name = target_date.strftime("%a")  # Mon, Tue, Wed, etc.

            for block in blocks:
                # Skip if disabled
                if not block.get("enabled", True):
                    skipped += 1
                    continue

                # Check date range
                start_date = block.get("start_date")
                end_date = block.get("end_date")

                if start_date and target_str < start_date:
                    skipped += 1
                    continue

                if end_date and target_str > end_date:
                    skipped += 1
                    continue

                # Check day of week
                days = block.get("days", [])
                if days != "*" and day_name not in days:
                    skipped += 1
                    continue

                # Check if already exists
                name = block.get("name", "Block")
                if self.check_block_exists(name, target_str):
                    skipped += 1
                    continue

                # Create the block - preserve category from config
                # Block category = time blocks (show ☀️, not actionable)
                # Study/Work/etc = actionable tasks (can be marked done)
                result = self.create_reminder(
                    text=name,
                    date=target_str,
                    start_time=block.get("start_time"),
                    end_time=block.get("end_time"),
                    priority=block.get("priority"),
                    category=block.get("category")  # Preserve original category
                )

                if result.get("success"):
                    logger.info(f"Created recurring block: {name} for {target_str}")
                    created += 1
                else:
                    logger.error(f"Failed to create block {name}: {result.get('error')}")
                    skipped += 1

        return {"created": created, "skipped": skipped, "source": source}

    def cleanup_old_reminders(self, months_old: int = 3, max_items: int = 1000) -> dict:
        """Archive old completed reminders to keep database clean.

        Cleanup triggers when:
        - Database has more than max_items entries, OR
        - Entry is older than months_old months

        Args:
            months_old: Archive reminders older than this many months
            max_items: Trigger cleanup if database exceeds this count

        Returns:
            Dictionary with archived count and total count
        """
        try:
            # Get all reminders (including disabled/completed)
            response = self.client.databases.query(
                database_id=self.reminders_db_id
            )

            all_items = response.get("results", [])
            total_count = len(all_items)

            # Calculate cutoff date
            cutoff_date = (datetime.now() - timedelta(days=months_old * 30)).strftime("%Y-%m-%d")

            archived = 0
            date_prop_name = self._get_date_property_name()

            for page in all_items:
                props = page.get("properties", {})
                page_id = page["id"]

                # Get date
                date_prop = props.get(date_prop_name, {})
                date_value = date_prop.get("date", {})
                date_str = date_value.get("start", "") if date_value else ""

                # Skip if no date (recurring tasks without specific date)
                if not date_str:
                    continue

                # Check if old enough to archive
                entry_date = date_str[:10] if date_str else ""
                if entry_date and entry_date < cutoff_date:
                    # Archive (soft delete) the page
                    self.client.pages.update(page_id=page_id, archived=True)
                    archived += 1
                    logger.info(f"Archived old reminder: {page_id} (date: {entry_date})")

                # If we've archived enough to get under the limit, stop
                if total_count - archived <= max_items * 0.8:  # Keep 20% buffer
                    break

            logger.info(f"Cleanup complete: archived {archived} of {total_count} reminders")
            return {"archived": archived, "total": total_count}

        except Exception as e:
            logger.error(f"Error cleaning up reminders: {e}")
            return {"archived": 0, "total": 0, "error": str(e)}

    def get_today_schedule(self, effective_date: str = None) -> dict:
        """Get today's full schedule from Reminders database only.

        No more built-in habits - everything comes from Notion databases.

        Args:
            effective_date: Override date string (YYYY-MM-DD) for day boundary support.
                           If before the day boundary (e.g., 4am), this should be yesterday's date.

        Returns:
            Dictionary with:
            - timeline: list of time blocks sorted by start_time
            - actionable_tasks: list of tasks that need action (excludes Life/Health)
            - completed_task_ids: list of already completed task IDs
        """
        habit = self.get_or_create_today_habit(effective_date=effective_date)
        completed_task_ids = habit.get("completed_tasks", [])

        # Get reminders for today (includes recurring blocks created earlier)
        target_date = effective_date or self._get_today_date_str()
        reminders = self.get_all_reminders(for_date=target_date)

        # Categorize tasks
        timeline = []
        actionable_tasks = []

        for r in reminders:
            task = {
                "id": r["id"],
                "text": r["text"],
                "start_time": r.get("start_time"),
                "end_time": r.get("end_time"),
                "category": r.get("category"),
                "priority": r.get("priority"),
                "done": r["id"] in completed_task_ids,
                "is_builtin": False
            }

            # Add to timeline if has time
            if task["start_time"]:
                timeline.append(task)

            # Add to actionable if NOT Block category
            # Block = recurring time blocks (Sleep, Family Time) that can't be marked done
            category = (task.get("category") or "").lower()
            if category != "block":
                actionable_tasks.append(task)

        # Sort timeline by start_time
        timeline.sort(key=lambda x: x.get("start_time") or "99:99")

        return {
            "timeline": timeline,
            "actionable_tasks": actionable_tasks,
            "completed_task_ids": completed_task_ids
        }

    def get_schedule_for_date(self, date_str: str) -> dict:
        """Get schedule for a specific date.

        Args:
            date_str: Date in YYYY-MM-DD format

        Returns:
            Dictionary with timeline, actionable_tasks, completed_task_ids
        """
        # Get completed tasks for this date
        try:
            response = self.client.databases.query(
                database_id=self.tracking_db_id,
                filter={
                    "property": "Date",
                    "title": {"equals": date_str}
                }
            )
            if response.get("results"):
                page = response["results"][0]
                habit = self._parse_habit_page(page)
                completed_task_ids = habit.get("completed_tasks", [])
            else:
                completed_task_ids = []
        except Exception:
            completed_task_ids = []

        # Get reminders for the specified date
        reminders = self.get_all_reminders(for_date=date_str)

        # Categorize tasks
        timeline = []
        actionable_tasks = []

        for r in reminders:
            task = {
                "id": r["id"],
                "text": r["text"],
                "start_time": r.get("start_time"),
                "end_time": r.get("end_time"),
                "category": r.get("category"),
                "priority": r.get("priority"),
                "done": r["id"] in completed_task_ids,
                "is_builtin": False
            }

            # Add to timeline if has time
            if task["start_time"]:
                timeline.append(task)

            # Add to actionable if NOT Block category
            category = (task.get("category") or "").lower()
            if category != "block":
                actionable_tasks.append(task)

        # Sort timeline by start_time
        timeline.sort(key=lambda x: x.get("start_time") or "99:99")

        return {
            "timeline": timeline,
            "actionable_tasks": actionable_tasks,
            "completed_task_ids": completed_task_ids
        }
