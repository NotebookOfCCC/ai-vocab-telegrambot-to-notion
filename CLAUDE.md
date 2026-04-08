# AI Vocabulary Telegram Bot to Notion

A 5-bot Telegram ecosystem for English vocabulary learning with AI-powered analysis, spaced repetition, habit tracking, grammar drills, and AI news digests - integrated with Notion and Obsidian via GitHub.

---

## Standing Instructions for Claude (ALWAYS follow these)

1. **After every code change**, commit and push to GitHub immediately — do not wait to be asked.
2. **After every new requirement** (UI change, behaviour change, rule, preference), update this CLAUDE.md file to record the spec, then commit and push.
3. Keep specs under the relevant section (e.g. keyboard layout under "Vocab Bot Keyboard Layout Spec", prompt rules under "Vocab Bot Prompt Specifications").
4. The Recent Changes list at the bottom should also be updated with a one-liner for each change.

---

## Architecture

```
main.py (Entry Point)
├── vocab/          bot.py + ai_handler.py + cache_handler.py + obsidian_vocab_handler.py
├── review/         review_bot.py + review_stats_handler.py + obsidian_review_stats_handler.py
├── habit/          habit_bot.py + habit_handler.py + task_parser.py + task_ai_handler.py
├── grammar/        grammar_bot.py + github_handler.py
├── news/           news_bot.py + digest_handler.py
├── shared/         notion_handler.py (used by vocab, review, habit, news)
└── scripts/        migrate_to_obsidian.py, migrate_review_stats_to_obsidian.py
```

## Bots Overview

### 1. Vocab Learner Bot (`vocab/bot.py`)
- Analyzes English text using Claude AI (Haiku)
- Extracts worth-learning phrases with phonetics, part of speech, examples
- Multiple meanings shown with numbered examples
- Grammar checking for sentences
- Saves to Notion vocabulary database + Obsidian markdown (dual-save via GitHub API)
- **Cost optimized**: Skips API for ~300 common words
- **AI fallback chain**: Haiku → Sonnet 4.5 → OpenAI GPT-4o-mini (when Anthropic is overloaded or model not found)
- **Persistent reply keyboard**: [Batch] for multi-phrase batch input; [Word Count] shows word counts per configured Notion database

### 2. Review Bot (`review/review_bot.py`)
- Spaced repetition system (SM-2 variant)
- Schedule: 8:00, 13:00, 19:00, 22:00
- Buttons: Again (1 day) / Good (2^n days) / Easy (skip ahead)
- New words and due words have equal priority
- **Multi-database support**: Can query from multiple Notion databases
- **Stats tracking**: Daily review counts (reviewed/again/good/easy) in dedicated Notion database
- **Weekly report**: Every Sunday — bar chart + totals + active days
- **Monthly report**: 1st of month — totals, averages, best day, month-over-month comparison
- **No API cost** (just Notion queries)

### 3. Task Bot (`habit/habit_bot.py`)
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
- **Weekly summary** - Sunday 7am summary with daily scores and streak
- **Auto-cleanup** - Monthly cleanup of tasks older than 3 months

### 4. Grammar Drill Bot (`grammar/grammar_bot.py`)
- Reads grammar practice cards from Obsidian markdown files via GitHub API
- **Private repo**: `NotebookOfCCC/Obsidian` → `01. Daily Reflection/05. Grammar Practice/`
- **8-week rotation**: 7 grammar categories (Chinese-to-English translation) + 1 phrase category (Chinese-to-English)
- **Spaced repetition**: new → again ⇄ good → easy → retired (3 consecutive easy = auto-retire)
- **Spacing**: Again = +1 day, Good = +4 days, Easy = +14 days, 3× Easy in a row = retired
- **Daily push**: Configurable time (default 9:00 AM), grammar count (default 5), phrase count (default 3)
- **Top Phrases daily**: Phrase cards are practiced every day (not just week 8)
- **Two practice modes**: Chinese-to-English translation (weeks 1-7, with keyword hint) and Chinese-to-English self-assessment (always)
- **Flashcard format**: Bold **说明：** label before spoiler-masked answers + rules; bold **例句：** before examples
- **Chinese translations**: Generated once via Haiku, stored in `Chinese` column in .md tables, reused on subsequent practices
- **Example sentences**: Grammar cards get examples generated via Haiku (one-time), stored in `Example` + `Example Chinese` columns
- **Phrase example flow**: Shows **例句中文：** (visible) for user to practice translating, then **例句：** (spoilered) to reveal English
- **Reveal on rate**: Clicking Again/Good/Easy reveals all spoilers and removes buttons (like review_bot)
- **No duplicate cards**: Pressing Practice multiple times per day gives different cards; shows "No more cards available today!" when exhausted
- **Interactive Schedule**: Inline button UI for push time, grammar count, phrase count, category override
- **Category override**: [Edit Category] button — pick any of 8 categories or Auto (weekly rotation), persists in config
- **Status write-back**: Daily buffer in memory, auto-synced to .md files on GitHub at 4:03 AM
- **Manual Sync**: [Sync] button or /sync — pushes all buffered updates + new column headers to Obsidian immediately
- **Reply keyboard**: [Practice] [Schedule] [Sync]
- **Minimal AI cost** — Haiku called once per new card for Chinese/examples (~$0.001/session), then stored permanently
- **No Notion dependency** — all data lives in GitHub/Obsidian
- **Markdown table columns (grammar)**: `# | Source | Date | Question | Answer | Wrong | Rule | Chinese | Example | Example Chinese | Status | Last Reviewed | Next Review | Easy Streak`
- **Markdown table columns (phrases)**: `# | Source | Date | Chinese Prompt | Keyword Hint | Answer (Target Phrase) | Example Sentence | Example Chinese | Status | Last Reviewed | Next Review | Easy Streak`

### 5. News Digest Bot (`news/news_bot.py`)
- Fetches daily AI builder digests from [follow-builders](https://github.com/zarazhangrui/follow-builders) GitHub feeds
- **Feed sources** (GitHub CDN, free): 25 AI builders' tweets, 6 podcasts, 2 blogs (Anthropic + Claude)
- Summarizes via Haiku (~$0.005/day)
- **Configurable language**: Chinese / English / bilingual
- **Configurable push time**: Default 9:00 AM, adjustable via inline buttons
- **Config dual-saved**: Notion (primary, read) + GitHub/Obsidian (backup)
- **Reply keyboard**: [Digest] [Settings]
- **Commands**: `/start`, `/help`, `/digest`, `/stop`, `/resume`, `/status`, `/settings`
- **Settings UI**: Inline buttons — [Edit Time] (hour grid + minute picker), [Edit Language] (中文/English/双语)

## Key Files

| File | Purpose | API Cost |
|------|---------|----------|
| `vocab/ai_handler.py` | Claude API for vocab analysis | ~$0.002/word |
| `vocab/cache_handler.py` | Cache for common words | FREE |
| `vocab/obsidian_vocab_handler.py` | Dual-save vocab to Obsidian .md via GitHub | FREE |
| `review/review_stats_handler.py` | Review stats tracking (Notion) | FREE |
| `review/obsidian_review_stats_handler.py` | Dual-save review stats to Obsidian .md via GitHub | FREE |
| `habit/habit_handler.py` | Task tracking, task management | FREE |
| `habit/task_parser.py` | Regex task parsing (fallback) | **FREE** |
| `grammar/github_handler.py` | GitHub API read/write for Obsidian files | FREE |
| `news/digest_handler.py` | Fetch follow-builders feeds + Haiku summarization | ~$0.005/day |
| `news/news_bot.py` | News digest Telegram bot + scheduler | FREE |
| `shared/notion_handler.py` | Notion database operations (with retry) | FREE |

## Cost Optimization

### Vocab Bot (ai_handler.py)
- **Common words list** (~300 words): Returns "basic vocabulary" response, no API call
- **Dynamic max_tokens**:
  - Short phrases (1-3 words): 800 tokens
  - Sentences: 1000 tokens
- **Model**: Claude Haiku (`claude-haiku-4-5-20251001`) for all tasks — analysis, modifications, entry detection
- **Overload fallback chain** (automatic, no user action needed):
  1. Claude Haiku (3 retries: 5s → 10s → 20s backoff)
  2. Claude Sonnet 4.5 (`claude-sonnet-4-5`) — different capacity pool
  3. OpenAI GPT-4o-mini — completely separate infrastructure
  - Triggers on: 429 (rate limit), 529 (overloaded), 404 (model not found/deprecated), 400 usage limit
  - Applies to ALL AI calls: main analysis, modifications, entry detection
  - Requires `OPENAI_API_KEY` env var for step 3 (optional but recommended)

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
- Category (Select) - 固定词组, 口语, 新闻, 职场, 学术词汇, 写作, 情绪, 科技, 精美句子, 其他
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

### Review Stats Database
```
- Date (Title) - YYYY-MM-DD
- Reviewed (Number) - total reviews for the day
- Again (Number) - again count
- Good (Number) - good count
- Easy (Number) - easy count
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
GRAMMAR_BOT_TOKEN=        # Grammar drill bot token
NEWS_BOT_TOKEN=           # News digest bot token

# API Keys
ANTHROPIC_API_KEY=        # Claude API key (for vocab analysis + task parsing)
OPENAI_API_KEY=           # Optional: OpenAI key — used as final fallback when Anthropic is overloaded
NOTION_API_KEY=           # Notion integration token
OBSIDIAN_GITHUB_TOKEN=    # GitHub PAT for Obsidian repo (grammar drill data)

# Notion Databases
NOTION_DATABASE_ID=       # Primary vocabulary database ID (for saving)
ADDITIONAL_DATABASE_IDS=  # Optional: comma-separated additional DB IDs for review
HABITS_TRACKING_DB_ID=    # Habit tracking database ID
HABITS_REMINDERS_DB_ID=   # Reminders database ID
RECURRING_BLOCKS_DB_ID=   # Optional: Recurring time blocks database ID
REVIEW_STATS_DB_ID=       # Review stats tracking database ID (daily counts)
CONFIG_DB_ID=             # Central config database (all bots share this for settings)

# User IDs
ALLOWED_USER_IDS=         # Comma-separated user IDs for vocab bot
REVIEW_USER_ID=           # Review bot user ID
HABITS_USER_ID=           # Habits bot user ID
GRAMMAR_USER_ID=          # Grammar drill bot user ID
NEWS_USER_ID=             # News digest bot user ID

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
- `/stats` - This week's review stats with bar chart
- **📋 Pending** (reply keyboard) - Resends all unrated cards from the last 2 days with chunked audio

### Task Bot
- `/tasks` - Today's schedule with date selector (view next 7 days)
- `/blocks` - Manually create recurring blocks for next 7 days
- `/settings` - Configure day boundary (default 4am) and timezone
- `/stop`, `/resume`, `/status` - Pause/resume reminders
- **Mark done**: Reply "1 3" to mark tasks #1 and #3 as done
- **Edit task**: Type "edit 1" to edit task #1 (date, time, text, category, delete)
- **Add task**: Send natural language like "4pm to 5pm job application" (AI parses it, shows Edit button)

### Grammar Drill Bot
- `/start`, `/help` - Welcome message with current week info
- `/status` - Current week category + card stats (new/again/good/easy/retired)
- `/settings` - Text-based settings (fallback; same as Schedule button)
- `/sync` - Manually sync all buffered updates to Obsidian .md files now
- `/stop`, `/resume` - Pause/resume daily pushes
- **Practice** (reply keyboard) - Start an on-demand drill session (grammar + phrases, no duplicates within same day)
- **Schedule** (reply keyboard) - Interactive settings with inline buttons:
  - [Edit Category] → pick any of the 8 categories or Auto (weekly rotation)
  - [Edit Time] → hour grid (7-23), then minute picker (00/15/30/45)
  - [Edit Grammar Count] → preset options (3, 5, 8, 10, 15)
  - [Edit Phrase Count] → preset options (3, 5, 8, 10, 15)
- **Sync** (reply keyboard) - Push buffered updates + new column headers to Obsidian immediately

### News Digest Bot
- `/start`, `/help` - Welcome message
- `/digest` - Get today's AI builder digest now
- `/settings` - Configure push time and language (inline buttons)
- `/stop`, `/resume` - Pause/resume daily pushes
- `/status` - Show current settings
- **Digest** (reply keyboard) - Same as /digest
- **Settings** (reply keyboard) - Interactive settings with inline buttons:
  - [Edit Time] → hour grid (7-23), then minute picker (00/15/30/45)
  - [Edit Language] → [中文] [English] [双语]

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
python vocab/bot.py         # Test vocab bot alone
python review/review_bot.py # Test review bot alone
python habit/habit_bot.py   # Test habit bot alone
python main.py              # Run all bots together
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

## Vocab Bot Prompt Specifications (DO NOT CHANGE)

These are the core behaviours of the vocab bot's AI prompt in `ai_handler.py → SYSTEM_PROMPT`. They were deliberately designed and must be preserved through any future edits or model changes.

### 1. All meanings — context-independent analysis (MOST IMPORTANT)
When a phrase is extracted from a sentence, the entry must cover **all** dictionary meanings of that phrase, not just the one relevant to the input sentence. The sentence only tells the model *which phrase to extract*, not *which meanings to include*.

- ✗ Wrong: "blocking out an hour" → `block out` only explains "预留时间"
- ✓ Correct: "blocking out an hour" → `block out` explains all 4 meanings (遮挡光线/声音, 忽视感受/记忆, 划掉文本, 预留时间)

This rule lives in the prompt as **Rule 6** and must stay there. Do not weaken, move, or remove it.

### 2. Multiple meanings format
When a word/phrase has multiple meanings, explanation and examples must both be numbered and matched 1-to-1.
- `explanation`: "1. 含义一 2. 含义二 3. 含义三"
- `example_en`: "1. Example one. 2. Example two. 3. Example three."
- `example_zh`: "1. 翻译一 2. 翻译二 3. 翻译三"

### 3. Base/dictionary form
Words are always saved in their base form: "blocking out" → "block out", "running" → "run", "fidelities" → "fidelity". Exception: 精美句子 entries keep the full original sentence.

**Irregular past tense phrasal verbs — convert conjugated forms to base form:**

| Seen in sentence | Save as (base form) |
|---|---|
| tore apart / tore into | tear apart / tear into |
| drove away / drove up | drive away / drive up |
| wore out / wore down | wear out / wear down |
| swore by / swore off | swear by / swear off |
| strove for / strove to | strive for / strive to |
| wove through | weave through |
| shone through | shine through |
| spoke up / spoke out | speak up / speak out |

**"bore down" is a valid base-form phrasal verb** (meaning: to drill/penetrate through something). Do NOT convert it to "bear down" — they are different phrases.

**Additionally**, when the base form has an irregular past tense, the explanation must include the conjugation with phonetics at the end:
- Format: `（不规则变化：过去式 tore /tɔːr/，过去分词 torn /tɔːrn/）`
- Do NOT put this note in the chinese field — explanation field only.
- This applies to any irregular verb: tear/tore/torn, wear/wore/worn, drive/drove/driven, etc.

This is in **Rule 0** of the system prompt. If editing the prompt, these examples must stay.

### 4. Selectivity
For sentence input, only extract truly worth-learning items (phrasal verbs, idioms, non-obvious collocations, advanced vocabulary). Do not extract basic words like "important", "people", "make".

### 5. Phonetics — British English (RP), every entry
Add IPA phonetics for **every** entry without exception using **British English (Received Pronunciation)** — NOT American English.
- British: `/ɡəʊ/` not `/ɡoʊ/`, `/bɑːθ/` not `/bæθ/`, `/ˈwɔːtə/` not `/ˈwɔːtər/`
- Single word: `run /rʌn/ (v./n.)`
- Phrasal verb: `give up /ɡɪv ʌp/ (phr. v.)`
- Do NOT skip phonetics for "easy" or common words.

### 5b. Phrase verification (spell-check)
Before saving the `english` field, verify it is a real standard English phrase. If it looks like a typo of a known phrase, silently correct it and note the correction in `grammar_note`.
- `"trail balloon"` → `"trial balloon"`
- `"blessing in the disguise"` → `"blessing in disguise"`
- `"take for granite"` → `"take for granted"`

### 6. Part of speech
List ALL parts of speech a word can be used as, e.g. "time (n./v.)".

### 7. 精美句子 category
For inspirational/poetic sentences: save the entire sentence as one entry with Chinese translation and literary analysis. Normal everyday sentences are NOT 精美句子.

---

## Vocab Bot Keyboard Layout Spec (DO NOT CHANGE without updating this section)

### Single-entry keyboard (1 result)
One row, left to right:
```
[Save]  [Cancel]  [More]  [🔊]
```
- **Save** — saves the entry to Notion (shows "Replace" if duplicate)
- **Cancel** — clears the session
- **More** — opens Others submenu (see below)
- **🔊** — plays TTS pronunciation

### Multi-entry keyboard (2+ results)
Two rows:
```
Row 1: [Save 1]  [Save 2]  [Save 3]  [Save All]
Row 2: [Cancel]  [More]  [🔊1]  [🔊2]  [🔊3]
```
- Row 1: individual **Save N** buttons + **Save All**
- Row 2: **Cancel**, **More** Others menu, then **🔊N** pronunciation buttons (one per entry)

### Edit-mode keyboard (after modifying an entry)
Single entry:
```
[Save]  [Cancel]  [More]  [🔊]
```
Multi-entry:
```
Row 1: [Save [N]]  [Save All]  [🔊]
Row 2: [Cancel]  [More]
```
- More must always be present so the user can access Others during edit/modify flow

### Others submenu (shown when More is tapped)
```
[Select Model]  [Add to Explanation]  [← Back]
```
- **Select Model** → opens model picker
- **Add to Explanation** → append text to an entry's explanation field
- **← Back** → restores the main keyboard

### Model selector (shown when Select Model is tapped)
```
[🤖 Haiku ✓]  [🧠 Sonnet]  [💡 GPT-4o]
[← Back]
```
- Checkmark (✓) shows currently active model
- Selected model persists for all follow-up modifications in the same session
- Session resets to Haiku when entries are saved or a new input is typed
- ← Back returns to Others submenu

### Add to Explanation flow
**Single entry:**
1. Tap More → Others submenu
2. Tap "Add to Explanation" → bot prompts "Reply with the text to append..."
3. User pastes text → appended to explanation with `\n\n——\n` separator

**Multi-entry:**
1. Tap More → Others submenu
2. Tap "Add to Explanation" → entry picker: `[1: bubble over]  [2: bubble up]  [← Back]`
3. Tap entry → bot prompts for text
4. User pastes → appended to that entry's explanation

**Appended format:**
```
原始解释内容...

——
用户追加的内容
```

---

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
12. **Haiku for all tasks**: All vocab analysis, modifications, and detection use claude-haiku-4-5-20251001
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
32. **Vocab review stats in habit bot**: Shows words reviewed count in all habit bot messages (morning: yesterday's count, check-ins/tasks: today's count, weekly summary: week total)
33. **Config persisted in Notion**: All bot configs stored in central `CONFIG_DB_ID` database (survives Railway redeploys). Config pages use `__CONFIG_` prefix. Review bot: `__CONFIG_review_schedule__`, Habit bot: `__CONFIG_task_settings__`, News bot: `__CONFIG_news_settings__`. Grammar bot uses GitHub config independently.
34. **Mobile popup instructions**: /schedule Edit Times/Edit Word Count buttons show popup alert on all platforms (mobile + desktop)
35. **精美句子 category**: New category for beautiful/inspirational sentences — saves the whole sentence as one entry with Chinese translation and literary analysis
36. **OpenAI fallback**: When Anthropic is overloaded (529), vocab bot automatically falls back: Haiku → Sonnet 3.5 → OpenAI GPT-4o-mini. Requires OPENAI_API_KEY env var.
37. **Non-blocking AI calls**: AI calls run in thread executor so bot stays responsive during retries
38. **Model selector button**: 🔄 button lets user re-analyze with Haiku / Sonnet / GPT-4o; chosen model persists for follow-up edits in the session
39. **Keyboard layout standardised**: Single-entry [Save][Cancel][🔄][🔊]; multi-entry all on one row [Save1..N][Save All][Cancel][🔄][🔊1..N]
40. **Phrase spell-check**: AI verifies extracted phrase is a real English phrase; corrects typos (e.g., "trail balloon" → "trial balloon") and notes in grammar_note
41. **British English IPA**: All phonetics now use Received Pronunciation (RP), not American English
43. **Habit bot bottom buttons**: [📋 Tasks] [📚 Words] — Words shows today's vocab review count via get_review_stats_line()
42. **Others (More) submenu**: Replaced 🔄 with More button; opens submenu with [Select Model] and [Add to Explanation]. Add to Explanation appends user-pasted text to a specific entry's explanation field with a —— separator
44. **Parallel Notion dup checks**: All per-entry duplicate queries now run concurrently (asyncio.gather) instead of sequentially — saves ~300-1000ms per analysis
45. **Skip pre-check for sentences**: Notion pre-check on raw input is skipped for inputs >3 words (sentences never match stored base-form phrases) — "Analyzing..." now appears immediately for sentence inputs
46. **Non-blocking pre-check**: Short phrase/word pre-check wrapped in run_in_executor so it no longer blocks the asyncio event loop
47. **Review batch audio**: After each review batch, sends one combined MP3 with all phrases pronounced by en-GB-SoniaNeural (edge-tts). Filename is date+time only (e.g. 2026-03-05_14-30.mp3). Vocab bot TTS (gTTS) is unchanged.
48. **Batch mode**: [Batch] reply keyboard button enters collection mode — send phrases one by one, tap Analyze to process all in parallel, each card gets [Save]/[Skip] buttons. [Word Count] button shows word counts per Notion database.
49. **Pending review resend**: 📋 Pending button on review bot resends all unrated cards from the last 2 days (accumulates across batches via `sent_but_unrated`, expires after 2 days, removed when rated). Audio in 10-phrase chunks. Regular batch audio also chunked into 10-phrase MP3s.
50. **Pending interleaved audio**: Pending resend sends 10 cards then their audio immediately, then next 10 cards then their audio, etc. (not all cards first, audio at the end). Audio filenames use `_part1`, `_part2`, etc. suffix (e.g. `2026-03-11_14-30_part1.mp3`) so each chunk is distinguishable.
51. **Grammar Drill Bot**: 4th bot for English grammar drills from Obsidian markdown files via GitHub API. 8-week rotation (7 grammar Chinese-to-English + 1 phrase Chinese-to-English). Spaced repetition with status write-back to GitHub. No AI cost, no Notion dependency.
52. **Grammar interactive schedule**: Schedule button now uses inline buttons (like review_bot) — hour grid for push time, preset options for grammar count and phrase count. No more text commands needed.
53. **Grammar example sentences**: All card types show "**例句：**" with example sentence + Chinese translation. Grammar cards get examples generated via Haiku one-time; phrase cards get existing examples translated. Stored in new Example/Example Chinese columns in .md files (generated once, persisted via buffer → daily sync).
54. **Grammar Chinese column**: Chinese translations stored in .md table (new `Chinese` column between Rule and Status). Generated once via Haiku, then read from file on subsequent practices. Phrase cards already have chinese_prompt.
55. **Grammar reveal on rate**: Clicking Again/Good/Easy reveals the spoilered answer+rule and removes buttons (like review_bot), instead of keeping dead buttons.
56. **Grammar phrase examples**: Phrase cards show "**例句中文：**" (visible, not spoilered) so user can practice translating Chinese→English, then "**例句：**" (spoilered) to reveal English. Grammar card examples stay fully spoilered.
57. **Grammar category override**: Schedule has [Edit Category] button — pick any of the 8 categories or Auto (weekly rotation). Override saved in config, persists across restarts.
58. **Grammar no duplicate cards**: Pressing Practice multiple times per day gives different cards each time. Sent card nums tracked in memory per filename, reset daily. Shows "No more cards available today!" when all eligible cards exhausted.
59. **Grammar Sync button**: Reply keyboard [Practice] [Schedule] [Sync]. Sync (or /sync) manually pushes all buffered updates + new column headers to Obsidian .md files immediately, without waiting for the 4:03 AM auto-sync.
60. **Grammar card labels**: Spoilered answers prefixed with bold "**说明：**", examples prefixed with bold "**例句：**" / "**例句中文：**" for visual clarity.
61. **Grammar daily sync at 4:03 AM**: Moved from 3:03 AM to 4:03 AM to avoid conflict with late-night usage.
62. **Grammar cards Chinese-to-English**: Grammar cards now show Chinese translation visible + answer as 💡 keyword hint, with full English sentence spoilered (instead of fill-in-blank). Same format as phrase cards — user practices constructing the full sentence from Chinese context.
63. **Review stats tracking**: Daily review counts (reviewed/again/good/easy) tracked in dedicated Notion database. /stats command shows weekly bar chart. Automated weekly report (Sunday) and monthly report (1st of month) with trends and comparisons.
64. **Obsidian dual-save**: Vocab entries saved to both Notion and Obsidian markdown table (via GitHub API). Files at `98. 数据库/01. Vocabulary Telegram/Vocabulary_NNN.md`. Files 001-004 are historical imports (one per Notion database), new entries go to 005+ with auto-split at 1000 entries. Uses same `OBSIDIAN_GITHUB_TOKEN`. Obsidian save is best-effort (failures logged, don't block Notion save). Confirmation messages show "Saved to Notion + Obsidian".
65. **Notion→Obsidian migration**: One-time migration script `migrate_to_obsidian.py` exports all 4 Notion vocab databases to Vocabulary_001-004.md (3,932 entries total). Also added databases 3 & 4 to `ADDITIONAL_DATABASE_IDS` for review bot coverage.
66. **Review stats dual-save**: Review stats (daily reviewed/again/good/easy counts) now saved to both Notion and Obsidian markdown. File at `98. 数据库/01. Vocabulary Telegram/Review_Stats.md`. Migration script `scripts/migrate_review_stats_to_obsidian.py` syncs existing Notion data. Obsidian save is best-effort (failures logged, don't block Notion save).
67. **Project restructure**: Organized Python files into package folders — `vocab/`, `review/`, `habit/`, `grammar/`, `shared/`, `scripts/`. Each bot is a subprocess launched from `main.py`. No performance impact.
68. **News Digest Bot**: 5th bot for daily AI builder digests from [follow-builders](https://github.com/zarazhangrui/follow-builders) feeds (tweets, podcasts, blogs). Summarized via Haiku (~$0.005/day), configurable language (zh/en/bilingual) and push time. Config dual-saved to Notion + GitHub. Reply keyboard [Digest] [Settings].
69. **Review bot stop/resume fix**: `is_paused` state now persisted to Notion config — previously lost on restart, causing reviews to continue after `/stop`.
70. **Central config database**: New `CONFIG_DB_ID` env var — all bot configs (review schedule, task settings, news settings) stored in one Notion database. Survives Railway restarts. Falls back to legacy per-bot storage if not set.
71. **Obsidian duplicate replace**: When replacing a duplicate word in Notion, Obsidian now also replaces the existing row in-place (searches all files 001+) instead of appending a duplicate. Falls back to append if not found.
72. **Rule 6 strengthened**: Added explicit "reference" example to AI prompt Rule 6 — single words with multiple parts of speech must include ALL meanings across ALL POS, not just the one used in the input sentence.
