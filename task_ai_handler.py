"""
Task AI Handler - Natural language task parsing using Claude API

Parses natural language task input like "今晚6点和Justin约饭" into structured data:
- Time
- Task description
- Priority
- Category
"""
import anthropic
import json
import re
from datetime import datetime, timedelta


TASK_SYSTEM_PROMPT = """You are a task/schedule assistant that parses natural language task input.

Given user input in Chinese or English, extract:
1. Task description (事项)
2. Time/date (时间) - convert to specific datetime if possible
3. Duration estimate (if mentioned or can be reasonably estimated)
4. Priority (优先级): High, Mid, Low - infer from context/urgency words
5. Category (类别): Work, Life, Health, Study, Other - infer from task content

IMPORTANT:
- "今天/today" = current date
- "明天/tomorrow" = next day
- "今晚/tonight" = today evening (default 19:00-21:00 if no specific time)
- "下午/afternoon" = 14:00-17:00 range
- Convert 12-hour to 24-hour format
- If only start time mentioned, estimate reasonable end time (e.g., meal = 2 hours, meeting = 1 hour)

OUTPUT FORMAT (strict JSON):
{
  "task": "task description in user's original language",
  "date": "YYYY-MM-DD",
  "start_time": "HH:MM" or null,
  "end_time": "HH:MM" or null,
  "priority": "High" | "Mid" | "Low",
  "category": "Work" | "Life" | "Health" | "Study" | "Other",
  "parsed_summary": "Brief summary of what was understood, in Chinese"
}

Respond with valid JSON only."""


class TaskAIHandler:
    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)

    def _get_current_datetime_context(self) -> str:
        """Get current datetime context for the AI."""
        now = datetime.now()
        return f"Current datetime: {now.strftime('%Y-%m-%d %H:%M')} ({now.strftime('%A')})"

    def _try_parse_json(self, text: str) -> dict:
        """Try to parse JSON from response."""
        # Remove markdown code blocks if present
        cleaned = text.strip()
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r'\s*```\s*$', '', cleaned)
        cleaned = cleaned.strip()

        # Try to extract JSON object
        json_match = re.search(r'\{[\s\S]*\}', cleaned)
        if json_match:
            return json.loads(json_match.group())

        return json.loads(cleaned)

    def parse_task(self, user_input: str, timezone: str = "Europe/London") -> dict:
        """Parse natural language task input into structured data.

        Args:
            user_input: Natural language task description
            timezone: User's timezone

        Returns:
            Dictionary with parsed task data or error
        """
        context = self._get_current_datetime_context()

        prompt = f"""{context}
User timezone: {timezone}

User input: {user_input}

Parse this into a structured task."""

        try:
            # Use Haiku for cost efficiency - task parsing is simple enough
            message = self.client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=300,
                system=TASK_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = message.content[0].text
            result = self._try_parse_json(response_text)
            result["success"] = True
            return result

        except json.JSONDecodeError as e:
            return {"success": False, "error": f"Failed to parse AI response: {e}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def format_task_confirmation(self, parsed: dict) -> str:
        """Format parsed task for confirmation message.

        Args:
            parsed: Parsed task dictionary

        Returns:
            Formatted confirmation message
        """
        if not parsed.get("success"):
            return f"解析失败: {parsed.get('error', 'Unknown error')}"

        lines = ["✅ 已经安排好！任务已添加到你的日程中。", "", "安排详情："]

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
