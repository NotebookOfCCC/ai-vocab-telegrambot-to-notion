# AI Vocabulary Telegram Bot to Notion

A 3-bot Telegram ecosystem for English vocabulary learning with AI-powered analysis, spaced repetition, and habit tracking - all integrated with Notion.

## Architecture

```
main.py (Entry Point)
├── bot.py (Vocab Learner Bot) + ai_handler.py + notion_handler.py
├── review_bot.py (Spaced Repetition) + notion_handler.py
└── habit_bot.py (Task Bot) + habit_handler.py + task_parser.py
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
- **Multi-database support**: Can query from multiple Notion databases
- **No API cost** (just Notion queries)

### 3. Task Bot (`habit_bot.py`)
- **Consolidated schedule view** - One message with numbered timeline + actionable tasks
- **Block category** - Recurring time blocks (Sleep, Family Time) show ☀️ in timeline, not actionable
- **All other categories scored** - Study, Work, Life, Health, Other tasks are actionable and graded
- **Number-based completion** - Reply "1 3" to mark tasks #1 and #3 as done
- **Edit tasks** - Type "edit 1" to edit task #1, or use Edit button on new tasks
- **AI-powered task parsing** - Uses Haiku for accurate natural language understanding (~$0.001/task)
- **Date selector** - /tasks shows buttons to view schedule for next 7 days
- **7-day recurring blocks** - /blocks creates blocks for next 7 days (also auto-creates at 6am)
- **Conflict detection** - Warns when creating task at same time as existing task
- **Configurable day boundary** - Default 4am, so late night work counts for previous day
- **Configurable timezone** - Change via /settings (affects all scheduling)
- **Daily scoring** - Evening wind-down shows A/B/C/D grade for all tasks (except Block)
- **Weekly summary** - Sunday 8pm summary with daily scores and streak
- **Auto-cleanup** - Monthly cleanup of tasks older than 3 months

## Key Files

| File | Purpose | API Cost |
|------|---------|----------|
| `ai_handler.py` | Claude API for vocab analysis | ~$0.01/word |
| `task_parser.py` | Regex task parsing (fallback) | **FREE** |
| `notion_handler.py` | Notion database operations (with retry) | FREE |
| `habit_handler.py` | Task tracking, task management | FREE |
| `schedule_config.json` | Recurring blocks configuration | - |

## Cost Optimization

### Vocab Bot (ai_handler.py)
- **Common words list** (~300 words): Returns "basic vocabulary" response, no API call
- **Dynamic max_tokens**:
  - Short phrases (1-3 words): 800 tokens
  - Sentences: 1000 tokens
- **Model selection by task**:
  - Main analysis: Claude Sonnet 4 (`claude-sonnet-4-20250514`) - quality matters
  - Modifications: Claude Sonnet 3.5 (`claude-3-5-sonnet-20241022`) - ~2x cheaper
  - Entry detection: Claude Sonnet 3.5 - ~2x cheaper

### Task Bot (habit_bot.py)
- **Primary**: Claude Haiku for AI parsing (~$0.001/task)
- **Fallback**: Regex patterns (task_parser.py) if no API key
- Parses Chinese: 今天, 明天, 后天, 周六, 上午/下午/晚上 + 时间
- Parses English: today, tomorrow, saturday, 3pm, "4pm to 5pm"
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
- Mastered (Checkbox) - auto-checked when review_count >= 7, excluded from reviews
```

### Task Tracking Database
```
- Date (Title) - format: YYYY-MM-DD
- Tasks (Rich text) - JSON array of completed task IDs
```

### Reminders Database
```
- Reminder (Title) - task description
- Created Date (Date) - when task was created [auto or optional]
- Date (Date) - scheduled date/time with optional end time for time blocks
- Enabled (Checkbox) - active/inactive
- Priority (Select) - High, Mid, Low [optional]
- Category (Select) - Work, Life, Health, Study, Other, Block [optional]
```

**Categories:**
- **Block** - Recurring time blocks (Sleep, Family Time) - show ☀️ in timeline, NOT actionable, NOT scored
- **Study, Work, Life, Health, Other** - User tasks - actionable and scored

**Note**: Tasks with start/end times (e.g., "3pm-5pm") appear as time blocks in Notion Calendar.

## Environment Variables

```bash
# Telegram Bots
TELEGRAM_BOT_TOKEN=       # Vocab bot token
REVIEW_BOT_TOKEN=         # Review bot token
HABITS_BOT_TOKEN=         # Habit bot token

# API Keys
ANTHROPIC_API_KEY=        # Claude API key (for vocab analysis + task parsing)
NOTION_API_KEY=           # Notion integration token

# Notion Databases
NOTION_DATABASE_ID=       # Primary vocabulary database ID (for saving)
ADDITIONAL_DATABASE_IDS=  # Optional: comma-separated additional DB IDs for review
HABITS_TRACKING_DB_ID=    # Habit tracking database ID
HABITS_REMINDERS_DB_ID=   # Reminders database ID
RECURRING_BLOCKS_DB_ID=   # Optional: Recurring time blocks database ID

# User IDs
ALLOWED_USER_IDS=         # Comma-separated user IDs for vocab bot
REVIEW_USER_ID=           # Review bot user ID
HABITS_USER_ID=           # Habits bot user ID

# Settings
TIMEZONE=Europe/London    # Timezone for scheduling
REVIEW_HOURS=8,13,17,19,22  # Review schedule hours (comma-separated)
WORDS_PER_BATCH=20        # Words per review batch
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

Mastery:
- Words with review_count >= 7 are auto-marked as **Mastered** (checkbox in Notion)
- Mastered words are excluded from review batches and stats
- Uncheck Mastered in Notion to bring a word back into review

## Commands

### Vocab Bot
- `/start`, `/help`, `/test`, `/clear`

### Review Bot
- `/review` - Manual review trigger
- `/due` - Show review stats (overdue, due today, new, total)
- `/stop`, `/resume`, `/status`

### Task Bot
- `/tasks` - Today's schedule with date selector (view next 7 days)
- `/blocks` - Manually create recurring blocks for next 7 days
- `/settings` - Configure day boundary (default 4am) and timezone
- `/stop`, `/resume`, `/status` - Pause/resume reminders
- **Mark done**: Reply "1 3" to mark tasks #1 and #3 as done
- **Edit task**: Type "edit 1" to edit task #1 (date, time, text, category, delete)
- **Add task**: Send natural language like "4pm to 5pm job application" (AI parses it, shows Edit button)

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

## Recurring Time Blocks

Configure automatic time blocks via Notion database.

### Notion Database Setup

Create a Notion database called "Recurring Blocks" with these properties:

| Property | Type | Description |
|----------|------|-------------|
| Name | Title | Block name (e.g., "Family Time") |
| Start Time | Text | HH:MM format (e.g., "17:00") |
| End Time | Text | HH:MM format (e.g., "22:00") |
| Days | Multi-select | Mon, Tue, Wed, Thu, Fri, Sat, Sun |
| Start Date | Date | When to start creating blocks |
| End Date | Date | When to stop (leave empty = forever) |
| Category | Select | Work, Life, Health, Study, Other |
| Priority | Select | High, Mid, Low |
| Enabled | Checkbox | Active/inactive |

Then add the database ID to your `.env`:
```bash
RECURRING_BLOCKS_DB_ID=your_database_id_here
```

**Schedule:** Blocks are created automatically at 6:00 AM daily for the next 7 days.

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

## Multi-Database Support

For large vocabularies, you can split entries across multiple Notion databases:

1. **Vocab Bot**: Saves to `NOTION_DATABASE_ID` (primary database)
2. **Review Bot**: Queries from ALL databases (primary + additional)

### Setup
```bash
# Primary database (used for saving new words)
NOTION_DATABASE_ID=your_primary_db_id

# Additional databases for review (comma-separated, optional)
ADDITIONAL_DATABASE_IDS=second_db_id,third_db_id
```

### Workflow
1. When your primary database reaches ~2000 words, create a new Notion database
2. Copy the new database ID
3. Move your old `NOTION_DATABASE_ID` to `ADDITIONAL_DATABASE_IDS`
4. Set the new database ID as `NOTION_DATABASE_ID`
5. New words save to the new database, reviews pull from all databases

## Recent Changes

1. **Phonetics**: Added IPA for uncommon words
2. **Part of speech**: Labels like (n.), (v.), (adj.)
3. **Multiple meanings**: Numbered explanations with matching examples
4. **Equal priority**: New words mixed with due words
5. **FREE task parsing**: Regex-based, no API cost
6. **Cost optimization**: Skip common words, dynamic token limits
7. **Total word count**: Shown in `/due` command
8. **Notion API retry**: Auto-retry (3x with backoff) for transient API errors
9. **Multi-database review**: Review bot can query from multiple Notion databases
10. **Fixed "New" label**: Now means "never reviewed" (not just review_count=0)
11. **Phrase override**: When modifying entries, explicit phrases in quotes are preserved exactly
12. **Sonnet 3.5 for secondary tasks**: Modifications and detection use Sonnet 3.5 (~2x cheaper), main analysis uses Sonnet 4
13. **Time blocking**: Tasks with time ranges appear in Notion Calendar (use with Notion Calendar app)
14. **Simplified commands**: Removed `/add` and `/tmr` - use natural language instead (e.g., "明天3点开会")
15. **Recurring blocks**: Auto-create daily time blocks from Notion database
16. **Consolidated schedule**: One message with timeline + tasks instead of multiple messages
17. **Number-based completion**: Reply "1 3" to mark tasks done (no more button spam)
18. **Smart categories**: Life/Health tasks show in timeline only - no action buttons needed
19. **Evening wind-down**: 10 PM reminder to prepare for sleep instead of regular check-in
20. **Auto-cleanup**: Monthly cleanup of tasks older than 3 months (keeps database clean)
21. **Simplified system**: Removed built-in habits, video recommendations, and weekly summary - all tasks from Notion databases
22. **AI task parsing**: Uses Haiku for accurate natural language parsing (handles "4pm to 5pm this afternoon" correctly)
23. **7-day recurring blocks**: Creates blocks for next 7 days so Notion Calendar shows full week
24. **Block category**: New category for recurring time blocks - show ☀️, not actionable, not scored
25. **Edit task feature**: Edit button on new tasks, or type "edit 1" to edit task #1
26. **Date selector**: /tasks shows buttons to view schedule for any day in next 7 days
27. **/blocks command**: Manually create recurring blocks (also auto-creates at 6am)
28. **Conflict detection**: Warns when creating task at same time as existing task
29. **All categories scored**: Life/Health tasks now count toward daily score (only Block excluded)
30. **Cleaner formatting**: Numbered schedule, sun icon for blocks, no duplicate headers
31. **Word mastery**: Auto-mark words as Mastered after 7+ reviews, excluded from future reviews, shown in /due stats
