# Pending Review Resend Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a 📋 Pending button to the review bot that resends unanswered cards from the current session as fresh review cards with chunked audio (10 phrases per MP3).

**Architecture:** Track `pending_batch: dict[str, dict]` (page_id → entry) in memory. Populate on batch send, remove on rating. "📋 Pending" resends remaining entries. Replace single combined audio with 10-phrase chunks everywhere.

**Tech Stack:** python-telegram-bot v22, edge-tts, APScheduler, Notion API

---

### Task 1: Add pending_batch global and populate on batch send

**Files:**
- Modify: `review_bot.py`

**Step 1: Add global `pending_batch` dict after existing globals (around line 101)**

Find:
```python
is_paused = False
review_config = None
```
Replace with:
```python
is_paused = False
review_config = None
pending_batch: dict = {}  # page_id → entry; cleared on new batch, entry removed on rating
```

**Step 2: Populate pending_batch when cards are sent in `send_review_batch`**

In `send_review_batch`, find the loop that sends individual cards:
```python
        total = len(entries)
        for i, entry in enumerate(entries, 1):
```

Add `pending_batch` population just before the loop:
```python
        # Track which cards have been sent but not yet rated
        global pending_batch
        pending_batch = {entry.get("page_id", ""): entry for entry in entries if entry.get("page_id")}

        total = len(entries)
        for i, entry in enumerate(entries, 1):
```

**Step 3: Commit**
```bash
git add review_bot.py
git commit -m "feat: add pending_batch tracking - populate on batch send"
```

---

### Task 2: Remove entries from pending_batch on rating

**Files:**
- Modify: `review_bot.py` — `handle_review_callback` function (around line 591)

**Step 1: Add removal in each rating branch**

In `handle_review_callback`, add `pending_batch.pop(page_id, None)` after extracting `page_id` in each of the three branches. The function currently looks like:

```python
    if data.startswith("again_"):
        page_id = data[6:]
        result = notion_handler.update_review_stats(page_id, response="again")
        ...

    elif data.startswith("good_"):
        page_id = data[5:]
        result = notion_handler.update_review_stats(page_id, response="good")
        ...

    elif data.startswith("easy_"):
        page_id = data[5:]
        result = notion_handler.update_review_stats(page_id, response="easy")
        ...
```

After each `page_id = data[...]` line in all three branches, add:
```python
        pending_batch.pop(page_id, None)
```

**Step 2: Commit**
```bash
git add review_bot.py
git commit -m "feat: remove entry from pending_batch when rated"
```

---

### Task 3: Replace single audio with 10-phrase chunked audio

**Files:**
- Modify: `review_bot.py` — replace `generate_batch_audio` and update caller

**Step 1: Replace `generate_batch_audio` with `generate_chunked_audio`**

Remove the existing `generate_batch_audio` function entirely and replace with:

```python
async def generate_chunked_audio(entries: list, chunk_size: int = 10) -> list[tuple[io.BytesIO, str]]:
    """Generate audio in chunks of chunk_size phrases each.

    Returns list of (audio_buf, caption) tuples, e.g.:
        [(buf, "🔊 1–10"), (buf, "🔊 11–20"), ...]
    Phrases that fail are skipped so the rest still play.
    """
    try:
        import edge_tts
    except ImportError:
        logger.warning("edge-tts not installed, skipping audio")
        return []

    voice = "en-GB-SoniaNeural"
    phrases = [_clean_phrase_for_tts(e.get("english", "")) for e in entries]
    phrases = [p for p in phrases if p]
    if not phrases:
        return []

    results = []
    for chunk_start in range(0, len(phrases), chunk_size):
        chunk = phrases[chunk_start:chunk_start + chunk_size]
        chunk_end = chunk_start + len(chunk)
        label = f"🔊 {chunk_start + 1}–{chunk_end}"

        combined = io.BytesIO()
        for phrase in chunk:
            try:
                buf = io.BytesIO()
                async for audio_chunk in edge_tts.Communicate(phrase, voice).stream():
                    if audio_chunk["type"] == "audio":
                        buf.write(audio_chunk["data"])
                audio = buf.getvalue()
                if audio:
                    combined.write(audio)
                    logger.info(f"TTS OK: '{phrase}' → {len(audio)} bytes")
                else:
                    logger.warning(f"TTS empty for: '{phrase}'")
            except Exception as e:
                logger.error(f"TTS error for '{phrase}': {e}")

        combined.seek(0)
        total_bytes = combined.getbuffer().nbytes
        if total_bytes > 0:
            results.append((combined, label))
            logger.info(f"Chunk '{label}': {total_bytes} bytes for {len(chunk)} phrases")
        else:
            logger.warning(f"Chunk '{label}' produced no audio")

    return results
```

**Step 2: Update `send_review_batch` to send chunked audio**

Find the existing audio-sending block:
```python
        # Send combined pronunciation audio for the whole batch
        audio_buf = await generate_batch_audio(entries)
        if audio_buf:
            audio_filename = f"{now.strftime('%Y-%m-%d_%H-%M')}.mp3"
            await application.bot.send_audio(
                chat_id=REVIEW_USER_ID,
                audio=audio_buf,
                filename=audio_filename,
                caption=f"🔊 {total} phrases",
            )
        else:
            logger.warning("Batch audio generation skipped or failed")
            await application.bot.send_message(
                chat_id=REVIEW_USER_ID,
                text="⚠️ Audio generation failed (edge-tts unavailable)",
            )
```

Replace with:
```python
        # Send pronunciation audio in chunks of 10
        audio_chunks = await generate_chunked_audio(entries)
        if audio_chunks:
            for audio_buf, caption in audio_chunks:
                await application.bot.send_audio(
                    chat_id=REVIEW_USER_ID,
                    audio=audio_buf,
                    filename=f"{now.strftime('%Y-%m-%d_%H-%M')}.mp3",
                    caption=caption,
                )
        else:
            logger.warning("Batch audio generation skipped or failed")
            await application.bot.send_message(
                chat_id=REVIEW_USER_ID,
                text="⚠️ Audio generation failed (edge-tts unavailable)",
            )
```

**Step 3: Commit**
```bash
git add review_bot.py
git commit -m "feat: chunk batch audio into groups of 10 phrases"
```

---

### Task 4: Add send_pending_resend function

**Files:**
- Modify: `review_bot.py` — add new function after `send_review_batch`

**Step 1: Add `send_pending_resend` function**

Add this function after `send_review_batch` (around line 276):

```python
async def send_pending_resend():
    """Resend cards from pending_batch that haven't been rated yet."""
    if not pending_batch:
        await application.bot.send_message(
            chat_id=REVIEW_USER_ID,
            text="✅ All caught up! No pending cards.",
        )
        return

    entries = list(pending_batch.values())
    total = len(entries)
    logger.info(f"Resending {total} pending cards")

    for i, entry in enumerate(entries, 1):
        message = format_entry_for_review(entry, i, total)
        page_id = entry.get("page_id", "")
        keyboard = [[
            InlineKeyboardButton("🔴 Again", callback_data=f"again_{page_id}"),
            InlineKeyboardButton("🟡 Good", callback_data=f"good_{page_id}"),
            InlineKeyboardButton("🟢 Easy", callback_data=f"easy_{page_id}"),
        ]]
        await application.bot.send_message(
            chat_id=REVIEW_USER_ID,
            text=message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

    import datetime
    now = datetime.datetime.now()
    audio_chunks = await generate_chunked_audio(entries)
    if audio_chunks:
        for audio_buf, caption in audio_chunks:
            await application.bot.send_audio(
                chat_id=REVIEW_USER_ID,
                audio=audio_buf,
                filename=f"{now.strftime('%Y-%m-%d_%H-%M')}.mp3",
                caption=caption,
            )
```

**Step 2: Commit**
```bash
git add review_bot.py
git commit -m "feat: add send_pending_resend function"
```

---

### Task 5: Add 📋 Pending to reply keyboard and wire up handler

**Files:**
- Modify: `review_bot.py` — `get_main_keyboard`, `handle_keyboard_button`, message handler filter

**Step 1: Update `get_main_keyboard`**

Find:
```python
    return ReplyKeyboardMarkup(
        [["📖 Review", "📊 Due"]],
```
Replace with:
```python
    return ReplyKeyboardMarkup(
        [["📖 Review", "📊 Due", "📋 Pending"]],
```

**Step 2: Add handler in `handle_keyboard_button`**

Find:
```python
    elif text == "📊 Due":
        await due_command(update, context)
```
Add after:
```python
    elif text == "📋 Pending":
        await send_pending_resend()
```

**Step 3: Update MessageHandler filter to include new button text**

Find:
```python
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r"^(📖 Review|📊 Due)$"),
        handle_keyboard_button
    ))
```
Replace with:
```python
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(r"^(📖 Review|📊 Due|📋 Pending)$"),
        handle_keyboard_button
    ))
```

**Step 4: Commit**
```bash
git add review_bot.py
git commit -m "feat: add Pending button to reply keyboard"
```

---

### Task 6: Update CLAUDE.md and push

**Files:**
- Modify: `CLAUDE.md` — Recent Changes section

**Step 1: Add entry to Recent Changes**

Add to the bottom of the Recent Changes list:
```
49. **Pending review resend**: 📋 Pending button resends unanswered cards from current batch with chunked audio. Regular batch audio also split into 10-phrase chunks.
```

**Step 2: Commit and push**
```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with pending review feature"
git push
```
