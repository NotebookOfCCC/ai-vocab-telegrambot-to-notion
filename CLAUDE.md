# AI Vocabulary Telegram Bot to Notion

A 3-bot Telegram ecosystem for English vocabulary learning with AI-powered analysis, spaced repetition, and habit tracking - all integrated with Notion.

## Architecture

```
main.py (Entry Point)
├── bot.py (Vocab Learner Bot) + ai_handler.py + notion_handler.py
├── review_bot.py (Spaced Repetition) + notion_handler.py
└── habit_bot.py (Daily Habits) + habit_handler.py + task_parser.py + youtube_handler.py
```

## Bots Overview

### 1. Vocab Learner Bot (`bot.py`)
- Analyzes English text using Claude AI (Sonnet)
- Extracts worth-learning phrases with phonetics, part of speech, examples
- Multiple meanings shown with numbered examples
- Grammar checking for sentences
- Saves to Notion vocabulary database
- **Cost optimized**: Skips API for ~300 common words

### 2. Review Bot (`review_bot.py`)
- Spaced repetition system (SM-2 variant)
- Schedule: 8:00, 13:00, 19:00, 22:00
- Buttons: Again (1 day) / Good (2^n days) / Easy (skip ahead)
- New words and due words have equal priority
- Shows total word count in `/due` command
- **No API cost** (just Notion queries)

### 3. Habit Bot (`habit_bot.py`)
- Daily English practice reminders
- **FREE natural language task parsing** (regex-based, no AI)
- Parses: "明天下午3点开会" → date, time, priority, category
- YouTube video recommendations
- Weekly progress summaries
- **No API cost** for task management

## Key Files

| File | Purpose | API Cost |
|------|---------|----------|
| `ai_handler.py` | Claude API for vocab analysis | ~$0.01/word |
| `task_parser.py` | Regex task parsing | **FREE** |
| `notion_handler.py` | Notion database operations | FREE |
| `habit_handler.py` | Habit tracking, task management | FREE |
| `youtube_handler.py` | YouTube video fetching | FREE |
| `video_config.json` | YouTube sources configuration | - |

## Cost Optimization

### Vocab Bot (ai_handler.py)
- **Common words list** (~300 words): Returns "basic vocabulary" response, no API call
- **Dynamic max_tokens**:
  - Short phrases (1-3 words): 800 tokens
  - Sentences: 1000 tokens
- Model: Claude Sonnet 4 (`claude-sonnet-4-20250514`)

### Habit Bot (task_parser.py)
- **100% FREE** - uses regex patterns, no API
- Parses Chinese: 今天, 明天, 后天, 周六, 上午/下午/晚上 + 时间
- Parses English: today, tomorrow, saturday, 3pm
- Auto-infers category: Work, Life, Health, Study, Other
- Auto-infers priority: High, Mid, Low

### Review Bot
- **100% FREE** - no AI, just Notion queries

### Estimated Daily Cost
- Light usage: ~£0.30/day
- Normal usage: ~£0.50-0.80/day
- Heavy usage: ~£1.00/day

## Notion Databases Required

### Vocabulary Database
```
- English (Title) - word/phrase with phonetic and part of speech
- Chinese (Rich text) - translation
- Explanation (Rich text) - 2-3 sentence Chinese explanation
- Example (Rich text) - English + Chinese examples (numbered if multiple meanings)
- Category (Select) - 固定词组, 口语, 新闻, 职场, 学术词汇, 写作, 情绪, 科技, 其他
- Date (Date) - when added
- Review Count (Number) - tracks review iterations
- Next Review (Date) - calculated review date
- Last Reviewed (Date) - most recent review date
```

### Habit Tracking Database
```
- Date (Title) - format: YYYY-MM-DD
- Listened (Checkbox) - listened to English content
- Spoke (Checkbox) - spoke English
- Video (Rich text) - stores YouTube URL
- Tasks (Rich text) - JSON array of completed task IDs
```

### Reminders Database
```
- Reminder (Title) - task description
- Enabled (Checkbox) - active/inactive
- Date (Date) - optional, supports datetime for time-specific tasks
- Priority (Select) - High, Mid, Low [optional]
- Category (Select) - Work, Life, Health, Study, Other [optional]
```

## Environment Variables

```bash
# Telegram Bots
TELEGRAM_BOT_TOKEN=       # Vocab bot token
REVIEW_BOT_TOKEN=         # Review bot token
HABITS_BOT_TOKEN=         # Habit bot token

# API Keys
ANTHROPIC_API_KEY=        # Claude API key (for vocab analysis)
NOTION_API_KEY=           # Notion integration token
YOUTUBE_API_KEY=          # Optional: YouTube API key

# Notion Databases
NOTION_DATABASE_ID=       # Vocabulary database ID
HABITS_TRACKING_DB_ID=    # Habit tracking database ID
HABITS_REMINDERS_DB_ID=   # Reminders database ID

# User IDs
ALLOWED_USER_IDS=         # Comma-separated user IDs for vocab bot
REVIEW_USER_ID=           # Review bot user ID
HABITS_USER_ID=           # Habits bot user ID

# Settings
TIMEZONE=Europe/London    # Timezone for scheduling
```

## Spaced Repetition Algorithm

Priority scoring system (in `notion_handler.py`):
- Due/overdue words: 150 + (days_overdue * 5) points
- New words (never reviewed): **150 points** (equal to due words!)
- Not yet due: 30 - (days_until * 3) points
- Lower review count bonus: max 30 points
- Recent addition bonus: max 20 points

Intervals:
- **Again (🔴)**: Tomorrow, reset count to 0
- **Good (🟡)**: 2^count days (1→2→4→8→16→32→60 max)
- **Easy (🟢)**: 2^(count+1) days, count += 2

## Commands

### Vocab Bot
- `/start`, `/help`, `/test`, `/clear`

### Review Bot
- `/review` - Manual review trigger
- `/due` - Show pending reviews + total word count
- `/stop`, `/resume`, `/status`

### Habit Bot
- `/habits` - Today's tasks
- `/add <task>` - Add task manually
- `/tmr <task>` - Add task for tomorrow
- `/video`, `/week`, `/stop`, `/resume`, `/status`
- **Natural language**: Just type "明天下午3点开会"

## Task Parser Patterns

The regex-based task parser (`task_parser.py`) recognizes:

### Date Patterns
- Chinese: 今天, 明天, 后天, 本周六, 周日, X月X日
- English: today, tomorrow, saturday, sunday

### Time Patterns
- Chinese: 上午/下午/晚上 + X点, 中午
- English: 3pm, 15:00, 3:30pm

### Category Keywords
- Work: 开会, 会议, 工作, meeting, work, office
- Study: 学习, 看书, study, learn, class
- Health: 运动, 健身, gym, exercise
- Life: 吃饭, 约, 朋友, dinner, party

### Priority Keywords
- High: 紧急, urgent, 重要, important, 必须
- Low: 不急, 随便, maybe

## Development Notes

- Uses `python-telegram-bot` v22.6+
- APScheduler for cron-like scheduling
- Anthropic Claude Sonnet for AI analysis
- All bots run as separate processes via `main.py`

## Testing

```bash
python bot.py         # Test vocab bot alone
python review_bot.py  # Test review bot alone
python habit_bot.py   # Test habit bot alone
python main.py        # Run all bots together
```

## Recent Changes

1. **Phonetics**: Added IPA for uncommon words
2. **Part of speech**: Labels like (n.), (v.), (adj.)
3. **Multiple meanings**: Numbered explanations with matching examples
4. **Equal priority**: New words mixed with due words
5. **FREE task parsing**: Regex-based, no API cost
6. **Cost optimization**: Skip common words, dynamic token limits
7. **Total word count**: Shown in `/due` command
