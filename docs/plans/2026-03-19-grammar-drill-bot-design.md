# Grammar Drill Bot — Design Spec

**Date:** 2026-03-19
**Status:** Approved

---

## Overview

A 4th Telegram bot for English grammar drills powered by Obsidian markdown files synced via a private GitHub repo. Two practice modes: fill-in-the-blank (grammar errors, weeks 1-7) and Chinese-to-English (phrase production, week 8). Spaced repetition via status tracking written back to GitHub.

## Architecture

```
main.py (Entry Point)
├── bot.py (Vocab Learner Bot)
├── review_bot.py (Spaced Repetition)
├── habit_bot.py (Task Bot)
└── grammar_bot.py (Grammar Drill Bot) ← NEW
    └── github_handler.py ← NEW (GitHub API read/write)
```

- Standalone subprocess launched from `main.py` (same pattern as existing bots)
- No Notion dependency — all data lives in GitHub
- No AI cost — pure string matching + self-assessment

## Data Source

**Repository:** `NotebookOfCCC/Obsidian` (private)
**Path:** `01. Daily Reflection/05. Grammar Practice/`

### Files (8 categories)

| File | Category | Mode |
|------|----------|------|
| `01. Articles.md` | Articles | Fill-in-blank |
| `02. Tenses.md` | Tenses | Fill-in-blank |
| `03. Prepositions.md` | Prepositions | Fill-in-blank |
| `04. Verb Forms.md` | Verb Forms | Fill-in-blank |
| `05. Word Choice.md` | Word Choice | Fill-in-blank |
| `06. Sentence Structure.md` | Sentence Structure | Fill-in-blank |
| `07. Spelling.md` | Spelling | Fill-in-blank |
| `08. Top Phrases.md` | Top Phrases | Chinese-to-English |

### Markdown Table Format

**Grammar cards (01-07):**
```
| # | Source | Date | Question | Answer | Wrong | Rule | Status | Last Reviewed | Next Review | Easy Streak |
```

**Top Phrases (08):**
```
| # | Source | Date | Chinese Prompt | Keyword Hint | Answer (Target Phrase) | Example Sentence | Status | Last Reviewed | Next Review | Easy Streak |
```

Bot adds `Last Reviewed`, `Next Review`, `Easy Streak` columns on first write-back if not present.

## GitHub Integration (`github_handler.py`)

- **Read:** Pull markdown files via GitHub Contents API on startup + before each drill session
- **Write-back:** After each drill session ends, commit updated statuses back to the repo
- **Auth:** `OBSIDIAN_GITHUB_TOKEN` env var (fine-grained PAT, repo Contents read/write scope)
- **Batched commits:** One commit per session (not per card), message like "grammar-bot: update card statuses"

### API Calls

```
GET /repos/NotebookOfCCC/Obsidian/contents/01. Daily Reflection/05. Grammar Practice/{filename}
PUT /repos/NotebookOfCCC/Obsidian/contents/01. Daily Reflection/05. Grammar Practice/{filename}
```

## Weekly Rotation

- **8-week cycle**, start date: 2026-03-16 (Monday)
- Formula: `week_number = ((today - start_date).days // 7) % 8`
- `week_number` 0-6 = grammar fill-in-blank, 7 = Top Phrases

## Spaced Repetition

### Status Values

| Status | Push Frequency | Next Review Calculation |
|--------|---------------|----------------------|
| `new` | Priority push | Immediate |
| `again` | 1-2 days | tomorrow |
| `good` | 3-5 days | +4 days |
| `easy` | ~14 days | +14 days |
| `retired` | Never | N/A |

### State Transitions

- Answer shown → user rates:
  - **Again** → status = `again`, next_review = tomorrow, easy_streak = 0
  - **Good** → status = `good`, next_review = +4 days, easy_streak = 0
  - **Easy** → status = `easy`, next_review = +14 days, easy_streak += 1
- `easy_streak >= 3` → auto-retire

### Card Selection Priority

1. `new` cards (never practiced)
2. `again` cards (due for review)
3. `good` cards (where next_review <= today)
4. `easy` cards (where next_review <= today)
5. Skip `retired` cards entirely

## Daily Scheduling

- **Default time:** 9:00 AM
- **Default card count:** 5
- **Configurable** via `/settings` command
- **Config persistence:** Stored as `__CONFIG_grammar_settings__` page in the primary vocab Notion DB (reuses existing config pattern), OR as a JSON file committed to the GitHub repo

Since this bot has no Notion dependency, config will be stored as a small JSON in the GitHub repo:
`01. Daily Reflection/05. Grammar Practice/.grammar_bot_config.json`

## Interaction Flow

### Grammar Cards (Weeks 1-7)

```
Bot:  📝 Grammar Drill (Articles) — 1/5

      Fill in the blank:
      "I had ___ flu last week."

User: the

Bot:  ✅ Correct!
      ❌ You originally wrote: (nothing)
      📖 Rule: 特指某次生病用 the

      Rate: [Again] [Good] [Easy]

User: (taps Good)
      → Next card...
```

Wrong answer:
```
Bot:  ❌ Not quite!

      Your answer: a
      ✅ Correct answer: the
      ❌ You originally wrote: (nothing)
      📖 Rule: 特指某次生病用 the

      Rate: [Again] [Good] [Easy]
```

### Top Phrases (Week 8)

```
Bot:  📝 Phrase Drill (高频句式) — 1/5

      用英语表达这个意思：
      "归根结底就是……"

      💡 Keyword: boils

User: What this boils down to is that I need to focus more.

Bot:  Target phrase: What this boils down to is...
      💬 "What this boils down to is that I need to trust the process."

      Rate: [Again] [Good] [Easy]
```

No auto-judging for Top Phrases — user self-assesses.

### Daily Summary

```
Bot:  📊 Today's Results

      ✅ 3/5 correct

      Mistakes to review:
      • "I had ___ flu" → the (特指某次生病)

      This week's focus: Articles (Day 4/7)
```

## Answer Matching (Grammar Cards Only)

- Case insensitive
- Trim whitespace
- Strip surrounding quotes
- Zero article: accept "nothing", "none", "∅", "zero", "-", "" (empty)
- Longer answers: normalize whitespace and compare

## Reply Keyboard

```
[Practice]
```

Single persistent button for on-demand drill sessions.

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message + info |
| `/help` | Usage instructions |
| `/settings` | Change push time + card count |
| `/stop` | Pause daily pushes |
| `/resume` | Resume daily pushes |
| `/status` | Show current week's category + stats |

## Environment Variables

```bash
GRAMMAR_BOT_TOKEN=        # Telegram bot token (from BotFather)
OBSIDIAN_GITHUB_TOKEN=    # GitHub PAT (fine-grained, repo Contents R/W)
GRAMMAR_USER_ID=          # Telegram user ID
```

## New Files

| File | Purpose |
|------|---------|
| `grammar_bot.py` | Main bot logic, handlers, scheduling |
| `github_handler.py` | GitHub API wrapper (read/write markdown files) |

## Changes to Existing Files

| File | Change |
|------|--------|
| `main.py` | Add grammar_bot.py as 4th subprocess |
| `.env.example` | Add 3 new env vars |
| `CLAUDE.md` | Add Grammar Bot section |

## Not in MVP

- Weekly summary
- Write-back to Obsidian Dashboard.md
- AI-powered semantic matching for Top Phrases
- Automatic file sync (already using GitHub)
