"""
Task Parser - FREE regex-based task parsing (no AI needed)

Parses common Chinese/English date and time patterns without API calls.
Falls back to AI only for complex/ambiguous inputs.
"""
import re
from datetime import datetime, timedelta


class TaskParser:
    """Parse natural language tasks using regex patterns (FREE - no API)."""

    def __init__(self, timezone: str = "Europe/London"):
        self.timezone = timezone

    def parse(self, text: str) -> dict:
        """Parse task text into structured data.

        Returns:
            {
                "task": str,  # cleaned task description
                "date": str or None,  # YYYY-MM-DD
                "start_time": str or None,  # HH:MM
                "end_time": str or None,  # HH:MM
                "priority": str,  # High, Mid, Low
                "category": str,  # Work, Life, Health, Study, Other
                "success": bool
            }
        """
        today = datetime.now()
        result = {
            "task": text,
            "date": None,
            "start_time": None,
            "end_time": None,
            "priority": "Mid",
            "category": "Life",
            "success": True
        }

        # Extract and remove date patterns
        text, date = self._extract_date(text, today)
        result["date"] = date

        # Extract and remove time patterns
        text, start_time, end_time = self._extract_time(text)
        result["start_time"] = start_time
        result["end_time"] = end_time

        # Debug logging
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"TaskParser extracted: date='{date}', start_time='{start_time}', end_time='{end_time}'")

        # Clean up the task text
        result["task"] = self._clean_task_text(text)

        # Infer category from keywords
        result["category"] = self._infer_category(text)

        # Infer priority from keywords
        result["priority"] = self._infer_priority(text)

        return result

    def _extract_date(self, text: str, today: datetime) -> tuple:
        """Extract date from text and return (remaining_text, date_str)."""
        date = None

        # Today patterns
        if re.search(r'今天|today', text, re.IGNORECASE):
            date = today.strftime("%Y-%m-%d")
            text = re.sub(r'今天|today', '', text, flags=re.IGNORECASE)

        # Tomorrow patterns
        elif re.search(r'明天|明日|tomorrow', text, re.IGNORECASE):
            date = (today + timedelta(days=1)).strftime("%Y-%m-%d")
            text = re.sub(r'明天|明日|tomorrow', '', text, flags=re.IGNORECASE)

        # Day after tomorrow
        elif re.search(r'后天|後天', text):
            date = (today + timedelta(days=2)).strftime("%Y-%m-%d")
            text = re.sub(r'后天|後天', '', text)

        # This weekend/Saturday/Sunday
        elif re.search(r'这?周六|本周六|this saturday|saturday', text, re.IGNORECASE):
            days_until_saturday = (5 - today.weekday()) % 7
            if days_until_saturday == 0:
                days_until_saturday = 7
            date = (today + timedelta(days=days_until_saturday)).strftime("%Y-%m-%d")
            text = re.sub(r'这?周六|本周六|this saturday|saturday', '', text, flags=re.IGNORECASE)

        elif re.search(r'这?周日|本周日|周天|this sunday|sunday', text, re.IGNORECASE):
            days_until_sunday = (6 - today.weekday()) % 7
            if days_until_sunday == 0:
                days_until_sunday = 7
            date = (today + timedelta(days=days_until_sunday)).strftime("%Y-%m-%d")
            text = re.sub(r'这?周日|本周日|周天|this sunday|sunday', '', text, flags=re.IGNORECASE)

        # Next week patterns
        elif re.search(r'下周一|next monday', text, re.IGNORECASE):
            days_until = (7 - today.weekday()) % 7 + 0
            if days_until <= 0:
                days_until += 7
            date = (today + timedelta(days=days_until)).strftime("%Y-%m-%d")
            text = re.sub(r'下周一|next monday', '', text, flags=re.IGNORECASE)

        # Tonight
        elif re.search(r'今晚|tonight', text, re.IGNORECASE):
            date = today.strftime("%Y-%m-%d")
            text = re.sub(r'今晚|tonight', '', text, flags=re.IGNORECASE)

        # Specific date: MM月DD日 or MM/DD
        date_match = re.search(r'(\d{1,2})月(\d{1,2})[日号]?', text)
        if date_match:
            month, day = int(date_match.group(1)), int(date_match.group(2))
            year = today.year
            if month < today.month or (month == today.month and day < today.day):
                year += 1
            date = f"{year}-{month:02d}-{day:02d}"
            text = re.sub(r'\d{1,2}月\d{1,2}[日号]?', '', text)

        return text, date

    def _chinese_num_to_int(self, chinese: str) -> int:
        """Convert Chinese numeral to integer (1-12 for hours)."""
        mapping = {
            '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
            '六': 6, '七': 7, '八': 8, '九': 9, '十': 10,
            '十一': 11, '十二': 12, '两': 2
        }
        # Direct mapping for simple cases
        if chinese in mapping:
            return mapping[chinese]
        # Handle 十X pattern (e.g., 十一 = 11, 十二 = 12)
        if chinese.startswith('十') and len(chinese) == 2:
            return 10 + mapping.get(chinese[1], 0)
        return None

    def _extract_time(self, text: str) -> tuple:
        """Extract time from text and return (remaining_text, start_time, end_time)."""
        start_time = None
        end_time = None

        # Chinese time with Chinese numerals: 上午十一点, 下午三点
        cn_time_match = re.search(r'(上午|下午|晚上|早上|中午)?(十?[一二三四五六七八九十两])[点點時]', text)
        if cn_time_match:
            period = cn_time_match.group(1) or ""
            cn_num = cn_time_match.group(2)
            hour = self._chinese_num_to_int(cn_num)

            if hour:
                # Convert to 24-hour format
                if period in ['下午', '晚上'] and hour < 12:
                    hour += 12
                elif period == '上午' and hour == 12:
                    hour = 0
                elif period == '中午':
                    hour = 12

                start_time = f"{hour:02d}:00"
                end_hour = min(hour + 2, 23)
                end_time = f"{end_hour:02d}:00"

                # Remove matched text
                text = text[:cn_time_match.start()] + text[cn_time_match.end():]
                return text, start_time, end_time

        # Chinese time patterns with Arabic numerals: 上午11点, 3点
        time_match = re.search(r'(上午|下午|晚上|早上|中午)?(\d{1,2})[点點時:：](\d{2})?', text)
        if time_match:
            period = time_match.group(1) or ""
            hour = int(time_match.group(2))
            minute = int(time_match.group(3)) if time_match.group(3) else 0

            # Convert to 24-hour format
            if period in ['下午', '晚上'] and hour < 12:
                hour += 12
            elif period == '上午' and hour == 12:
                hour = 0
            elif period == '中午':
                hour = 12

            start_time = f"{hour:02d}:{minute:02d}"

            # Estimate end time (2 hours for most activities)
            end_hour = hour + 2
            if end_hour >= 24:
                end_hour = 23
            end_time = f"{end_hour:02d}:{minute:02d}"

            text = re.sub(r'(上午|下午|晚上|早上|中午)?(\d{1,2})[点時:：](\d{2})?', '', text)

        # English time patterns: 3pm, 3:30pm
        time_match = re.search(r'(\d{1,2}):?(\d{2})?\s*(am|pm|AM|PM)?', text)
        if time_match and not start_time:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2)) if time_match.group(2) else 0
            period = time_match.group(3)

            if period and period.lower() == 'pm' and hour < 12:
                hour += 12
            elif period and period.lower() == 'am' and hour == 12:
                hour = 0

            if 0 <= hour <= 23:
                start_time = f"{hour:02d}:{minute:02d}"
                end_hour = min(hour + 2, 23)
                end_time = f"{end_hour:02d}:{minute:02d}"
                text = re.sub(r'(\d{1,2}):?(\d{2})?\s*(am|pm|AM|PM)?', '', text, count=1)

        return text, start_time, end_time

    def _clean_task_text(self, text: str) -> str:
        """Clean up task text by removing extra punctuation and whitespace."""
        # Remove common filler words and punctuation
        text = re.sub(r'[，,。.！!？?、]+', ' ', text)
        text = re.sub(r'\s+', ' ', text)
        text = text.strip()

        # If task is empty after cleaning, return a default
        if not text:
            text = "Task"

        return text

    def _infer_category(self, text: str) -> str:
        """Infer category from keywords."""
        text_lower = text.lower()

        if re.search(r'开会|会议|工作|meeting|work|office|报告|report', text_lower):
            return "Work"
        elif re.search(r'学习|看书|读书|study|learn|课|class|homework', text_lower):
            return "Study"
        elif re.search(r'运动|健身|跑步|gym|exercise|workout|health|医', text_lower):
            return "Health"
        elif re.search(r'吃饭|约|朋友|玩|看|show|movie|dinner|lunch|party', text_lower):
            return "Life"
        else:
            return "Other"

    def _infer_priority(self, text: str) -> str:
        """Infer priority from keywords."""
        text_lower = text.lower()

        if re.search(r'紧急|urgent|重要|important|必须|must|asap', text_lower):
            return "High"
        elif re.search(r'不急|随便|maybe|可能', text_lower):
            return "Low"
        else:
            return "Mid"

    def format_confirmation(self, parsed: dict) -> str:
        """Format parsed task for confirmation message."""
        lines = ["✅ 已添加任务！", ""]

        # Time
        if parsed.get("start_time"):
            time_str = f"• 时间：{parsed.get('date', '今天')} {parsed['start_time']}"
            if parsed.get("end_time"):
                time_str += f"-{parsed['end_time']}"
            lines.append(time_str)
        elif parsed.get("date"):
            lines.append(f"• 日期：{parsed['date']}")

        # Task
        lines.append(f"• 事项：{parsed.get('task', '')}")

        # Priority
        priority_emoji = {"High": "🔴", "Mid": "🟡", "Low": "🟢"}.get(parsed.get("priority", "Mid"), "🟡")
        lines.append(f"• 优先级：{priority_emoji} {parsed.get('priority', 'Mid')}")

        # Category
        lines.append(f"• 类别：{parsed.get('category', 'Other')}")

        return "\n".join(lines)
