# Story Bot AI Revision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add AI-powered English revision and grammar suggestions to Story Bot, saving revised text and notes alongside originals in Obsidian.

**Architecture:** New `story/ai_handler.py` handles AI calls (Sonnet with Haiku/GPT-4o-mini fallback). `story/story_bot.py` is modified to use 4-column tables and call AI asynchronously after saving.

**Tech Stack:** anthropic SDK, openai SDK (optional fallback), aiohttp, python-telegram-bot

---

### Task 1: Create `story/ai_handler.py`

**Files:**
- Create: `story/ai_handler.py`
- Reference: `vocab/ai_handler.py` (for fallback chain pattern)

- [ ] **Step 1: Create the AI handler file**

```python
"""
Story Bot AI Handler - Revises English text and provides grammar suggestions.

Uses Claude Sonnet as primary model with Haiku and GPT-4o-mini fallback.
Cost: ~$0.005 per revision.
"""
import anthropic
import json
import re
import time
import logging

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an English writing coach for a Chinese learner practicing daily storytelling.

Your job:
1. If the input is English: revise it for naturalness, grammar, and fluency. Provide detailed Chinese grammar explanations.
2. If the input is Chinese: translate it into natural, idiomatic English. Explain translation choices in Chinese.
3. If the input is mixed: convert everything to polished English. Explain in Chinese.
4. Even if the input has no errors, suggest improvements — more advanced vocabulary, more idiomatic phrasing, better sentence structure. Explain why the alternatives are better.

IMPORTANT:
- "revised" should be the improved/translated English text
- "notes" should be detailed Chinese explanations (grammar errors, word choices, translation reasoning, improvement suggestions)
- Keep the original meaning intact
- Be encouraging but thorough

Respond with ONLY valid JSON, no markdown:
{"revised": "the improved English text", "notes": "详细的中文语法解释和建议"}"""


class StoryAIHandler:
    def __init__(self, anthropic_api_key: str, openai_api_key: str = None):
        self.client = anthropic.Anthropic(api_key=anthropic_api_key)
        self.primary_model = "claude-sonnet-4-5"
        self.fallback_model = "claude-haiku-4-5-20251001"

        self.openai_client = None
        self.openai_model = "gpt-4o-mini"
        if openai_api_key:
            try:
                from openai import OpenAI
                self.openai_client = OpenAI(api_key=openai_api_key)
                logger.info("Story AI: OpenAI fallback enabled")
            except ImportError:
                logger.warning("openai package not installed - fallback disabled")

    def _retry_anthropic(self, **kwargs):
        """Call Anthropic API with up to 3 retries for 429/529 errors."""
        max_retries = 3
        base_delay = 5
        last_error = None

        for attempt in range(max_retries):
            try:
                return self.client.messages.create(**kwargs)
            except anthropic.APIStatusError as e:
                if e.status_code in (429, 529):
                    last_error = e
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(f"Anthropic overloaded (attempt {attempt+1}), retrying in {delay}s...")
                        time.sleep(delay)
                else:
                    raise

        raise last_error or RuntimeError("Unreachable")

    def _get_response_text(self, model: str, messages: list, system: str = None) -> str:
        """Get AI response with fallback chain: requested model -> fallback model -> OpenAI."""
        anthropic_models = [model]
        if model != self.fallback_model:
            anthropic_models.append(self.fallback_model)

        last_error = None
        for attempt_model in anthropic_models:
            try:
                kwargs = {
                    "model": attempt_model,
                    "max_tokens": 1000,
                    "messages": messages,
                }
                if system:
                    kwargs["system"] = system
                response = self._retry_anthropic(**kwargs)
                return response.content[0].text
            except anthropic.APIStatusError as e:
                is_usage_limit = e.status_code == 400 and "usage" in str(e).lower()
                if e.status_code in (429, 529, 404) or is_usage_limit:
                    last_error = e
                    logger.warning(f"Anthropic {attempt_model} unavailable ({e.status_code})")
                    if is_usage_limit:
                        break
                    continue
                raise

        if self.openai_client:
            logger.warning("Anthropic unavailable, falling back to OpenAI")
            openai_messages = []
            if system:
                openai_messages.append({"role": "system", "content": system})
            openai_messages.extend(messages)
            response = self.openai_client.chat.completions.create(
                model=self.openai_model,
                max_tokens=1000,
                messages=openai_messages,
            )
            return response.choices[0].message.content

        raise last_error or RuntimeError("All AI providers unavailable")

    def _parse_json(self, text: str) -> dict:
        """Parse JSON from AI response with cleanup."""
        cleaned = text.strip()
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned, flags=re.MULTILINE)
        cleaned = re.sub(r'\s*```\s*$', '', cleaned)
        cleaned = cleaned.strip()

        # Try direct parse
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Try extracting JSON object
        match = re.search(r'\{[\s\S]*\}', cleaned)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        # Fix trailing commas
        fixed = re.sub(r',(\s*[}\]])', r'\1', cleaned)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError as e:
            raise e

    async def revise_text(self, text: str) -> dict:
        """Revise text and return {"revised": "...", "notes": "..."}.

        Returns {"revised": None, "notes": None} if AI call fails.
        Runs the blocking API call in a thread executor.
        """
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._revise_sync, text)
            return result
        except Exception as e:
            logger.error(f"Story AI revision failed: {e}")
            return {"revised": None, "notes": None}

    def _revise_sync(self, text: str) -> dict:
        """Synchronous revision call."""
        response_text = self._get_response_text(
            model=self.primary_model,
            messages=[{"role": "user", "content": text}],
            system=SYSTEM_PROMPT,
        )

        result = self._parse_json(response_text)
        revised = result.get("revised")
        notes = result.get("notes")

        if not revised or not notes:
            logger.warning(f"Incomplete AI response: {response_text[:200]}")
            return {"revised": revised, "notes": notes}

        return {"revised": revised, "notes": notes}
```

- [ ] **Step 2: Commit**

```bash
git add story/ai_handler.py
git commit -m "feat(story): add AI handler for text revision with Sonnet + fallback chain"
```

---

### Task 2: Update table format and entry functions in `story/story_bot.py`

**Files:**
- Modify: `story/story_bot.py:50` (TABLE_HEADER)
- Modify: `story/story_bot.py:128-187` (_escape_pipe, _append_entry)
- Modify: `story/story_bot.py:252-281` (_get_today_entries)

- [ ] **Step 1: Update TABLE_HEADER to 4 columns**

Change line 50 from:
```python
TABLE_HEADER = "| Time | Story |\n|------|-------|"
```
to:
```python
TABLE_HEADER = "| Time | Story | Revised | Notes |\n|------|-------|---------|-------|"
```

- [ ] **Step 2: Update `_append_entry` to write 4-column rows**

Change the function signature and row format. The function now returns `(timestamp, today_str)` instead of just `timestamp`.

In `_append_entry`, change the `new_row` line (around line 140):
```python
# OLD:
new_row = f"| {timestamp} | {escaped_text} |"

# NEW:
new_row = f"| {timestamp} | {escaped_text} |  |  |"
```

Also change the return to return both values:
```python
# OLD:
return timestamp

# NEW:
return timestamp, today_str
```

- [ ] **Step 3: Add `_update_entry_revision` function**

Add this new function after `_append_entry` (around line 188):

```python
async def _update_entry_revision(date_str: str, timestamp: str, revised: str, notes: str):
    """Update the Revised and Notes columns for an existing entry."""
    content, _ = await _github_get()
    if not content:
        return

    date_header = f"## {date_str}"
    if date_header not in content:
        return

    escaped_revised = _escape_pipe(revised) if revised else ""
    escaped_notes = _escape_pipe(notes) if notes else ""

    lines = content.split("\n")
    in_target_date = False
    for i, line in enumerate(lines):
        if line.strip() == date_header:
            in_target_date = True
        elif in_target_date and line.startswith("## "):
            break
        elif in_target_date and line.startswith(f"| {timestamp} |"):
            # Parse existing row to get original story text
            match = re.match(r"\|\s*\S+\s*\|\s*(.*?)\s*\|.*\|.*\|$", line)
            if match:
                original_story = match.group(1)
            else:
                # Fallback: try 2-column format
                match2 = re.match(r"\|\s*\S+\s*\|\s*(.*?)\s*\|$", line)
                original_story = match2.group(1) if match2 else ""
            lines[i] = f"| {timestamp} | {original_story} | {escaped_revised} | {escaped_notes} |"
            break

    new_content = "\n".join(lines)
    if not new_content.endswith("\n"):
        new_content += "\n"
    await _github_put(new_content, f"story: revision {date_str} {timestamp}")
```

- [ ] **Step 4: Update `_get_today_entries` to show revised + notes**

Replace the display format in `_get_today_entries` (lines 252-281):

```python
async def _get_today_entries() -> str | None:
    """Get today's entries as readable text."""
    content, _ = await _github_get()
    if not content:
        return None

    today_str = _now().strftime("%Y-%m-%d")
    date_header = f"## {today_str}"

    if date_header not in content:
        return None

    lines = content.split("\n")
    in_today = False
    entries = []
    for line in lines:
        if line.strip() == date_header:
            in_today = True
            continue
        if in_today and line.startswith("## "):
            break
        if in_today and line.startswith("| ") and not line.startswith("|---") and not line.startswith("| Time"):
            # Parse table row: 4-column or 2-column
            match4 = re.match(r"\|\s*(\S+)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|$", line)
            match2 = re.match(r"\|\s*(\S+)\s*\|\s*(.*?)\s*\|$", line)
            if match4:
                time_str = match4.group(1)
                story = match4.group(2).strip()
                revised = match4.group(3).strip()
                notes = match4.group(4).strip()
                entry_text = f"{time_str}  {story}"
                if revised:
                    entry_text += f"\n  ✍️ {revised}"
                if notes:
                    entry_text += f"\n  📝 {notes}"
                entries.append(entry_text)
            elif match2:
                entries.append(f"{match2.group(1)}  {match2.group(2)}")

    if not entries:
        return None
    return f"Today ({today_str}):\n\n" + "\n\n".join(entries)
```

- [ ] **Step 5: Commit**

```bash
git add story/story_bot.py
git commit -m "feat(story): expand table to 4 columns (Story/Revised/Notes) and update entry functions"
```

---

### Task 3: Integrate AI into message handler

**Files:**
- Modify: `story/story_bot.py:12-15` (imports)
- Modify: `story/story_bot.py:40-44` (config)
- Modify: `story/story_bot.py:316-338` (handle_text)

- [ ] **Step 1: Add imports and initialize AI handler**

Add import at the top of `story/story_bot.py` (after existing imports, around line 15):
```python
from story.ai_handler import StoryAIHandler
```

Add AI handler initialization after the config section (around line 55):
```python
# AI handler for text revision
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
_ai_handler = None
if ANTHROPIC_API_KEY:
    _ai_handler = StoryAIHandler(ANTHROPIC_API_KEY, OPENAI_API_KEY)
else:
    logger.warning("ANTHROPIC_API_KEY not set - Story AI revision disabled")
```

- [ ] **Step 2: Update `handle_text` to call AI after saving**

Replace `handle_text` function:

```python
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save any text message as a story entry, then revise with AI."""
    if not is_authorized(update):
        return

    text = update.message.text.strip()
    if text in ("Today",):
        await today_command(update, context)
        return

    try:
        timestamp, today_str = await _append_entry(text)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Delete", callback_data=f"sdel_{today_str}_{timestamp}")]
        ])
        await update.message.reply_text(
            f"Saved ({timestamp})",
            reply_markup=keyboard,
        )

        # Call AI in background for revision
        if _ai_handler:
            import asyncio
            asyncio.create_task(_revise_and_reply(update, context, text, today_str, timestamp))

    except Exception as e:
        logger.error(f"Failed to save entry: {e}")
        await update.message.reply_text(f"Failed to save: {e}")


async def _revise_and_reply(update: Update, context: ContextTypes.DEFAULT_TYPE,
                            text: str, date_str: str, timestamp: str):
    """Background task: call AI for revision, send result, update file."""
    try:
        result = await _ai_handler.revise_text(text)
        revised = result.get("revised")
        notes = result.get("notes")

        if revised and notes:
            # Send revision message
            msg = f"✍️ Revised:\n{revised}\n\n📝 Notes:\n{notes}"
            await update.message.reply_text(msg, reply_markup=REPLY_KEYBOARD)

            # Update the file with revision
            await _update_entry_revision(date_str, timestamp, revised, notes)
        else:
            await update.message.reply_text(
                "AI revision unavailable.",
                reply_markup=REPLY_KEYBOARD,
            )
    except Exception as e:
        logger.error(f"AI revision failed: {e}")
        await update.message.reply_text(
            "AI revision unavailable.",
            reply_markup=REPLY_KEYBOARD,
        )
```

- [ ] **Step 3: Update `_delete_entry` to handle 4-column rows**

In `_delete_entry` (line 210), the row matching `line.startswith(f"| {timestamp} |")` already works for 4-column rows — no change needed.

The empty-section check (line 232) compares against `TABLE_HEADER.split("\n")[0]` which will now be the 4-column header — this also works correctly.

No code change needed for delete, just verify.

- [ ] **Step 4: Commit**

```bash
git add story/story_bot.py
git commit -m "feat(story): integrate AI revision into message handler with async background processing"
```

---

### Task 4: Update CLAUDE.md and push

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Update Story Bot description in CLAUDE.md**

In the Story Bot section (### 6. Story Bot), update the description to reflect AI revision. Add to the feature list:
- AI-powered revision using Sonnet (~$0.005/message)
- Grammar suggestions in Chinese
- Chinese text translated to English
- 4-column table: Time | Story | Revised | Notes
- Fallback chain: Sonnet -> Haiku -> GPT-4o-mini

Update the Key Files table to add `story/ai_handler.py`.

Add a new entry to Recent Changes.

- [ ] **Step 2: Commit and push**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with Story Bot AI revision feature"
git push
```
