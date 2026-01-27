"""
Telegram Vocabulary Learning Bot
Main entry point - handles Telegram interactions
"""
import os
import logging
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from ai_handler import AIHandler
from notion_handler import NotionHandler

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
NOTION_KEY = os.getenv("NOTION_API_KEY")
NOTION_DB_ID = os.getenv("NOTION_DATABASE_ID")
ALLOWED_USERS = os.getenv("ALLOWED_USER_IDS", "").split(",")
ALLOWED_USERS = [uid.strip() for uid in ALLOWED_USERS if uid.strip()]

ai_handler = None
notion_handler = None

# Store user session data (pending entries to save)
user_sessions = {}


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
    await update.message.reply_text(welcome_message)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    if not is_user_allowed(update.effective_user.id):
        return

    help_text = """
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
固定词组, 口语, 新闻, 职场, 学术词汇, 写作, 情绪, 其他
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


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages."""
    logger.info(f"Received message: {update.message.text} from user {update.effective_user.id}")
    user_id = update.effective_user.id

    if not is_user_allowed(user_id):
        logger.info(f"User {user_id} not allowed. ALLOWED_USERS: {ALLOWED_USERS}")
        await update.message.reply_text("Sorry, this bot is private.")
        return

    text = update.message.text.strip()

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

        # Anything else = edit request (let AI handle it)
        await handle_edit_request(update, context, text)
        return

    # New input - analyze it
    await update.message.reply_text("Analyzing...")

    try:
        analysis = ai_handler.analyze_input(text)

        if "error" in analysis:
            await update.message.reply_text(f"Error: {analysis['error']}")
            return

        # Store pending entries in session
        user_sessions[user_id] = {
            "pending_entries": analysis.get("entries", []),
            "original_input": text
        }

        # Format and send response
        response = ai_handler.format_entries_for_display(analysis)
        entries = analysis.get("entries", [])

        # Create inline keyboard buttons
        keyboard = []
        if len(entries) == 1:
            # Single entry - Save and Cancel buttons
            keyboard.append([
                InlineKeyboardButton("Save", callback_data="save_1"),
                InlineKeyboardButton("Cancel", callback_data="cancel")
            ])
        else:
            # Multiple entries - show numbered save buttons
            row = []
            for i in range(len(entries)):
                row.append(InlineKeyboardButton(f"Save {i+1}", callback_data=f"save_{i+1}"))
                if len(row) == 3:  # Max 3 buttons per row
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
            keyboard.append([
                InlineKeyboardButton("Save All", callback_data="save_all"),
                InlineKeyboardButton("Cancel", callback_data="cancel")
            ])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(response, reply_markup=reply_markup)

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


async def handle_edit_request(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    """Handle edit/modification request for pending entry."""
    user_id = update.effective_user.id
    session = user_sessions.get(user_id, {})
    pending_entries = session.get("pending_entries", [])

    if not pending_entries:
        await update.message.reply_text("No pending entries to modify.")
        return

    # Check if it's a simple category change with category name in text
    valid_categories = ["固定词组", "口语", "新闻", "职场", "学术词汇", "写作", "情绪", "其他"]
    for cat in valid_categories:
        if cat in text:
            pending_entries[0]["category"] = cat
            user_sessions[user_id]["pending_entries"] = pending_entries
            entry = pending_entries[0]
            response = ai_handler._format_single_entry(entry)
            keyboard = [[
                InlineKeyboardButton("Save", callback_data="save_1"),
                InlineKeyboardButton("Cancel", callback_data="cancel")
            ]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"Category → {cat}\n{response}\n\n(Type to edit more)",
                reply_markup=reply_markup
            )
            return

    # Use AI to modify the entry based on user request
    await update.message.reply_text("Modifying...")

    entry = pending_entries[0]
    result = ai_handler.modify_entry(entry, text)

    if result["success"]:
        pending_entries[0] = result["entry"]
        user_sessions[user_id]["pending_entries"] = pending_entries

        response = ai_handler._format_single_entry(result["entry"])
        keyboard = [[
            InlineKeyboardButton("Save", callback_data="save_1"),
            InlineKeyboardButton("Cancel", callback_data="cancel")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"Updated!\n{response}\n\n(Type to edit more)",
            reply_markup=reply_markup
        )
    else:
        # Show buttons so user can escape the loop
        keyboard = [[
            InlineKeyboardButton("Save", callback_data="save_1"),
            InlineKeyboardButton("Start New", callback_data="cancel")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Couldn't understand that. Try again, Save current entry, or Start New.",
            reply_markup=reply_markup
        )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard button presses."""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data
    session = user_sessions.get(user_id, {})
    pending_entries = session.get("pending_entries", [])

    if not pending_entries:
        await query.edit_message_text("Session expired. Send new text to analyze.")
        return

    # Handle cancel - clear session, keep content, remove buttons
    if data == "cancel":
        user_sessions[user_id] = {}
        original_text = query.message.text
        # Remove any edit hints and show cancelled status
        new_text = original_text.replace("\n\n(Type to edit more)", "")
        await query.edit_message_text(new_text)
        await query.message.reply_text("— Cancelled the saving.")
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
            f"Category → {new_category}\n{response}\n\n(Type to edit more)",
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

        saved_entries = []
        failed_count = 0

        for idx in indices:
            entry = pending_entries[idx - 1]
            result = notion_handler.save_entry(entry)

            if result["success"]:
                saved_entries.append(entry)
            else:
                failed_count += 1

        # Clear session
        user_sessions[user_id] = {}

        # Keep content, remove buttons
        original_text = query.message.text
        new_text = original_text.replace("\n\n(Type to edit more)", "")
        await query.edit_message_text(new_text)

        # Send save confirmation as separate message
        if saved_entries:
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
    global ai_handler, notion_handler

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
    ai_handler = AIHandler(ANTHROPIC_KEY)
    notion_handler = NotionHandler(NOTION_KEY, NOTION_DB_ID)

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
    application.add_handler(CallbackQueryHandler(handle_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Add error handler
    application.add_error_handler(error_handler)

    # Start polling
    print("Bot is starting...")
    print("Press Ctrl+C to stop")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
