# Vocab Learning Telegram Bot

A Telegram bot system that helps you learn English vocabulary with AI-powered explanations, automatic saving to Notion, scheduled reviews, daily task management with Notion Calendar integration, grammar drills, and AI news digests.

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
- **Stats Tracking**: Daily review counts (reviewed/again/good/easy) in dedicated Notion database
- **Weekly Report**: Every Sunday — bar chart with daily counts, totals, active days
- **Monthly Report**: 1st of month — averages, best day, month-over-month comparison
- **Reliable Fetching**: Auto-retry (3x with exponential backoff) for Notion API errors

### Grammar Drill Bot (`grammar_bot.py`)
- **Flashcard Style**: Bold **说明：** label before spoiler-masked answers, bold **例句：** before examples
- **Two Card Types**: Weekly grammar fill-in-blank (7 categories) + daily Top Phrases (Chinese-to-English)
- **8-Week Rotation**: Articles → Tenses → Prepositions → Verb Forms → Word Choice → Sentence Structure → Spelling → Top Phrases
- **Category Override**: Pick any category manually or use auto-rotation
- **Spaced Repetition**: Again (+1d) / Good (+4d) / Easy (+14d) with automatic retirement after 3 consecutive Easy
- **Chinese Translations**: Generated once via Haiku, stored in .md table columns, reused on subsequent practices
- **Example Sentences**: Grammar cards get AI-generated examples; phrase cards show **例句中文：** (visible for translation practice) then **例句：** (spoilered)
- **Reveal on Rate**: Clicking Again/Good/Easy reveals all spoilers and removes buttons
- **No Duplicates**: Pressing Practice multiple times per day gives different cards each time
- **GitHub-backed**: Reads cards from Obsidian markdown files in a private GitHub repo
- **Manual Sync**: [Sync] button or /sync pushes buffered updates to Obsidian immediately
- **Auto Sync**: Daily buffer synced to GitHub .md files at 4:03 AM
- **Interactive Schedule**: Inline button UI for push time, grammar count, phrase count, category override
- **Minimal AI Cost**: Haiku called once per new card (~$0.001/session), then stored permanently

### News Digest Bot (`news_bot.py`)
- **AI Builder Digests**: Daily summaries of top AI researchers, founders, and engineers
- **Feed Sources**: 25 AI builders' tweets, 6 podcasts, 2 blogs (Anthropic + Claude) via [follow-builders](https://github.com/zarazhangrui/follow-builders)
- **AI Summarization**: Haiku generates concise digests (~$0.005/day)
- **Language Options**: Chinese, English, or bilingual — configurable via inline buttons
- **Configurable Push Time**: Default 9:00 AM, adjustable via interactive settings
- **Config Dual-Save**: Notion (primary) + GitHub/Obsidian (backup)
- **Manual Trigger**: /digest or [Digest] button for on-demand digest

### Task Bot (`habit_bot.py`)
- **AI Task Parsing**: Natural language task input with Claude Haiku - just type "4pm to 5pm job application" or "明天下午3点开会"
- **Consolidated Schedule**: One message showing numbered timeline + actionable tasks
- **Date Selector**: View schedule for any day in the next 7 days with buttons
- **Notion Calendar Integration**: Recurring time blocks sync to Notion Calendar for time blocking
- **Block Category**: Time blocks (Sleep, Family Time) show ☀️ in timeline, not actionable
- **All Tasks Scored**: Study, Work, Life, Health, Other categories are all scored (only Block excluded)
- **Number-based Completion**: Reply "1 3" to mark tasks #1 and #3 as done
- **Edit Tasks**: Type "edit 1" to edit task #1, or use Edit button on new tasks
- **Conflict Detection**: Warns when creating task at same time as existing task
- **Configurable Day Boundary**: Default 4am - late night work counts for previous day
- **Configurable Timezone**: Change via /settings command with button selection
- **Daily Scoring**: Evening wind-down shows A/B/C/D grade for all actionable tasks
- **Weekly Summary**: Sunday 8pm summary with daily scores and streak
- **Recurring Blocks**: /blocks command or auto-creates next 7 days at 6am
- **Auto-cleanup**: Monthly cleanup of old completed tasks

## Cost Optimization

This bot is optimized to minimize API costs:

| Feature | Cost |
|---------|------|
| News Digest (Haiku) | ~$0.005 per day |
| Task Bot AI parsing (Haiku) | ~$0.001 per task |
| Common words (~300) | **FREE** (skipped) |
| Review Bot | **FREE** (no AI) |
| Review Stats Tracking | **FREE** (Notion only) |
| Vocab analysis (Sonnet 4) | ~$0.01-0.02 per word |
| Modifications (Sonnet 3.5) | ~$0.005 per call |
| Entry detection (Sonnet 3.5) | ~$0.002 per call |

**Model selection**: Main analysis uses Sonnet 4 for quality, secondary tasks use Sonnet 3.5 (~2x cheaper), task parsing uses Haiku (very cheap).

**Estimated cost**: ~£0.40-0.70/day with normal usage

## Setup Instructions

### Step 1: Create Telegram Bots

Create 5 bots via `@BotFather` on Telegram:
1. **Vocab Learner Bot** - for learning new vocabulary
2. **Review Bot** - for scheduled reviews
3. **Task Bot** - for daily task management
4. **Grammar Drill Bot** - for grammar practice from Obsidian
5. **News Digest Bot** - for daily AI builder digests

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
- Category (Select): Work, Life, Health, Study, Other, Block

**Note:** Block category is for recurring time blocks (Sleep, Family Time) - they show ☀️ in timeline but are NOT actionable or scored.

#### Review Stats Database
Required properties:
- Date (Title) - format: YYYY-MM-DD
- Reviewed (Number) - total reviews for the day
- Again (Number) - again count
- Good (Number) - good count
- Easy (Number) - easy count

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
REVIEW_STATS_DB_ID=your_review_stats_database_id  # Optional: daily review counts

# Grammar Drill Bot
GRAMMAR_BOT_TOKEN=your_grammar_bot_token
GRAMMAR_USER_ID=your_telegram_user_id
OBSIDIAN_GITHUB_TOKEN=your_github_pat  # Fine-grained, Contents R/W on Obsidian repo

# News Digest Bot
NEWS_BOT_TOKEN=your_news_bot_token
NEWS_USER_ID=your_telegram_user_id
# Central Config Database (shared by all bots)
CONFIG_DB_ID=your_config_database_id  # All bot settings stored here

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
python vocab/bot.py         # Vocab learner
python review/review_bot.py # Scheduled reviews
python habit/habit_bot.py   # Task management
python grammar/grammar_bot.py # Grammar drills
python news/news_bot.py     # AI news digests
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
- `/stats` - This week's review stats with bar chart
- `/stop` / `/resume` - Pause/resume scheduled reviews
- `/status` - Bot status

### Grammar Drill Bot
- `/start` - Bot info with current week
- `/status` - Card stats (new, again, good, easy, retired)
- `/sync` - Manually sync buffered updates to Obsidian .md files now
- `/stop` / `/resume` - Pause/resume daily push
- **Practice** - Start a drill session (grammar + phrases, no duplicates per day)
- **Schedule** - Interactive settings (push time, card counts, category override)
- **Sync** - Push buffered updates to Obsidian immediately

### News Digest Bot
- `/start` - Bot info
- `/digest` - Get today's AI builder digest
- `/settings` - Configure push time and language (inline buttons)
- `/stop` / `/resume` - Pause/resume daily pushes
- `/status` - Current settings
- **Digest** (reply keyboard) - Same as /digest
- **Settings** (reply keyboard) - Configure push time and language

### Task Bot
- `/start` - Bot info
- `/tasks` - Today's schedule with date selector (view next 7 days)
- `/blocks` - Create recurring blocks for next 7 days
- `/settings` - Configure day boundary (3-6am) and timezone
- `/stop` / `/resume` - Pause/resume reminders
- `/status` - Bot status
- **Mark done**: Reply with numbers like "1 3" to mark tasks done
- **Edit tasks**: Type "edit 1" to edit task #1
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

This runs all five bots as separate processes.

## Files

```
ai-vocab-telegram-bot/
├── main.py                 # Entry point - runs all bots as subprocesses
├── vocab/                  # Vocab Learner Bot
│   ├── bot.py              # AI analysis and Notion/Obsidian saving
│   ├── ai_handler.py       # Claude AI integration for vocab analysis
│   ├── cache_handler.py    # Common words cache
│   └── obsidian_vocab_handler.py  # Dual-save vocab to Obsidian .md
├── review/                 # Review Bot
│   ├── review_bot.py       # Spaced repetition scheduling
│   ├── review_stats_handler.py    # Review stats tracking (Notion)
│   └── obsidian_review_stats_handler.py  # Dual-save stats to Obsidian .md
├── habit/                  # Task Bot
│   ├── habit_bot.py        # Daily task management and reminders
│   ├── habit_handler.py    # Notion API for task/reminder databases
│   ├── task_parser.py      # Regex-based task parser (fallback)
│   └── task_ai_handler.py  # AI-powered task parsing
├── grammar/                # Grammar Drill Bot
│   ├── grammar_bot.py      # Flashcard practice from Obsidian
│   └── github_handler.py   # GitHub API for Obsidian .md read/write
├── news/                   # News Digest Bot
│   ├── news_bot.py         # Daily AI builder digest + scheduler
│   └── digest_handler.py   # Feed fetching + Haiku summarization
├── shared/                 # Shared modules
│   └── notion_handler.py   # Notion API (used by vocab, review, habit)
├── scripts/                # One-time migration scripts
├── requirements.txt
├── .env.example
└── CLAUDE.md
```

## Schedule

### Review Bot
- 8:00, 13:00, 19:00, 22:00 - Vocabulary reviews
- Sunday (at first review hour) - Weekly review report
- 1st of month, 7:00 AM - Monthly review report

### Grammar Drill Bot
- 9:00 AM (configurable) - Daily grammar + phrase push
- 4:03 AM - Daily auto-sync (buffer → .md files on GitHub)
- Manual sync anytime via [Sync] button or /sync

### News Digest Bot
- 9:00 AM (configurable) - Daily AI builder digest

### Task Bot
- 6:00 AM - Create recurring blocks (next 7 days)
- 8:00 AM - Morning schedule (with date)
- 12:00 PM - Check-in
- 7:00 PM - Check-in
- 10:00 PM - Evening wind-down + daily score (A/B/C/D for Study/Work)
- Sunday 8:00 PM - Weekly summary with daily breakdown and streak
- 1st of month - Auto-cleanup old tasks
