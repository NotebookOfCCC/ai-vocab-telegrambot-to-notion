# Vocab Learning Telegram Bot

A Telegram bot system that helps you learn English vocabulary with AI-powered explanations, automatic saving to Notion, scheduled reviews, and daily task management with Notion Calendar integration.

## Features

### Vocab Learner Bot (`bot.py`)
- **Grammar Check**: Automatically corrects grammar in sentences
- **Phrase Extraction**: Extracts learnable phrases from sentences
- **AI Explanations**: Provides Chinese explanations, examples, and categorization
- **Phonetics**: Adds IPA pronunciation for uncommon words
- **Part of Speech**: Labels words with (n.), (v.), (adj.), etc.
- **Multiple Meanings**: Shows numbered meanings with corresponding examples
- **Notion Integration**: Saves vocabulary entries directly to your Notion database
- **Cost Optimized**: Skips API for common words, uses dynamic token limits

### Review Bot (`review_bot.py`)
- **Spaced Repetition**: Smart scheduling based on review performance
- **Scheduled Reviews**: Sends vocabulary reviews at 8:00, 13:00, 19:00, 22:00
- **3-Button System**: Again (review tomorrow), Good (normal interval), Easy (longer interval)
- **Equal Priority**: New words and due words have same priority (mixed reviews)
- **Multi-Database**: Supports querying from multiple Notion databases
- **Reliable Fetching**: Auto-retry (3x with exponential backoff) for Notion API errors

### Task Bot (`habit_bot.py`)
- **AI Task Parsing**: Natural language task input with Claude Haiku - just type "4pm to 5pm job application" or "明天下午3点开会"
- **Consolidated Schedule**: One message showing timeline + actionable tasks
- **Notion Calendar Integration**: Recurring time blocks sync to Notion Calendar for time blocking
- **Smart Categories**: Life/Health tasks (Family Time, Sleep) show in timeline only, no action needed
- **Number-based Completion**: Reply "1 3" to mark tasks #1 and #3 as done
- **Recurring Blocks**: Auto-creates next 7 days of recurring time blocks (Sleep, Family Time, Speaking Practice)
- **Auto-cleanup**: Monthly cleanup of old completed tasks

## Cost Optimization

This bot is optimized to minimize API costs:

| Feature | Cost |
|---------|------|
| Task Bot AI parsing (Haiku) | ~$0.001 per task |
| Common words (~300) | **FREE** (skipped) |
| Review Bot | **FREE** (no AI) |
| Vocab analysis (Sonnet 4) | ~$0.01-0.02 per word |
| Modifications (Sonnet 3.5) | ~$0.005 per call |
| Entry detection (Sonnet 3.5) | ~$0.002 per call |

**Model selection**: Main analysis uses Sonnet 4 for quality, secondary tasks use Sonnet 3.5 (~2x cheaper), task parsing uses Haiku (very cheap).

**Estimated cost**: ~£0.40-0.70/day with normal usage

## Setup Instructions

### Step 1: Create Telegram Bots

Create 3 bots via `@BotFather` on Telegram:
1. **Vocab Learner Bot** - for learning new vocabulary
2. **Review Bot** - for scheduled reviews
3. **Task Bot** - for daily task management

### Step 2: Get API Keys

1. **Claude API Key**: [console.anthropic.com](https://console.anthropic.com)
2. **Notion Integration**: [notion.so/my-integrations](https://www.notion.so/my-integrations)

### Step 3: Set Up Notion Databases

#### Vocabulary Database
Required properties:
- English (Title)
- Chinese (Text)
- Explanation (Text)
- Example (Text)
- Category (Select): 固定词组, 口语, 新闻, 职场, 学术词汇, 写作, 情绪, 科技, 其他
- Date (Date)
- Review Count (Number) - for spaced repetition
- Next Review (Date) - for spaced repetition
- Last Reviewed (Date) - for tracking

#### Task Tracking Database
Required properties:
- Date (Title) - format: YYYY-MM-DD
- Tasks (Text) - stores completed task IDs as JSON

#### Reminders Database
Required properties:
- Reminder (Title) - task description
- Enabled (Checkbox) - whether task is active
- Date (Date) - supports datetime for time-specific tasks

Optional properties:
- Priority (Select): High, Mid, Low
- Category (Select): Work, Life, Health, Study, Other

#### Recurring Blocks Database (Optional - for Notion Calendar)
Required properties:
- Reminder (Title) - block name (e.g., "Family Time", "Sleep")
- Date (Date) - with time for calendar display
- Enabled (Checkbox)
- Category (Select): Life, Health, Study, Work, Other

### Step 4: Configure Environment

Copy `.env.example` to `.env` and fill in your values:

```bash
# Vocab Learner Bot
TELEGRAM_BOT_TOKEN=your_vocab_bot_token
ANTHROPIC_API_KEY=your_claude_api_key
NOTION_API_KEY=your_notion_integration_token
NOTION_DATABASE_ID=your_vocab_database_id
ALLOWED_USER_IDS=your_telegram_user_id

# Review Bot
REVIEW_BOT_TOKEN=your_review_bot_token
REVIEW_USER_ID=your_telegram_user_id
ADDITIONAL_DATABASE_IDS=  # Optional: old_db_1,old_db_2 for multi-database review
REVIEW_HOURS=8,13,17,19,22  # Optional: review schedule hours
WORDS_PER_BATCH=20          # Optional: words per review batch

# Task Bot
HABITS_BOT_TOKEN=your_task_bot_token
HABITS_USER_ID=your_telegram_user_id
HABITS_REMINDERS_DB_ID=your_reminders_database_id
HABITS_TRACKING_DB_ID=your_tracking_database_id
RECURRING_BLOCKS_DB_ID=your_recurring_blocks_database_id  # Optional

# Timezone
TIMEZONE=Europe/London
```

### Step 5: Install & Run

```bash
# Install dependencies
pip install -r requirements.txt

# Run all bots together
python main.py

# Or run individual bots
python bot.py         # Vocab learner
python review_bot.py  # Scheduled reviews
python habit_bot.py   # Task management
```

## Commands

### Vocab Learner Bot
- `/start` - Welcome message
- `/help` - Show help
- `/test` - Test Notion connection
- `/clear` - Clear pending entries

### Review Bot
- `/start` - Bot info
- `/review` - Get review batch now
- `/due` - See pending reviews count + total words
- `/stop` / `/resume` - Pause/resume scheduled reviews
- `/status` - Bot status

### Task Bot
- `/start` - Bot info
- `/tasks` - Today's consolidated schedule (timeline + actionable tasks)
- `/stop` / `/resume` - Pause/resume reminders
- `/status` - Bot status
- **Mark done**: Reply with numbers like "1 3" to mark tasks done
- **Add tasks**: Send natural language like "4pm to 5pm job application"

## Spaced Repetition Algorithm

The review bot uses a modified SM-2 algorithm:

| Response | Next Review | Count Change |
|----------|-------------|--------------|
| Again (red circle) | Tomorrow | Reset to 0 |
| Good (yellow circle) | 2^count days (1-2-4-8-16-32-60 max) | +1 |
| Easy (green circle) | 2^(count+1) days | +2 |

Priority scoring ensures new words and due words are mixed equally.

## Multi-Database Support

When your vocabulary database gets large (~2000+ words), you can split across multiple databases:

1. Create a new Notion database with the same structure
2. Update environment variables:
   ```bash
   NOTION_DATABASE_ID=new_database_id
   ADDITIONAL_DATABASE_IDS=old_database_id
   ```
3. New words save to the new database
4. Review bot queries ALL databases combined

For multiple old databases, use comma-separated IDs:
```bash
ADDITIONAL_DATABASE_IDS=old_db_1,old_db_2,old_db_3
```

## Notion Calendar Integration

The Task Bot creates recurring time blocks that sync to Notion Calendar:

1. Set up the Recurring Blocks Database (see Step 3)
2. Add `RECURRING_BLOCKS_DB_ID` to your `.env`
3. The bot auto-creates blocks for the next 7 days at 6:00 AM daily
4. View your schedule in Notion Calendar for time blocking

Example recurring blocks:
- Sleep (1:00 AM - 6:00 AM) - Health
- Family Time (5:00 PM - 10:00 PM) - Life
- Speaking Practice (11:00 AM - 12:00 PM, Mon-Fri) - Study

## Deployment

### Railway

1. Connect your GitHub repo to Railway
2. Set environment variables in Railway Dashboard
3. Deploy - Railway auto-deploys on push to main

### Start Command

```bash
python main.py
```

This runs all three bots as separate processes.

## Files

```
ai-vocab-telegram-bot/
├── bot.py              # Vocab learner bot - AI analysis and Notion saving
├── review_bot.py       # Review bot - spaced repetition scheduling
├── habit_bot.py        # Task bot - daily task management and reminders
├── main.py             # Entry point - runs all bots together
├── ai_handler.py       # Claude AI integration for vocab analysis
├── notion_handler.py   # Notion API for vocab database (with retry)
├── habit_handler.py    # Notion API for task/reminder databases
├── task_parser.py      # Regex-based task parser (fallback if no AI)
├── schedule_config.json # Recurring blocks configuration
├── requirements.txt    # Python dependencies
├── .env.example        # Environment template
├── CLAUDE.md           # AI assistant documentation
├── README.md           # This file
└── archive/            # Unused files (youtube_handler.py, video_config.json)
```

## Schedule

### Review Bot
- 8:00, 13:00, 19:00, 22:00 - Vocabulary reviews

### Task Bot
- 6:00 AM - Create recurring blocks (next 7 days)
- 8:00 AM - Morning schedule
- 12:00 PM - Check-in
- 7:00 PM - Check-in
- 10:00 PM - Evening wind-down
- 1st of month - Auto-cleanup old tasks
