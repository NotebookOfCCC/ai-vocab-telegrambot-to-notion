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


TASK_SYSTEM_PROMPT = """You parse task input into JSON. Respond with ONLY valid JSON, no other text.

RULES:
- "今天/today" = current date
- "明天/tomorrow" = next day
- "后天" = day after tomorrow
- "今晚/tonight" = today, start_time "19:00"
- "下午/afternoon" = start_time "14:00"
- "上午/morning" = start_time "09:00"
- "晚上/evening" = start_time "19:00"
- "中午/noon" = start_time "12:00"
- Convert 12h to 24h: "3pm" = "15:00", "下午3点" = "15:00"
- Estimate end_time: meal=2h, meeting=1h, exercise=1h, study=2h
- If no time mentioned, set start_time and end_time to null

PRIORITY rules:
- High: 紧急, urgent, 重要, important, 必须, ASAP
- Low: 不急, maybe, 随便, 有空
- Mid: everything else (default)

CATEGORY rules:
- Work: 开会, 会议, 工作, meeting, work, office, 报告, 项目
- Study: 学习, 看书, study, learn, class, 课, 作业
- Health: 运动, 健身, gym, exercise, 跑步, 游泳
- Life: 吃饭, 约, dinner, party, 购物, 买, 朋友
- Other: anything else (default)

OUTPUT FORMAT:
{"task": "original language description", "date": "YYYY-MM-DD", "start_time": "HH:MM or null", "end_time": "HH:MM or null", "priority": "High|Mid|Low", "category": "Work|Life|Health|Study|Other", "parsed_summary": "Chinese summary"}

EXAMPLE:
Input: "明天下午3点开会"
Output: {"task": "开会", "date": "2025-01-02", "start_time": "15:00", "end_time": "16:00", "priority": "Mid", "category": "Work", "parsed_summary": "明天下午3点开会，预计1小时"}

Input: "tonight dinner with Justin"
Output: {"task": "dinner with Justin", "date": "2025-01-01", "start_time": "19:00", "end_time": "21:00", "priority": "Mid", "category": "Life", "parsed_summary": "今晚和Justin吃饭"}"""


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
                model="claude-haiku-4-5-20251001",
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
