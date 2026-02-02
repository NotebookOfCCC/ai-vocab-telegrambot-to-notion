# Vocab Learning Telegram Bot

A Telegram bot system that helps you learn English vocabulary with AI-powered explanations, automatic saving to Notion, scheduled reviews, and daily habit tracking.

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
- **Total Count**: Shows total words in database with `/due` command
- **Reliable Fetching**: Auto-retry (3x with exponential backoff) for Notion API errors

### Habit Bot (`habit_bot.py`)
- **Natural Language Tasks**: Just type "明天下午3点开会" - automatically parses time, priority, category (FREE - no API cost!)
- **Daily Reminders**: Morning video + tasks, check-ins throughout the day
- **YouTube Integration**: Random videos from configured channels/playlists
- **Habit Tracking**: Track listening and speaking practice in Notion
- **Custom Tasks**: Add tasks via natural language or `/add` command
- **Weekly Summary**: Progress report every Sunday

## Cost Optimization

This bot is optimized to minimize API costs:

| Feature | Cost |
|---------|------|
| Habit Bot task parsing | **FREE** (regex-based) |
| Common words (~300) | **FREE** (skipped) |
| Review Bot | **FREE** (no AI) |
| Vocab analysis | ~$0.01-0.02 per word |

**Estimated cost**: ~£0.50-0.80/day with normal usage

## Setup Instructions

### Step 1: Create Telegram Bots

Create 3 bots via `@BotFather` on Telegram:
1. **Vocab Learner Bot** - for learning new vocabulary
2. **Review Bot** - for scheduled reviews
3. **Habit Bot** - for daily reminders

### Step 2: Get API Keys

1. **Claude API Key**: [console.anthropic.com](https://console.anthropic.com)
2. **Notion Integration**: [notion.so/my-integrations](https://www.notion.so/my-integrations)
3. **YouTube API Key** (optional): [Google Cloud Console](https://console.cloud.google.com) - Enable "YouTube Data API v3"

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

#### Habit Tracking Database
Required properties:
- Date (Title) - format: YYYY-MM-DD
- Listened (Checkbox)
- Spoke (Checkbox)
- Video (Text) - stores video URL
- Tasks (Text) - stores completed task IDs as JSON

#### Reminders Database
Required properties:
- Reminder (Title) - task description
- Enabled (Checkbox) - whether task is active
- Date (Date) - optional, for time-specific reminders

Optional properties (for natural language parsing):
- Priority (Select): High, Mid, Low
- Category (Select): Work, Life, Health, Study, Other

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

# Habit Bot
HABITS_BOT_TOKEN=your_habit_bot_token
HABITS_USER_ID=your_telegram_user_id
HABITS_REMINDERS_DB_ID=your_reminders_database_id
HABITS_TRACKING_DB_ID=your_tracking_database_id
YOUTUBE_API_KEY=your_youtube_api_key

# Timezone
TIMEZONE=Europe/London
```

### Step 5: Configure YouTube Playlists (Optional)

Edit `video_config.json` to add your preferred channels:

```json
{
  "playlists": [
    {
      "name": "Channel Name",
      "channel_handle": "@YouTubeHandle",
      "enabled": true
    },
    {
      "name": "Playlist Name",
      "playlist_id": "PLxxxxxx",
      "enabled": true
    }
  ]
}
```

### Step 6: Install & Run

```bash
# Install dependencies
pip install -r requirements.txt

# Run all bots together
python main.py

# Or run individual bots
python bot.py         # Vocab learner
python review_bot.py  # Scheduled reviews
python habit_bot.py   # Daily habits
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

### Habit Bot
- `/start` - Bot info
- `/habits` - Today's tasks with Done/Not Yet buttons
- `/add <task>` - Add a new task manually
- `/tmr <task>` - Add task for tomorrow
- `/video` - Get a random practice video
- `/week` - Weekly progress summary
- `/stop` / `/resume` - Pause/resume reminders
- `/status` - Bot status
- **Or just type naturally**: "明天下午3点开会" → auto-parsed!

## Spaced Repetition Algorithm

The review bot uses a modified SM-2 algorithm:

| Response | Next Review | Count Change |
|----------|-------------|--------------|
| Again (🔴) | Tomorrow | Reset to 0 |
| Good (🟡) | 2^count days (1→2→4→8→16→32→60 max) | +1 |
| Easy (🟢) | 2^(count+1) days | +2 |

Priority scoring ensures new words and due words are mixed equally.

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
├── habit_bot.py        # Habit bot - daily reminders and tracking
├── main.py             # Entry point - runs all bots together
├── ai_handler.py       # Claude AI integration for vocab analysis
├── notion_handler.py   # Notion API for vocab database (with retry)
├── habit_handler.py    # Notion API for habit/reminder databases
├── youtube_handler.py  # YouTube API for fetching videos
├── task_parser.py      # FREE regex-based task parser (no API)
├── video_config.json   # YouTube channels/playlists configuration
├── requirements.txt    # Python dependencies
├── .env.example        # Environment template
├── CLAUDE.md           # AI assistant documentation
└── README.md           # This file
```

## Schedule

### Review Bot
- 8:00, 13:00, 19:00, 22:00 - Vocabulary reviews

### Habit Bot
- 8:00 - Morning video + reminders
- 12:00, 19:00, 22:00 - Practice check-ins
- Sunday 20:00 - Weekly summary
