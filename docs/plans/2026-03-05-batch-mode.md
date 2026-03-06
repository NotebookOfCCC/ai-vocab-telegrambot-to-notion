# Batch Mode Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a persistent reply keyboard with [Batch] and [Word Count] buttons; Batch mode lets users queue multiple phrases, analyze all in parallel, then save each card independently.

**Architecture:** Three additions — (1) a `count_entries_per_db()` method in `notion_handler.py`, (2) a persistent `ReplyKeyboardMarkup` shown on /start, (3) batch session state in `user_sessions` that accumulates phrases, runs parallel `analyze_input` calls, and sends one result card per phrase.

**Tech Stack:** python-telegram-bot v22, asyncio.gather for parallel analysis, Notion client pagination for counts.

---

## Relevant Existing Patterns (read before touching anything)

- `user_sessions[user_id]` dict holds all per-user state. Keys currently used: `pending_entries`, `original_input`, `dup_page_ids`, `last_button_message_id`, `last_button_message_chat_id`, `awaiting_explanation_for`, `session_model_key`, `session_model_id`, `from_cache`, `duplicate_text`.
- `_check_duplicates_parallel()` runs Notion dup checks concurrently — reuse this for batch cards.
- `_build_save_keyboard()` and `_build_edit_keyboard()` build inline keyboards — batch cards use their own simpler keyboard.
- `loop.run_in_executor(None, fn, *args)` is the pattern for running sync Notion/AI calls without blocking.
- `notion_handler.all_database_ids` contains the list of all DB IDs (primary + additional).

---

## Task 1: Add `count_entries_per_db()` to NotionHandler

**Files:**
- Modify: `notion_handler.py` (add method to `NotionHandler` class, after `test_connection`)

**Context:** Notion's query API returns pages. To count, paginate with `page_size=100` until no more pages. Filter out `__CONFIG_` pages (they use `__CONFIG_` prefix in the title — see `_parse_page_to_entry` at line 928 for how that filter works).

**Step 1: Write the failing test**

Create `tests/test_notion_count.py`:

```python
"""Tests for NotionHandler.count_entries_per_db()"""
import pytest
from unittest.mock import MagicMock, patch


def _make_handler(db_ids):
    from notion_handler import NotionHandler
    with patch("notion_handler.Client"):
        handler = NotionHandler.__new__(NotionHandler)
        handler.client = MagicMock()
        handler.database_id = db_ids[0]
        handler.all_database_ids = db_ids
        handler._category_options = None
        return handler


def _make_page(title):
    return {
        "properties": {
            "English": {
                "type": "title",
                "title": [{"plain_text": title}]
            }
        }
    }


def test_count_single_db_two_entries():
    handler = _make_handler(["db1"])
    handler.client.databases.query.return_value = {
        "results": [_make_page("hello"), _make_page("world")],
        "has_more": False,
    }
    counts = handler.count_entries_per_db()
    assert counts == {"db1": 2}


def test_count_skips_config_pages():
    handler = _make_handler(["db1"])
    handler.client.databases.query.return_value = {
        "results": [_make_page("hello"), _make_page("__CONFIG_review_schedule__")],
        "has_more": False,
    }
    counts = handler.count_entries_per_db()
    assert counts == {"db1": 1}


def test_count_multiple_dbs():
    handler = _make_handler(["db1", "db2"])
    def query_side_effect(database_id, **kwargs):
        if database_id == "db1":
            return {"results": [_make_page("a"), _make_page("b"), _make_page("c")], "has_more": False}
        return {"results": [_make_page("x")], "has_more": False}
    handler.client.databases.query.side_effect = query_side_effect
    counts = handler.count_entries_per_db()
    assert counts == {"db1": 3, "db2": 1}
```

**Step 2: Run tests to confirm they fail**

```bash
cd "C:\Users\yaqio\Desktop\Lisa\02. Project Information\07.AI\ai-vocab-telegrambot-to-notion"
python -m pytest tests/test_notion_count.py -v
```
Expected: `ERROR` — `count_entries_per_db` does not exist yet.

**Step 3: Implement the method**

In `notion_handler.py`, add after the `test_connection` method (around line 272):

```python
def count_entries_per_db(self) -> dict:
    """Return word count per database, excluding __CONFIG_ pages.

    Returns:
        dict mapping db_id -> int count
    """
    counts = {}
    for db_id in self.all_database_ids:
        count = 0
        cursor = None
        while True:
            kwargs = {"database_id": db_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            try:
                resp = self.client.databases.query(**kwargs)
            except Exception as e:
                logger.warning(f"count_entries_per_db failed for {db_id}: {e}")
                break
            for page in resp.get("results", []):
                props = page.get("properties", {})
                # Find the title property (English field)
                title_text = ""
                for prop in props.values():
                    if prop.get("type") == "title":
                        parts = prop.get("title", [])
                        if parts:
                            title_text = parts[0].get("plain_text", "")
                        break
                if not title_text.startswith("__CONFIG_"):
                    count += 1
            if resp.get("has_more"):
                cursor = resp.get("next_cursor")
            else:
                break
        counts[db_id] = count
    return counts
```

**Step 4: Run tests to confirm they pass**

```bash
python -m pytest tests/test_notion_count.py -v
```
Expected: all 3 tests PASS.

**Step 5: Commit**

```bash
git add tests/test_notion_count.py notion_handler.py
git commit -m "feat: add count_entries_per_db to NotionHandler"
```

---

## Task 2: Persistent Reply Keyboard + Word Count Handler

**Files:**
- Modify: `bot.py`

**Context:** `ReplyKeyboardMarkup` in python-telegram-bot creates a persistent bottom keyboard. Pass it as `reply_markup` on any message to show it; it stays until removed with `ReplyKeyboardRemove`. Send it on `/start` so it appears immediately. The keyboard has two buttons: "Batch" and "Word Count". These arrive as ordinary text messages, so `handle_message` must intercept them before the normal flow.

**Step 1: Add import and keyboard helper**

At the top of `bot.py`, add `ReplyKeyboardMarkup` to the telegram import line:

```python
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
```

After the `REANALYZE_MODELS` block (around line 63), add:

```python
REPLY_KEYBOARD = ReplyKeyboardMarkup(
    [["Batch", "Word Count"]],
    resize_keyboard=True,
    is_persistent=True,
)
```

**Step 2: Show keyboard on /start**

In the `start()` function, change the final `reply_text` call to include the keyboard:

```python
await update.message.reply_text(welcome_message, reply_markup=REPLY_KEYBOARD)
```

**Step 3: Add word count handler**

Add this function after `clear_cache()`:

```python
async def handle_word_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reply with word count per Notion database."""
    await update.message.reply_text("Counting words...")
    loop = asyncio.get_running_loop()
    try:
        counts = await loop.run_in_executor(None, notion_handler.count_entries_per_db)
    except Exception as e:
        await update.message.reply_text(f"Error fetching counts: {e}")
        return

    db_ids = list(counts.keys())
    lines = []
    for i, db_id in enumerate(db_ids):
        label = "Primary DB" if db_id == NOTION_DB_ID else f"Archive DB {i}"
        lines.append(f"- {label}: {counts[db_id]:,} words")
    total = sum(counts.values())
    lines.append(f"- Total: {total:,} words")
    await update.message.reply_text("Word Count:\n" + "\n".join(lines))
```

**Step 4: Route "Word Count" text in handle_message**

At the very top of `handle_message`, before the pending-entries check (around line 206), add:

```python
    # Persistent reply keyboard actions
    if text == "Word Count":
        await handle_word_count(update, context)
        return
    if text == "Batch":
        await handle_batch_start(update, context)
        return
```

**Step 5: Manual smoke test**

Run the bot locally with `python bot.py`, send `/start`, confirm the reply keyboard appears. Tap "Word Count", confirm a count message appears.

**Step 6: Commit**

```bash
git add bot.py
git commit -m "feat: add persistent reply keyboard and Word Count handler"
```

---

## Task 3: Batch Collection Mode

**Files:**
- Modify: `bot.py`

**Context:** Batch state lives in `user_sessions[user_id]` under these keys:
- `batch_mode: True` — signals collection mode is active
- `batch_queue: list[str]` — raw phrases the user has sent
- `batch_collect_msg_id: int` — message ID of the "Batch mode on" message (to update button label)
- `batch_collect_chat_id: int` — chat ID of same message

When in batch mode, incoming text messages add to `batch_queue` and update the [Analyze (N)] button. The [Analyze (N)] button has callback_data `"batch_analyze"`.

Note: batch mode and normal pending_entries mode are mutually exclusive. Starting batch mode clears any existing pending session.

**Step 1: Add `handle_batch_start()`**

Add this function after `handle_word_count()`:

```python
async def handle_batch_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enter batch collection mode."""
    user_id = update.effective_user.id
    # Clear any existing session
    user_sessions[user_id] = {
        "batch_mode": True,
        "batch_queue": [],
    }
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Analyze (0)", callback_data="batch_analyze")
    ]])
    sent = await update.message.reply_text(
        "Batch mode on. Send your phrases one by one. Tap Analyze when ready.",
        reply_markup=keyboard,
    )
    user_sessions[user_id]["batch_collect_msg_id"] = sent.message_id
    user_sessions[user_id]["batch_collect_chat_id"] = sent.chat_id
```

**Step 2: Handle incoming phrases during batch collection**

In `handle_message`, after the `"Batch"` / `"Word Count"` intercepts and before the pending_entries check, add:

```python
    # Batch collection mode: add phrase to queue
    if user_sessions.get(user_id, {}).get("batch_mode"):
        session = user_sessions[user_id]
        session["batch_queue"].append(text)
        n = len(session["batch_queue"])
        # Update the Analyze button count
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=session["batch_collect_chat_id"],
                message_id=session["batch_collect_msg_id"],
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(f"Analyze ({n})", callback_data="batch_analyze")
                ]])
            )
        except Exception:
            pass
        await update.message.reply_text(f"Added ({n} phrase{'s' if n != 1 else ''} queued)")
        return
```

**Step 3: Route `batch_analyze` callback**

In `handle_callback()`, before the `tts_` check (top of the function), add:

```python
    if data == "batch_analyze":
        await handle_batch_analyze(query, context, user_id)
        return
```

**Step 4: Manual test**

Run bot, tap Batch, send 3 phrases one by one, confirm button updates to "Analyze (3)".

**Step 5: Commit**

```bash
git add bot.py
git commit -m "feat: batch collection mode with phrase queue"
```

---

## Task 4: Batch Analysis and Result Cards

**Files:**
- Modify: `bot.py`

**Context:** `handle_batch_analyze()` is called from the callback handler. It runs all `analyze_input` calls in parallel using `asyncio.gather` + `run_in_executor`. Each analysis produces one or more entries; for simplicity each *line the user sent* becomes one card (take the first entry from each analysis). After all analyses complete, send all cards together. Each card has [Save] [Skip] inline buttons with callback data `batch_save_{i}` and `batch_skip_{i}`.

Batch result state stored in `user_sessions[user_id]`:
- `batch_results: list[dict]` — list of analyzed entry dicts (one per phrase), may be None if analysis failed
- `batch_mode` is cleared (set to False or removed) once analysis starts

**Step 1: Add `handle_batch_analyze()`**

Add after `handle_batch_start()`:

```python
async def handle_batch_analyze(query, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Analyze all queued batch phrases in parallel and send result cards."""
    session = user_sessions.get(user_id, {})
    queue = session.get("batch_queue", [])

    if not queue:
        await query.answer("No phrases queued.", show_alert=True)
        return

    n = len(queue)
    await query.edit_message_text(f"Analyzing {n} phrase{'s' if n != 1 else ''}...", reply_markup=None)

    # Clear batch mode so new messages go through normal flow
    user_sessions[user_id] = {"batch_results": [None] * n}

    loop = asyncio.get_running_loop()
    analyses = await asyncio.gather(*[
        loop.run_in_executor(None, ai_handler.analyze_input, phrase)
        for phrase in queue
    ], return_exceptions=True)

    # Extract first entry from each analysis (or error placeholder)
    results = []
    for i, analysis in enumerate(analyses):
        if isinstance(analysis, Exception) or "error" in (analysis or {}):
            results.append(None)
        else:
            entries = (analysis or {}).get("entries", [])
            results.append(entries[0] if entries else None)

    user_sessions[user_id]["batch_results"] = results

    # Send all cards
    for i, entry in enumerate(results):
        if entry is None:
            await query.message.reply_text(
                f"[{i+1}/{n}] Could not analyze: {queue[i]}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Skip", callback_data=f"batch_skip_{i}")
                ]])
            )
        else:
            card_text = f"[{i+1}/{n}] {ai_handler._format_single_entry(entry)}"
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("Save", callback_data=f"batch_save_{i}"),
                InlineKeyboardButton("Skip", callback_data=f"batch_skip_{i}"),
            ]])
            await query.message.reply_text(card_text, reply_markup=keyboard)
```

**Step 2: Handle `batch_save_N` and `batch_skip_N` callbacks**

In `handle_callback()`, after the `batch_analyze` route, add:

```python
    if data.startswith("batch_save_"):
        idx = int(data[len("batch_save_"):])
        session = user_sessions.get(user_id, {})
        results = session.get("batch_results", [])
        if idx >= len(results) or results[idx] is None:
            await query.answer("Entry not found.", show_alert=True)
            return
        entry = results[idx]
        # Check for existing duplicate
        dup = notion_handler.find_entry_by_english(entry.get("english", ""))
        if dup:
            result = notion_handler.update_entry_content(dup["page_id"], entry)
            verb = "Replaced"
        else:
            result = notion_handler.save_entry(entry)
            verb = "Saved"
        if result["success"]:
            chinese = entry.get("chinese", "")
            short_zh = chinese.split("；")[0].split(";")[0].split("，")[0].split(",")[0].strip()
            await query.edit_message_text(
                f"— {verb}: {entry['english']} - {short_zh} ({entry['category']})",
                reply_markup=None,
            )
        else:
            await query.answer(f"Save failed: {result.get('error', '?')}", show_alert=True)
        return

    if data.startswith("batch_skip_"):
        await query.edit_message_reply_markup(reply_markup=None)
        return
```

**Step 3: Manual end-to-end test**

1. Run bot, tap Batch
2. Send 3 phrases (including one messy: "give it a shot - from meeting")
3. Tap Analyze (3)
4. Confirm 3 cards arrive together, each with Save/Skip
5. Tap Save on one — confirm "Saved: ..." confirmation
6. Tap Skip on another — confirm buttons disappear
7. Send a new phrase (normal flow) — confirm it analyzes independently without disturbing remaining batch card

**Step 4: Commit**

```bash
git add bot.py
git commit -m "feat: batch analysis with parallel processing and per-card Save/Skip"
```

---

## Task 5: Update CLAUDE.md and Push

**Step 1: Add to Recent Changes in CLAUDE.md**

Add this line to the Recent Changes list:

```
48. **Batch mode**: [Batch] reply keyboard button queues multiple phrases, analyzes all in parallel, sends one card per phrase with Save/Skip buttons. [Word Count] button shows word counts per Notion database.
```

**Step 2: Commit and push**

```bash
git add CLAUDE.md
git commit -m "docs: record batch mode and word count features"
git push
```
