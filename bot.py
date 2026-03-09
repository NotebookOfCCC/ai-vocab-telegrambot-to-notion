"""
Telegram Vocabulary Learning Bot
Main entry point - handles Telegram interactions
"""
import os
import io
import re
import asyncio
import logging
from dotenv import load_dotenv
import edge_tts
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from ai_handler import AIHandler, CATEGORIES, CATEGORY_LIST
from notion_handler import NotionHandler
from cache_handler import CacheHandler

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize handlers
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
NOTION_KEY = os.getenv("NOTION_API_KEY")
NOTION_DB_ID = os.getenv("NOTION_DATABASE_ID")
ADDITIONAL_DB_IDS_RAW = os.getenv("ADDITIONAL_DATABASE_IDS", "")
ADDITIONAL_DB_IDS = [db_id.strip() for db_id in ADDITIONAL_DB_IDS_RAW.split(",") if db_id.strip()]
USE_CHEAP_MODEL = os.getenv("USE_CHEAP_MODEL", "false").lower() == "true"  # Set to "true" to save ~90% on API costs
ALLOWED_USERS = os.getenv("ALLOWED_USER_IDS", "").split(",")
ALLOWED_USERS = [uid.strip() for uid in ALLOWED_USERS if uid.strip()]

ai_handler = None
notion_handler = None
cache_handler = None

# Store user session data (pending entries to save)
user_sessions = {}

# Models available for re-analysis via the 🔄 button
# (key, display label, model ID)
REANALYZE_MODELS = [
    ("haiku",    "🤖 Haiku",   "claude-haiku-4-5-20251001"),
    ("sonnet",   "🧠 Sonnet",  "claude-sonnet-4-5"),
    ("gpt4mini", "💡 GPT-4o",  "gpt-4o-mini"),
]
_MODEL_ID   = {k: mid  for k, _, mid  in REANALYZE_MODELS}
_MODEL_LABEL = {k: lbl  for k, lbl, _ in REANALYZE_MODELS}
DEFAULT_MODEL_KEY = "haiku"

REPLY_KEYBOARD = ReplyKeyboardMarkup(
    [["Batch", "Word Count"]],
    resize_keyboard=True,
    is_persistent=True,
)


def is_user_allowed(user_id: int) -> bool:
    """Check if user is allowed to use the bot."""
    if not ALLOWED_USERS or ALLOWED_USERS == [""]:
        return True  # No restriction if ALLOWED_USER_IDS is empty
    return str(user_id) in ALLOWED_USERS


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    logger.info(f"Received /start from user {update.effective_user.id}")
    if not is_user_allowed(update.effective_user.id):
        logger.info(f"User {update.effective_user.id} not allowed")
        await update.message.reply_text("Sorry, this bot is private.")
        return

    welcome_message = """
Welcome to Vocab Learning Bot!

How to use:
1. Send me any English word, phrase, or sentence
2. I'll analyze it and provide learning content
3. Reply with a number to save to Notion

Commands:
/start - Show this message
/test - Test Notion connection
/help - Show help

Just send me some English text to get started!
"""
    await update.message.reply_text(welcome_message, reply_markup=REPLY_KEYBOARD)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    if not is_user_allowed(update.effective_user.id):
        return

    help_text = f"""
Vocab Learning Bot Help

Send me:
- A single word: "procrastinate"
- A phrase: "break the ice"
- A sentence: "I've been putting off this task"

I will:
1. Check grammar (for sentences)
2. Extract learnable phrases
3. Provide explanations in Chinese
4. Give example sentences
5. Categorize the content

Reply with number(s) to save entries to Notion.

Categories available:
{CATEGORY_LIST}
"""
    await update.message.reply_text(help_text)


async def test_notion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /test command - test Notion connection."""
    if not is_user_allowed(update.effective_user.id):
        return

    if not notion_handler:
        await update.message.reply_text("Notion handler not initialized. Check API key.")
        return

    result = notion_handler.test_connection()

    if result["success"]:
        props = ", ".join(result["properties"][:10])
        if len(result["properties"]) > 10:
            props += f"... (+{len(result['properties']) - 10} more)"

        await update.message.reply_text(
            f"Notion connection successful!\n\n"
            f"Database: {result['database_title']}\n"
            f"Properties: {props}"
        )
    else:
        await update.message.reply_text(f"Notion connection failed:\n{result['error']}")


async def clear_session(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /clear command - clear pending entries."""
    if not is_user_allowed(update.effective_user.id):
        return

    user_id = update.effective_user.id
    user_sessions[user_id] = {}
    await update.message.reply_text("Session cleared. Send me new text to analyze.")


async def clear_cache(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /clearcache command - clear the analysis cache."""
    if not is_user_allowed(update.effective_user.id):
        return
    count = cache_handler.clear()
    await update.message.reply_text(f"Cache cleared. Removed {count} entries.")


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
        count_str = str(counts[db_id]) if counts[db_id] is not None else "?"
        lines.append(f"- {label}: {count_str} words")
    total_known = sum(v for v in counts.values() if v is not None)
    has_unknown = any(v is None for v in counts.values())
    total_str = f"{total_known:,}+" if has_unknown else f"{total_known:,}"
    lines.append(f"- Total: {total_str} words")
    await update.message.reply_text("Word Count:\n" + "\n".join(lines), reply_markup=REPLY_KEYBOARD)


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


async def handle_batch_analyze(query, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    """Analyze all queued batch phrases in parallel and send result cards."""
    session = user_sessions.get(user_id, {})
    queue = session.get("batch_queue", [])

    if not queue:
        await query.message.reply_text("No phrases queued.")
        return

    n = len(queue)
    await query.edit_message_text(f"Analyzing {n} phrase{'s' if n != 1 else ''}...", reply_markup=None)

    # Clear batch mode so new messages go through normal flow
    user_sessions[user_id] = {"batch_results": [None] * n, "batch_phrases": list(queue)}

    loop = asyncio.get_running_loop()
    analyses = await asyncio.gather(*[
        loop.run_in_executor(None, ai_handler.analyze_input, phrase)
        for phrase in queue
    ], return_exceptions=True)

    # Extract first entry from each analysis
    results = []
    for analysis in analyses:
        if isinstance(analysis, Exception) or "error" in (analysis or {}):
            results.append(None)
        else:
            entries = (analysis or {}).get("entries", [])
            results.append(entries[0] if entries else None)

    user_sessions[user_id]["batch_results"] = results

    # Parallel duplicate check on non-None entries
    batch_dup_page_ids = {}
    non_none = [(i, e) for i, e in enumerate(results) if e is not None]
    if non_none:
        dup_checks = await asyncio.gather(*[
            loop.run_in_executor(None, notion_handler.find_entry_by_english, e.get("english", ""))
            for _, e in non_none
        ])
        for (i, _), dup in zip(non_none, dup_checks):
            if dup:
                batch_dup_page_ids[i] = dup["page_id"]
    user_sessions[user_id]["batch_dup_page_ids"] = batch_dup_page_ids

    # Send all cards
    for i, entry in enumerate(results):
        if entry is None:
            phrase_text = queue[i] if i < len(queue) else f"#{i+1}"
            await query.message.reply_text(
                f"[{i+1}/{n}] Could not analyze: {phrase_text}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Skip", callback_data=f"batch_skip_{i}")
                ]])
            )
        else:
            is_dup = i in batch_dup_page_ids
            save_label = "Replace" if is_dup else "Save"
            dup_note = " ⚠️ already in Notion" if is_dup else ""
            card_text = f"[{i+1}/{n}]{dup_note}\n{ai_handler._format_single_entry(entry)}"
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(save_label, callback_data=f"batch_save_{i}"),
                InlineKeyboardButton("Skip", callback_data=f"batch_skip_{i}"),
            ]])
            await query.message.reply_text(card_text, reply_markup=keyboard)

    # Re-show the persistent keyboard after all cards are sent
    await query.message.reply_text(
        f"Batch done — {n} card{'s' if n != 1 else ''} above.",
        reply_markup=REPLY_KEYBOARD,
    )


async def _check_duplicates_parallel(entries: list) -> tuple:
    """Check all entries for Notion duplicates in parallel.

    Returns (dup_notes list, dup_page_ids dict).
    Runs all Notion queries concurrently instead of sequentially.
    """
    if not entries:
        return [], {}

    loop = asyncio.get_running_loop()
    dup_results = await asyncio.gather(*[
        loop.run_in_executor(None, notion_handler.find_entry_by_english, entry.get("english", ""))
        for entry in entries
    ])

    dup_notes = []
    dup_page_ids = {}
    for i, dup in enumerate(dup_results):
        if dup:
            date_str = f" ({dup['date']})" if dup.get("date") else ""
            dup_notes.append(f"⚠️ #{i+1} already in Notion{date_str}")
            dup_page_ids[i] = dup["page_id"]

    return dup_notes, dup_page_ids


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages."""
    logger.info(f"Received message: {update.message.text} from user {update.effective_user.id}")
    user_id = update.effective_user.id

    if not is_user_allowed(user_id):
        logger.info(f"User {user_id} not allowed. ALLOWED_USERS: {ALLOWED_USERS}")
        await update.message.reply_text("Sorry, this bot is private.")
        return

    text = update.message.text.strip()

    # Persistent reply keyboard actions
    if text == "Word Count":
        await handle_word_count(update, context)
        return
    if text == "Batch":
        await handle_batch_start(update, context)
        return

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

    # Check if user has pending entries
    if user_id in user_sessions and user_sessions[user_id].get("pending_entries"):
        pending_entries = user_sessions[user_id].get("pending_entries", [])
        num_entries = len(pending_entries)

        # Check for save commands: y/yes/ok/save for single entry, or valid numbers
        if text.lower() in ["y", "yes", "ok", "save", "1"] and num_entries == 1:
            await handle_selection(update, context, "1")
            return

        # Check for valid number selections (must be within range)
        cleaned = text.replace(",", " ").replace(".", " ")
        parts = [p for p in cleaned.split() if p]
        if parts and all(p.isdigit() for p in parts):
            nums = [int(p) for p in parts]
            if all(1 <= n <= num_entries for n in nums):
                await handle_selection(update, context, text)
                return

        # Check if user is appending text to an explanation
        if user_sessions[user_id].get("awaiting_explanation_for") is not None:
            idx = user_sessions[user_id].pop("awaiting_explanation_for")
            if idx < len(pending_entries):
                entry = pending_entries[idx]
                old_expl = entry.get("explanation", "")
                entry["explanation"] = old_expl + "\n\n——\n" + text
                pending_entries[idx] = entry
                user_sessions[user_id]["pending_entries"] = pending_entries

                await _remove_previous_buttons(context, user_sessions[user_id])
                response = ai_handler._format_single_entry(entry)
                dup_page_ids = user_sessions[user_id].get("dup_page_ids", {})
                keyboard = _build_edit_keyboard(len(pending_entries), idx, is_dup=idx in dup_page_ids, entries=pending_entries)
                reply_markup = InlineKeyboardMarkup(keyboard)
                entry_label = f"[{idx + 1}] " if len(pending_entries) > 1 else ""
                sent = await update.message.reply_text(f"{entry_label}Explanation updated!\n{response}", reply_markup=reply_markup)
                user_sessions[user_id]["last_button_message_id"] = sent.message_id
                user_sessions[user_id]["last_button_message_chat_id"] = sent.chat_id
            return

        # Anything else = edit request (let AI handle it)
        await handle_edit_request(update, context, text)
        return

    # New input - check cache and duplicates before API call

    # Step 1: Check local cache
    cached_result = cache_handler.get(text)
    if cached_result and "entries" in cached_result:
        # Cache hit - free!
        entries = cached_result.get("entries", [])
        user_sessions[user_id] = {
            "pending_entries": entries,
            "original_input": text,
            "from_cache": True,
        }

        response = ai_handler.format_entries_for_display(cached_result)

        # Duplicate check on cached entries - run in parallel
        dup_notes, dup_page_ids = await _check_duplicates_parallel(entries)
        user_sessions[user_id]["dup_page_ids"] = dup_page_ids

        if dup_notes:
            response = "\n".join(dup_notes) + "\n\n" + response

        reply_markup = _build_save_keyboard(entries, dup_indices=set(dup_page_ids.keys()))
        sent_message = await update.message.reply_text(
            f"(cached)\n{response}", reply_markup=reply_markup
        )

        user_sessions[user_id]["last_button_message_id"] = sent_message.message_id
        user_sessions[user_id]["last_button_message_chat_id"] = sent_message.chat_id
        return

    # Step 2: For short phrase/word inputs only, check Notion for exact duplicates.
    # Skip for sentence-like inputs (>3 words): the raw sentence won't match stored phrases,
    # so the pre-check is always a miss and just delays "Analyzing..." feedback.
    word_count = len(text.split())
    if word_count <= 3:
        loop = asyncio.get_running_loop()
        duplicate = await loop.run_in_executor(None, notion_handler.find_entry_by_english, text)
        if duplicate:
            user_sessions[user_id] = {
                "duplicate_text": text,
            }
            keyboard = [[
                InlineKeyboardButton("Re-analyze", callback_data="reanalyze"),
                InlineKeyboardButton("Cancel", callback_data="cancel")
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            date_str = f" (saved: {duplicate['date']})" if duplicate.get('date') else ""
            sent_message = await update.message.reply_text(
                f"Already in Notion{date_str}:\n\n"
                f"{duplicate['english']}\n{duplicate['chinese']}\n\n"
                f"Re-analyze anyway?",
                reply_markup=reply_markup,
            )
            user_sessions[user_id]["last_button_message_id"] = sent_message.message_id
            user_sessions[user_id]["last_button_message_chat_id"] = sent_message.chat_id
            return

    # Step 3: No cache hit, no duplicate - call AI
    await update.message.reply_text("Analyzing...")

    try:
        loop = asyncio.get_running_loop()
        analysis = await loop.run_in_executor(None, ai_handler.analyze_input, text)

        if "error" in analysis:
            await update.message.reply_text(f"Error: {analysis['error']}")
            return

        # Cache the result for future lookups
        if not analysis.get("skipped_ai") and "error" not in analysis:
            cache_handler.put(text, analysis)

        entries = analysis.get("entries", [])

        # Store pending entries in session
        user_sessions[user_id] = {
            "pending_entries": entries,
            "original_input": text
        }

        # Format and send response
        response = ai_handler.format_entries_for_display(analysis)

        # Post-AI duplicate check on extracted phrases - run in parallel
        dup_notes, dup_page_ids = await _check_duplicates_parallel(entries)
        user_sessions[user_id]["dup_page_ids"] = dup_page_ids

        if dup_notes:
            response = "\n".join(dup_notes) + "\n\n" + response

        reply_markup = _build_save_keyboard(entries, dup_indices=set(dup_page_ids.keys()))
        sent_message = await update.message.reply_text(response, reply_markup=reply_markup)

        # Store message info so we can remove buttons later
        user_sessions[user_id]["last_button_message_id"] = sent_message.message_id
        user_sessions[user_id]["last_button_message_chat_id"] = sent_message.chat_id

    except Exception as e:
        logger.error(f"Error processing message: {e}")
        await update.message.reply_text(f"Error processing your input: {str(e)}")


async def handle_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Handle user's selection of entries to save."""
    user_id = update.effective_user.id
    session = user_sessions.get(user_id, {})
    pending_entries = session.get("pending_entries", [])

    if not pending_entries:
        await update.message.reply_text("No pending entries. Send me new text to analyze.")
        return

    # Parse selection (e.g., "1" or "1,2,3" or "1 2 3")
    try:
        # Handle various formats: "1", "1,2,3", "1 2 3", "1, 2, 3"
        selections = []
        for part in text.replace(",", " ").split():
            num = int(part.strip())
            if 1 <= num <= len(pending_entries):
                selections.append(num)

        if not selections:
            raise ValueError("No valid selections")

    except ValueError:
        await update.message.reply_text(
            f"Please enter valid number(s) between 1 and {len(pending_entries)}.\n"
            f"Example: 1 or 1,2,3"
        )
        return

    # Save selected entries
    saved_count = 0
    failed_count = 0

    for idx in selections:
        entry = pending_entries[idx - 1]

        # Display entry being saved
        display_text = ai_handler.format_entry_for_save_confirmation(entry)
        await update.message.reply_text(display_text)

        # Save to Notion
        result = notion_handler.save_entry(entry)

        if result["success"]:
            saved_count += 1
            await update.message.reply_text(f"Saved: {entry['english']}")
        else:
            failed_count += 1
            await update.message.reply_text(f"Failed to save: {result['error']}")

    # Clear session
    user_sessions[user_id] = {}

    # Summary
    if saved_count > 0:
        summary = f"\n{saved_count} entry(ies) saved to Notion!"
        if failed_count > 0:
            summary += f"\n{failed_count} entry(ies) failed."
        await update.message.reply_text(summary)


async def _remove_previous_buttons(context: ContextTypes.DEFAULT_TYPE, session: dict) -> None:
    """Remove buttons from the previous message if it exists."""
    msg_id = session.get("last_button_message_id")
    chat_id = session.get("last_button_message_chat_id")
    if msg_id and chat_id:
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=msg_id,
                reply_markup=None
            )
        except Exception:
            pass  # Message may have been deleted or already edited


async def handle_edit_request(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Handle edit/modification request for pending entry."""
    user_id = update.effective_user.id
    session = user_sessions.get(user_id, {})
    pending_entries = session.get("pending_entries", [])

    if not pending_entries:
        await update.message.reply_text("No pending entries to modify.")
        return

    # Detect which entry the user is referring to (0-indexed)
    target_idx = ai_handler.detect_target_entry(pending_entries, text)

    # Check if it's a simple category change with category name in text
    for cat in CATEGORIES:
        if cat in text:
            # Remove buttons from previous message
            await _remove_previous_buttons(context, session)

            pending_entries[target_idx]["category"] = cat
            user_sessions[user_id]["pending_entries"] = pending_entries
            entry = pending_entries[target_idx]
            response = ai_handler._format_single_entry(entry)

            # Re-check duplicate status
            dup_page_ids = session.get("dup_page_ids", {})
            dup = notion_handler.find_entry_by_english(entry.get("english", ""))
            if dup:
                dup_page_ids[target_idx] = dup["page_id"]
            else:
                dup_page_ids.pop(target_idx, None)
            user_sessions[user_id]["dup_page_ids"] = dup_page_ids

            keyboard = _build_edit_keyboard(len(pending_entries), target_idx, is_dup=target_idx in dup_page_ids, entries=pending_entries)
            reply_markup = InlineKeyboardMarkup(keyboard)

            entry_label = f"[{target_idx + 1}] " if len(pending_entries) > 1 else ""
            sent_message = await update.message.reply_text(
                f"{entry_label}Category → {cat}\n{response}",
                reply_markup=reply_markup
            )

            # Update message tracking
            user_sessions[user_id]["last_button_message_id"] = sent_message.message_id
            user_sessions[user_id]["last_button_message_chat_id"] = sent_message.chat_id
            return

    # Use AI to modify the entry based on user request
    await update.message.reply_text("Modifying...")

    entry = pending_entries[target_idx]
    loop = asyncio.get_running_loop()
    session_model = session.get("session_model_id")
    result = await loop.run_in_executor(None, ai_handler.modify_entry, entry, text, session_model)

    if result["success"]:
        # Remove buttons from previous message before showing new one
        await _remove_previous_buttons(context, session)

        # If user asked a question, send the answer first as a separate message
        if result.get("question_answer"):
            await update.message.reply_text(f"💬 {result['question_answer']}")

        pending_entries[target_idx] = result["entry"]
        user_sessions[user_id]["pending_entries"] = pending_entries

        response = ai_handler._format_single_entry(result["entry"])

        # Re-check duplicate status after edit
        dup_page_ids = session.get("dup_page_ids", {})
        dup = notion_handler.find_entry_by_english(result["entry"].get("english", ""))
        if dup:
            dup_page_ids[target_idx] = dup["page_id"]
        else:
            dup_page_ids.pop(target_idx, None)
        user_sessions[user_id]["dup_page_ids"] = dup_page_ids

        keyboard = _build_edit_keyboard(len(pending_entries), target_idx, is_dup=target_idx in dup_page_ids, entries=pending_entries)
        reply_markup = InlineKeyboardMarkup(keyboard)

        entry_label = f"[{target_idx + 1}] " if len(pending_entries) > 1 else ""
        sent_message = await update.message.reply_text(
            f"{entry_label}Updated!\n{response}",
            reply_markup=reply_markup
        )

        # Update message tracking
        user_sessions[user_id]["last_button_message_id"] = sent_message.message_id
        user_sessions[user_id]["last_button_message_chat_id"] = sent_message.chat_id
    else:
        # Remove buttons from previous message
        await _remove_previous_buttons(context, session)

        # Show buttons so user can escape the loop
        keyboard = _build_edit_keyboard(len(pending_entries), target_idx, entries=pending_entries)
        reply_markup = InlineKeyboardMarkup(keyboard)
        sent_message = await update.message.reply_text(
            "Couldn't understand that. Try again, Save current entry, or Start New.",
            reply_markup=reply_markup
        )

        # Update message tracking
        user_sessions[user_id]["last_button_message_id"] = sent_message.message_id
        user_sessions[user_id]["last_button_message_chat_id"] = sent_message.chat_id


def _extract_pronounce_text(english: str) -> str:
    """Extract just the word/phrase from 'word /phonetics/ (pos.)' format for TTS."""
    text = re.split(r'\s+[/(]', english)[0].strip()
    return text[:58]  # Leave room for "tts_" prefix in 64-byte callback_data limit


def _build_save_keyboard(entries: list, dup_indices: set = None) -> InlineKeyboardMarkup:
    """Build inline keyboard for save/cancel after analysis."""
    dup_indices = dup_indices or set()
    keyboard = []
    if len(entries) == 1:
        label = "Replace" if 0 in dup_indices else "Save"
        word = _extract_pronounce_text(entries[0].get("english", ""))
        keyboard.append([
            InlineKeyboardButton(label, callback_data="save_1"),
            InlineKeyboardButton("Cancel", callback_data="cancel"),
            InlineKeyboardButton("More", callback_data="others_menu"),
            InlineKeyboardButton("🔊", callback_data=f"tts_{word}"),
        ])
    else:
        # Row 1: [Save 1] [Save 2] [Save 3] [Save All]
        row1 = []
        for i in range(len(entries)):
            label = f"Replace {i+1}" if i in dup_indices else f"Save {i+1}"
            row1.append(InlineKeyboardButton(label, callback_data=f"save_{i+1}"))
        row1.append(InlineKeyboardButton("Save All", callback_data="save_all"))
        keyboard.append(row1)
        # Row 2: [Cancel] [🔄] [🔊1] [🔊2] [🔊3]
        row2 = [
            InlineKeyboardButton("Cancel", callback_data="cancel"),
            InlineKeyboardButton("More", callback_data="others_menu"),
        ]
        for i, entry in enumerate(entries):
            word = _extract_pronounce_text(entry.get("english", ""))
            row2.append(InlineKeyboardButton(f"🔊{i+1}", callback_data=f"tts_{word}"))
        keyboard.append(row2)
    return InlineKeyboardMarkup(keyboard)


def _build_edit_keyboard(num_entries: int, current_idx: int, is_dup: bool = False, entries: list = None) -> list:
    """Build inline keyboard for edit mode based on number of entries."""
    tts_word = ""
    if entries and current_idx < len(entries):
        tts_word = _extract_pronounce_text(entries[current_idx].get("english", ""))

    if num_entries == 1:
        row = [
            InlineKeyboardButton("Replace" if is_dup else "Save", callback_data="save_1"),
            InlineKeyboardButton("Cancel", callback_data="cancel"),
            InlineKeyboardButton("More", callback_data="others_menu"),
        ]
        if tts_word:
            row.append(InlineKeyboardButton("🔊", callback_data=f"tts_{tts_word}"))
        return [row]
    else:
        label = f"Replace [{current_idx + 1}]" if is_dup else f"Save [{current_idx + 1}]"
        row1 = [
            InlineKeyboardButton(label, callback_data=f"save_{current_idx + 1}"),
            InlineKeyboardButton("Save All", callback_data="save_all"),
        ]
        if tts_word:
            row1.append(InlineKeyboardButton("🔊", callback_data=f"tts_{tts_word}"))
        row2 = [
            InlineKeyboardButton("Cancel", callback_data="cancel"),
            InlineKeyboardButton("More", callback_data="others_menu"),
        ]
        return [row1, row2]


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard button presses."""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data
    session = user_sessions.get(user_id, {})
    pending_entries = session.get("pending_entries", [])

    if data == "batch_analyze":
        await handle_batch_analyze(query, context, user_id)
        return

    if data.startswith("batch_save_"):
        idx = int(data[len("batch_save_"):])
        session = user_sessions.get(user_id, {})
        results = session.get("batch_results", [])
        if idx >= len(results) or results[idx] is None:
            await query.answer("Entry not found.", show_alert=True)
            return
        entry = results[idx]
        loop = asyncio.get_running_loop()
        # Use pre-checked dup page_id if available; otherwise live-check
        batch_dup_page_ids = session.get("batch_dup_page_ids", {})
        page_id = batch_dup_page_ids.get(idx)
        if page_id is None:
            dup = await loop.run_in_executor(None, notion_handler.find_entry_by_english, entry.get("english", ""))
            page_id = dup["page_id"] if dup else None
        if page_id:
            result = await loop.run_in_executor(None, notion_handler.update_entry_content, page_id, entry)
            verb = "Replaced"
        else:
            result = await loop.run_in_executor(None, notion_handler.save_entry, entry)
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

    # Handle pronunciation (TTS) - works independently of session state
    if data.startswith("tts_"):
        word = data[4:]  # Remove "tts_" prefix
        if not word:
            return
        try:
            audio = io.BytesIO()
            communicate = edge_tts.Communicate(word, "en-GB-SoniaNeural")
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio.write(chunk["data"])
            audio.seek(0)
            if audio.getbuffer().nbytes == 0:
                raise ValueError("Empty audio generated")
            await query.message.reply_audio(audio=audio, filename=f"{word}.mp3")
        except Exception as e:
            logger.error(f"TTS error for '{word}': {e}")
            await query.message.reply_text("⚠️ Failed to generate audio")
        return

    # ── Model selector ──────────────────────────────────────────────────────
    if data == "model_select":
        current_key = session.get("session_model_key", DEFAULT_MODEL_KEY)
        row = []
        for key, label, _ in REANALYZE_MODELS:
            check = " ✓" if key == current_key else ""
            row.append(InlineKeyboardButton(f"{label}{check}", callback_data=f"use_model_{key}"))
        picker = InlineKeyboardMarkup([row, [InlineKeyboardButton("← Back", callback_data="others_menu")]])
        await query.edit_message_reply_markup(reply_markup=picker)
        return

    if data == "others_menu":
        # Show Others submenu: [Select Model] [Add to Explanation] [← Back]
        markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("Select Model", callback_data="model_select"),
            InlineKeyboardButton("Add to Explanation", callback_data="add_to_explanation"),
            InlineKeyboardButton("← Back", callback_data="others_back"),
        ]])
        await query.edit_message_reply_markup(reply_markup=markup)
        return

    if data in ("others_back", "model_back"):
        # Restore the normal save keyboard
        entries = session.get("pending_entries", [])
        if not entries:
            await query.edit_message_reply_markup(reply_markup=None)
            return
        dup_page_ids = session.get("dup_page_ids", {})
        reply_markup = _build_save_keyboard(entries, dup_indices=set(dup_page_ids.keys()))
        await query.edit_message_reply_markup(reply_markup=reply_markup)
        return

    if data == "add_to_explanation":
        entries = session.get("pending_entries", [])
        if not entries:
            await query.answer("No pending entries", show_alert=True)
            return
        if len(entries) == 1:
            user_sessions[user_id]["awaiting_explanation_for"] = 0
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("Reply with the text to append to the explanation:")
        else:
            # Show entry picker — one button per entry + Back
            row = []
            for i, entry in enumerate(entries):
                label = entry.get("english", f"#{i+1}").split("/")[0].strip()[:18]
                row.append(InlineKeyboardButton(f"{i+1}: {label}", callback_data=f"add_expl_pick_{i}"))
            markup = InlineKeyboardMarkup([row, [InlineKeyboardButton("← Back", callback_data="others_menu")]])
            await query.edit_message_reply_markup(reply_markup=markup)
        return

    if data.startswith("add_expl_pick_"):
        idx = int(data[len("add_expl_pick_"):])
        entries = session.get("pending_entries", [])
        label = entries[idx].get("english", f"#{idx+1}").split("/")[0].strip() if idx < len(entries) else f"#{idx+1}"
        user_sessions[user_id]["awaiting_explanation_for"] = idx
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"Reply with the text to append to the explanation of '{label}':")
        return

    if data.startswith("use_model_"):
        model_key = data[len("use_model_"):]
        if model_key not in _MODEL_ID:
            await query.answer("Unknown model", show_alert=True)
            return

        model_id = _MODEL_ID[model_key]
        model_label = _MODEL_LABEL[model_key]
        original_input = session.get("original_input", "")
        if not original_input:
            await query.answer("Session expired — send the text again", show_alert=True)
            return

        # Store chosen model in session BEFORE re-analysis
        user_sessions[user_id]["session_model_key"] = model_key
        user_sessions[user_id]["session_model_id"] = model_id

        await query.edit_message_text(f"Re-analyzing with {model_label}...", reply_markup=None)

        try:
            loop = asyncio.get_running_loop()
            analysis = await loop.run_in_executor(
                None, ai_handler.analyze_input, original_input, model_id
            )
            if "error" in analysis:
                await query.message.reply_text(f"Error: {analysis['error']}")
                return

            entries = analysis.get("entries", [])
            response = ai_handler.format_entries_for_display(analysis)

            # Duplicate check - run in parallel
            dup_notes, dup_page_ids = await _check_duplicates_parallel(entries)

            user_sessions[user_id]["pending_entries"] = entries
            user_sessions[user_id]["dup_page_ids"] = dup_page_ids

            if dup_notes:
                response = "\n".join(dup_notes) + "\n\n" + response

            model_note = "" if model_key == DEFAULT_MODEL_KEY else f"({model_label})\n"
            reply_markup = _build_save_keyboard(entries, dup_indices=set(dup_page_ids.keys()))
            sent = await query.message.reply_text(f"{model_note}{response}", reply_markup=reply_markup)
            user_sessions[user_id]["last_button_message_id"] = sent.message_id
            user_sessions[user_id]["last_button_message_chat_id"] = sent.chat_id

        except Exception as e:
            logger.error(f"Re-analysis error: {e}")
            await query.message.reply_text(f"Error re-analyzing: {e}")
        return
    # ────────────────────────────────────────────────────────────────────────

    # Handle re-analyze (duplicate override)
    if data == "reanalyze":
        text = session.get("duplicate_text", "")
        if not text:
            await query.edit_message_text("Session expired. Send new text.", reply_markup=None)
            return

        await query.edit_message_text("Re-analyzing...", reply_markup=None)

        try:
            loop = asyncio.get_running_loop()
            analysis = await loop.run_in_executor(None, ai_handler.analyze_input, text)
            if "error" in analysis:
                await query.message.reply_text(f"Error: {analysis['error']}")
                return

            # Cache the new result
            if not analysis.get("skipped_ai") and "error" not in analysis:
                cache_handler.put(text, analysis)

            entries = analysis.get("entries", [])
            user_sessions[user_id] = {
                "pending_entries": entries,
                "original_input": text,
            }

            response = ai_handler.format_entries_for_display(analysis)

            # Duplicate check on re-analyzed entries - run in parallel
            dup_notes, dup_page_ids = await _check_duplicates_parallel(entries)
            user_sessions[user_id]["dup_page_ids"] = dup_page_ids

            if dup_notes:
                response = "\n".join(dup_notes) + "\n\n" + response

            reply_markup = _build_save_keyboard(entries, dup_indices=set(dup_page_ids.keys()))
            sent_message = await query.message.reply_text(response, reply_markup=reply_markup)

            user_sessions[user_id]["last_button_message_id"] = sent_message.message_id
            user_sessions[user_id]["last_button_message_chat_id"] = sent_message.chat_id

        except Exception as e:
            logger.error(f"Error in re-analyze: {e}")
            await query.message.reply_text(f"Error: {str(e)}")
        return

    # Handle cancel - clear session, keep content, remove buttons
    if data == "cancel":
        user_sessions[user_id] = {}
        await query.edit_message_text(query.message.text, reply_markup=None)
        await query.message.reply_text("— Cancelled the saving.")
        return

    if not pending_entries:
        await query.edit_message_text("Session expired. Send new text to analyze.", reply_markup=None)
        return

    # Handle category selection (from category buttons)
    if data.startswith("cat_"):
        new_category = data[4:]  # Remove "cat_" prefix
        pending_entries[0]["category"] = new_category
        user_sessions[user_id]["pending_entries"] = pending_entries

        entry = pending_entries[0]
        response = ai_handler._format_single_entry(entry)
        keyboard = [[
            InlineKeyboardButton("Save", callback_data="save_1"),
            InlineKeyboardButton("Cancel", callback_data="cancel")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            f"Category → {new_category}\n{response}",
            reply_markup=reply_markup
        )
        return

    # Handle save buttons
    if data.startswith("save_"):
        if data == "save_all":
            indices = list(range(1, len(pending_entries) + 1))
        else:
            idx = int(data.split("_")[1])
            indices = [idx]

        dup_page_ids = session.get("dup_page_ids", {})
        saved_entries = []
        replaced_entries = []
        failed_count = 0

        for idx in indices:
            entry = pending_entries[idx - 1]
            page_id = dup_page_ids.get(idx - 1)  # 0-indexed

            if page_id:
                result = notion_handler.update_entry_content(page_id, entry)
            else:
                result = notion_handler.save_entry(entry)

            if result["success"]:
                if page_id:
                    replaced_entries.append(entry)
                else:
                    saved_entries.append(entry)
            else:
                failed_count += 1

        # Invalidate cache for saved words so duplicate detection works next time
        original_input = session.get("original_input", "")
        if original_input and (saved_entries or replaced_entries):
            cache_handler.remove(original_input)

        # Clear session
        user_sessions[user_id] = {}

        # Keep content, remove buttons
        await query.edit_message_text(query.message.text, reply_markup=None)

        # Send save confirmation as separate message
        if saved_entries or replaced_entries:
            for entry in replaced_entries:
                chinese = entry.get('chinese', '')
                short_chinese = chinese.split('；')[0].split(';')[0].split('，')[0].split(',')[0].strip()
                await query.message.reply_text(f"— Replaced in Notion: {entry['english']} - {short_chinese} ({entry['category']})")
            for entry in saved_entries:
                chinese = entry.get('chinese', '')
                short_chinese = chinese.split('；')[0].split(';')[0].split('，')[0].split(',')[0].strip()
                await query.message.reply_text(f"— Saved to Notion: {entry['english']} - {short_chinese} ({entry['category']})")
            if failed_count > 0:
                await query.message.reply_text(f"({failed_count} failed)")
        else:
            await query.message.reply_text("— Failed to save.")

        return


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors."""
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.message:
        await update.message.reply_text("An error occurred. Please try again.")


def main():
    """Main function to run the bot."""
    global ai_handler, notion_handler, cache_handler

    # Validate configuration
    if not TELEGRAM_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN not set in .env file")
        return
    if not ANTHROPIC_KEY:
        print("ERROR: ANTHROPIC_API_KEY not set in .env file")
        return
    if not NOTION_KEY:
        print("ERROR: NOTION_API_KEY not set in .env file")
        return

    # Clear any leftover sessions
    user_sessions.clear()

    # Initialize handlers
    ai_handler = AIHandler(ANTHROPIC_KEY, use_cheap_model=USE_CHEAP_MODEL, openai_api_key=OPENAI_KEY)
    if USE_CHEAP_MODEL:
        print("Using Haiku model (cheap mode) - ~90% cost savings")
    notion_handler = NotionHandler(NOTION_KEY, NOTION_DB_ID, additional_database_ids=ADDITIONAL_DB_IDS)
    cache_handler = CacheHandler()
    print(f"Cache loaded: {len(cache_handler.cache)} entries")

    # Test Notion connection on startup
    notion_test = notion_handler.test_connection()
    if notion_test["success"]:
        print(f"Notion connected: {notion_test['database_title']}")
    else:
        print(f"WARNING: Notion connection issue: {notion_test['error']}")

    # Create application
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("test", test_notion))
    application.add_handler(CommandHandler("clear", clear_session))
    application.add_handler(CommandHandler("clearcache", clear_cache))
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Add error handler
    application.add_error_handler(error_handler)

    # Start polling (drop pending updates to avoid processing old queued commands)
    print("Bot is starting...")
    print("Press Ctrl+C to stop")
    application.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
