# Vocab Learning Telegram Bot

A Telegram bot that helps you learn English vocabulary with AI-powered explanations and automatic saving to Notion.

## Features

- **Grammar Check**: Automatically corrects grammar in sentences
- **Phrase Extraction**: Extracts learnable phrases from sentences
- **AI Explanations**: Provides Chinese explanations, examples, and categorization
- **Notion Integration**: Saves vocabulary entries directly to your Notion database
- **Multi-device**: Works on phone, tablet, and desktop via Telegram

## Setup Instructions

### Step 1: Create Telegram Bot

1. Open Telegram and search for `@BotFather`
2. Send `/newbot`
3. Follow prompts to name your bot
4. Copy the **API Token** (looks like: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### Step 2: Get Claude API Key

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Sign up or log in
3. Go to API Keys section
4. Create new API key and copy it

### Step 3: Set Up Notion Integration

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Click "New integration"
3. Name it (e.g., "Vocab Bot")
4. Copy the **Internal Integration Token**
5. Go to your Notion vocabulary database
6. Click "..." menu → "Add connections" → Select your integration

**Your Notion database should have these properties:**
- English (Title)
- Chinese (Text)
- Explanation (Text)
- Example (Text)
- Category (Select) with options: 固定词组, 口语, 新闻, 职场, 学术词汇, 写作, 情绪, 其他
- Date (Date)

### Step 4: Configure Environment

1. Copy `.env.example` to `.env`
2. Fill in your API keys:

```
TELEGRAM_BOT_TOKEN=your_telegram_token
ANTHROPIC_API_KEY=your_claude_api_key
NOTION_API_KEY=your_notion_integration_token
NOTION_DATABASE_ID=2eb67845254b8042bfe7d0afbb7b233c
ALLOWED_USER_IDS=your_telegram_user_id
```

To get your Telegram user ID, message `@userinfobot` on Telegram.

### Step 5: Install & Run

```bash
# Install Python dependencies
pip install -r requirements.txt

# Run the bot
python bot.py
```

## Usage

1. Open Telegram and find your bot
2. Send `/start` to begin
3. Send any English word, phrase, or sentence
4. Review the AI-generated learning content
5. Reply with a number to save to Notion

### Example

**You send:** "I've been procrastinating on this task"

**Bot responds:**
- Grammar check (if needed)
- Extracted phrases with explanations
- Numbered list of saveable items

**You reply:** "1"

**Bot saves:** Entry to your Notion database

## Commands

- `/start` - Welcome message
- `/help` - Show help
- `/test` - Test Notion connection

## Hosting (Optional)

To keep the bot running 24/7, deploy to:

- **Railway** (free tier available): [railway.app](https://railway.app)
- **Render** (free tier): [render.com](https://render.com)
- **PythonAnywhere** (free tier): [pythonanywhere.com](https://pythonanywhere.com)
- **Your own server**: Any VPS with Python

## Files

```
ai-vocab-telegram-bot/
├── bot.py              # Main bot logic
├── ai_handler.py       # Claude AI integration
├── notion_handler.py   # Notion database integration
├── requirements.txt    # Python dependencies
├── .env.example        # Environment template
├── .env                # Your configuration (create this)
└── README.md           # This file
```
