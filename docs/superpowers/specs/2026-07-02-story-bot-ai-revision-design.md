# Story Bot AI Revision Design

## Overview

Enhance Story Bot to provide AI-powered English revision and grammar suggestions. When users send text, the bot saves the original, then uses AI to revise it and provide detailed grammar/translation notes. This enables continuous English writing practice throughout the day.

## User Flow

1. User sends any text (English, Chinese, or mixed)
2. Bot immediately replies: `Saved (HH:MM)` + [Delete] button (no waiting for AI)
3. Bot calls Sonnet in background to revise + analyze
4. Bot sends second message with revision and notes:
   ```
   Revised:
   I went to the store yesterday.

   Notes:
   "goed"不是正确的过去式。go 的过去式是不规则变化 went，不能加 -ed。
   ```
5. Bot updates the GitHub/Obsidian file with Revised and Notes columns

## Table Format

Expanded from 2 columns to 4:

```
| Time | Story | Revised | Notes |
|------|-------|---------|-------|
| 14:30 | I goed to store yesterday | I went to the store yesterday | "goed"不是正确的过去式... |
```

- **Story**: Original text (unchanged)
- **Revised**: AI-polished version
- **Notes**: Detailed Chinese grammar explanation
- If AI fails: Revised and Notes columns left empty

## AI Behavior

### Language Handling
- **English input**: Revise for naturalness/grammar + Chinese grammar explanation
- **Chinese input**: Translate to idiomatic English + Chinese explanation of translation choices
- **Mixed input**: Convert to polished English + Chinese explanation
- **Already correct English**: Suggest improvements (more advanced vocabulary, more idiomatic expressions) + explain why the alternatives are better

### Model & Fallback Chain
1. **Sonnet** (`claude-sonnet-4-5`) — primary, 3 retries with 5s/10s/20s backoff
2. **Haiku** (`claude-haiku-4-5-20251001`) — fallback
3. **OpenAI GPT-4o-mini** — final fallback (requires `OPENAI_API_KEY`)

Triggers: 429 (rate limit), 529 (overloaded), 404 (model not found), 400 (usage limit)

If all fail: original text already saved, Revised/Notes left empty, second message says "AI revision unavailable".

### Prompt Design
- System prompt instructs the model to return JSON: `{"revised": "...", "notes": "..."}`
- Notes must be in Chinese with detailed explanations
- Even if no errors, provide improvement suggestions

### Cost
- ~$0.005/message
- ~$0.10/day at 20 messages

## Code Changes

### New File: `story/ai_handler.py`
- `SYSTEM_PROMPT` — instructions for revision/translation
- `revise_text(text: str) -> dict` — calls Sonnet with fallback chain, returns `{"revised": "...", "notes": "..."}`
- Fallback chain logic (Anthropic Sonnet → Haiku → OpenAI)
- JSON parsing with error handling

### Modified File: `story/story_bot.py`
- `TABLE_HEADER` updated to 4 columns: `| Time | Story | Revised | Notes |`
- `_append_entry()` — accepts optional `revised` and `notes` params, writes 4-column rows
- `_update_entry_revision()` — new function to update Revised/Notes columns for an existing row (by date + timestamp)
- `handle_text()` — after saving, calls AI in background (asyncio.create_task), sends second message with results, updates GitHub file
- `_get_today_entries()` — updated to show Revised and Notes in Today view:
  ```
  14:30  I goed to store yesterday
    Revised: I went to the store yesterday.
    Notes: "goed"不是正确的过去式...
  ```

### No Changes
- `main.py` — no changes needed
- Other bots — no impact

## Environment Variables

No new env vars required. Uses existing:
- `ANTHROPIC_API_KEY` — for Sonnet/Haiku
- `OPENAI_API_KEY` — optional, for GPT-4o-mini fallback

## Backward Compatibility

- Existing 2-column entries in the .md file will still render fine in Obsidian
- New 4-column rows will be added alongside old 2-column rows
- `_get_today_entries()` handles both formats gracefully
