# AI Vocabulary Telegram Bot to Notion

A 3-bot Telegram ecosystem for English vocabulary learning with AI-powered analysis, spaced repetition, and habit tracking - all integrated with Notion.

## Architecture

```
main.py (Entry Point)
├── bot.py (Vocab Learner Bot) + ai_handler.py + notion_handler.py
├── review_bot.py (Spaced Repetition) + notion_handler.py
└── habit_bot.py (Daily Habits) + habit_handler.py + youtube_handler.py
```

## Bots Overview

### 1. Vocab Learner Bot (`bot.py`)
- Analyzes English text using Claude AI
- Extracts worth-learning phrases with phonetics, part of speech, examples
- Saves to Notion vocabulary database
- Grammar checking for sentences

### 2. Review Bot (`review_bot.py`)
- Spaced repetition system (SM-2 variant)
- Schedule: 8:00, 13:00, 19:00, 22:00
- Buttons: Again (1 day) / Good (2^n days) / Easy (skip ahead)

### 3. Habit Bot (`habit_bot.py`)
- Daily English practice reminders
- Task management with natural language parsing
- YouTube video recommendations
- Weekly progress summaries

## Key Files

| File | Purpose |
|------|---------|
| `ai_handler.py` | Claude API integration, vocabulary analysis |
| `notion_handler.py` | Notion database operations, spaced repetition |
| `habit_handler.py` | Habit tracking, task management |
| `youtube_handler.py` | YouTube video fetching |
| `video_config.json` | YouTube sources configuration |

## Notion Databases Required

### Vocabulary Database
- English (title), Chinese (text), Explanation (text), Example (text)
- Category (select), Date (date), Review Count (number)
- Next Review (date), Last Reviewed (date)

### Habit Tracking Database
- Date (title), Listened (checkbox), Spoke (checkbox)
- Video (text), Tasks (text - JSON array)

### Reminders Database
- Reminder (title), Enabled (checkbox), Date (date)
- Time (date), Priority (select), Category (select)

## Environment Variables

```
TELEGRAM_BOT_TOKEN=       # Vocab bot token
REVIEW_BOT_TOKEN=         # Review bot token
HABITS_BOT_TOKEN=         # Habit bot token
ANTHROPIC_API_KEY=        # Claude API key
NOTION_API_KEY=           # Notion integration token
NOTION_DATABASE_ID=       # Vocabulary database ID
HABITS_TRACKING_DB_ID=    # Habit tracking database ID
HABITS_REMINDERS_DB_ID=   # Reminders database ID
ALLOWED_USER_IDS=         # Comma-separated user IDs
REVIEW_USER_ID=           # Review bot user ID
HABITS_USER_ID=           # Habits bot user ID
YOUTUBE_API_KEY=          # Optional: YouTube API key
TIMEZONE=Europe/London    # Timezone for scheduling
```

## Spaced Repetition Algorithm

Priority scoring system:
- Due/overdue words: 150 + (days_overdue * 5) points
- New words (never reviewed): 150 points (equal to due words)
- Not yet due: 30 - (days_until * 3) points
- Lower review count bonus: max 30 points
- Recent addition bonus: max 20 points

Intervals:
- Again: Tomorrow, reset count
- Good: 2^count days (1→2→4→8→16→32→60 max)
- Easy: 2^(count+1) days, count += 2

## Commands

### Vocab Bot
- `/start`, `/help`, `/test`, `/clear`

### Review Bot
- `/review` - Manual review trigger
- `/due` - Show pending reviews and total word count
- `/stop`, `/resume`, `/status`

### Habit Bot
- `/habits` - Today's tasks
- `/add <task>` or natural language task input
- `/video`, `/week`, `/stop`, `/resume`, `/status`

## Development Notes

- Uses `python-telegram-bot` v22.6+
- APScheduler for cron-like scheduling
- Anthropic Claude Sonnet for AI analysis
- All bots run as separate processes via `main.py`

## Testing

```bash
python bot.py      # Test vocab bot alone
python review_bot.py  # Test review bot alone
python habit_bot.py   # Test habit bot alone
python main.py     # Run all bots together
```
