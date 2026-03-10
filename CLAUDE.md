# AI Vocabulary Telegram Bot to Notion

A 3-bot Telegram ecosystem for English vocabulary learning with AI-powered analysis, spaced repetition, and habit tracking - all integrated with Notion.

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
├── bot.py (Vocab Learner Bot) + ai_handler.py + notion_handler.py
├── review_bot.py (Spaced Repetition) + notion_handler.py
└── habit_bot.py (Task Bot) + habit_handler.py + task_parser.py
```

## Bots Overview

### 1. Vocab Learner Bot (`bot.py`)
- Analyzes English text using Claude AI (Haiku)
- Extracts worth-learning phrases with phonetics, part of speech, examples
- Multiple meanings shown with numbered examples
- Grammar checking for sentences
- Saves to Notion vocabulary database
- **Cost optimized**: Skips API for ~300 common words
- **AI fallback chain**: Haiku → Sonnet 4.5 → OpenAI GPT-4o-mini (when Anthropic is overloaded or model not found)
- **Persistent reply keyboard**: [Batch] for multi-phrase batch input; [Word Count] shows word counts per configured Notion database

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
- **Weekly summary** - Sunday 7am summary with daily scores and streak
- **Auto-cleanup** - Monthly cleanup of tasks older than 3 months

## Key Files

| File | Purpose | API Cost |
|------|---------|----------|
| `ai_handler.py` | Claude API for vocab analysis | ~$0.002/word |
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
OPENAI_API_KEY=           # Optional: OpenAI key — used as final fallback when Anthropic is overloaded
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
- **📋 Pending** (reply keyboard) - Resends all unrated cards from the last 2 days with chunked audio

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
33. **Config persisted in Notion**: Review schedule and task settings stored as Notion pages (survives Railway redeploys). Config pages use `__CONFIG_` prefix and are filtered from reviews/stats.
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
