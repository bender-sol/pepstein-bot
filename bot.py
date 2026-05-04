import os
import logging
import time

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from dotenv import load_dotenv

from database import (
    init_db,
    add_points,
    get_leaderboard,
    get_user_score,
    set_active_game,
    get_active_game,
    clear_active_game,
)

from redactor import get_answer, generate_trivia, redact_answer, check_guess


# --------------------
# ENV
# --------------------
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN is missing (Railway Variables)")


# --------------------
# LOGGING
# --------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# --------------------
# GAME SETTINGS
# --------------------
LOCK_SECONDS = 120  # 2 minutes

ROUND_INSTRUCTIONS = (
    "🕵️ *FIELD BRIEFING:*\n"
    "• Decode the redacted intelligence fragment\n"
    "• First correct reconstruction earns points\n"
    "• Each recovered term = 10 points\n"
    "• Use /reveal after 2 minutes if stalled\n"
)

FULL_RULES = (
    "📁 *CLASSIFIED RULES DOSSIER*\n\n"
    "🧠 Premise:\n"
    "You are analyzing redacted intelligence fragments from a fictional archive of sealed communications, financial networks, and surveillance reports.\n\n"
    "🎯 Objective:\n"
    "Reconstruct missing terms hidden in redacted documents.\n\n"
    "🏆 Scoring:\n"
    "• Each correct term = 10 points\n"
    "• First correct match locks the point\n\n"
    "⏱ Protocol Timing:\n"
    f"• Each file remains active for {LOCK_SECONDS} seconds\n"
    "• After timeout, /reveal exposes full file\n\n"
    "🧾 Commands:\n"
    "• /trivia — load a random classified file\n"
    "• /ask [query] — request a custom intelligence prompt\n"
    "• /score — view your clearance score\n"
    "• /leaderboard — top analysts\n"
    "• /reveal — decrypt full document\n"
)


# --------------------
# HELPERS
# --------------------
def escape_md(text: str) -> str:
    for ch in ["_", "*", "[", "]", "`"]:
        text = text.replace(ch, f"\\{ch}")
    return text


async def pin_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
    try:
        await context.bot.pin_chat_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.warning(f"Pin failed: {e}")


async def unpin_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    try:
        await context.bot.unpin_chat_message(chat_id=chat_id)
    except Exception as e:
        logger.warning(f"Unpin failed: {e}")


async def edit_message(context, chat_id, message_id, text):
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode="Markdown",
        )
    except Exception as e:
        logger.warning(f"Edit failed: {e}")


# --------------------
# COMMANDS
# --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = (
        "📁 *REDAC-TD ARCHIVE ACCESS GRANTED*\n\n"
        "You are entering a simulated intelligence reconstruction system.\n\n"
        "Files originate from a fictionalized archive of:\n"
        "• sealed financial records\n"
        "• encrypted communications\n"
        "• institutional reports\n"
        "• redacted public disclosures\n\n"
        "🎮 Mission:\n"
        "Restore missing terms before the document auto-decrypts.\n\n"
        "📌 Type /rules for full classification briefing."
    )

    msg = await update.message.reply_text(text, parse_mode="Markdown")

    await pin_message(context, update.effective_chat.id, msg.message_id)
    context.chat_data["menu_message_id"] = msg.message_id


async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(FULL_RULES, parse_mode="Markdown")


async def trivia_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    game = get_active_game(chat_id)
    if game and time.time() - game["asked_at"] < LOCK_SECONDS:
        await update.message.reply_text("⏳ File already active.")
        return

    await update.message.reply_text("🧠 Loading classified file...")

    question, answer, keywords = generate_trivia()
    redacted = redact_answer(answer, keywords)

    set_active_game(chat_id, answer, redacted, keywords)

    msg = await update.message.reply_text(
        f"📄 *FILE: {escape_md(question)}*\n\n"
        f"{redacted}\n\n"
        f"{ROUND_INSTRUCTIONS}",
        parse_mode="Markdown",
    )

    await pin_message(context, chat_id, msg.message_id)
    context.chat_data["pinned_game_message"] = msg.message_id


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /ask [query]")
        return

    chat_id = update.effective_chat.id
    question = " ".join(context.args)

    await update.message.reply_text("🧠 Querying archive...")

    answer, keywords = get_answer(question)
    redacted = redact_answer(answer, keywords)

    set_active_game(chat_id, answer, redacted, keywords)

    msg = await update.message.reply_text(
        f"📄 *FILE: {escape_md(question)}*\n\n"
        f"{redacted}\n\n"
        f"{ROUND_INSTRUCTIONS}",
        parse_mode="Markdown",
    )

    await pin_message(context, chat_id, msg.message_id)
    context.chat_data["pinned_game_message"] = msg.message_id


async def reveal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = get_active_game(chat_id)

    if not game:
        await update.message.reply_text("No active file.")
        return

    if time.time() - game["asked_at"] < LOCK_SECONDS:
        remaining = int(LOCK_SECONDS - (time.time() - game["asked_at"]))
        await update.message.reply_text(f"⏳ Decryption in {remaining}s.")
        return

    clear_active_game(chat_id)
    await unpin_message(context, chat_id)

    await update.message.reply_text(
        f"🔓 *FULL FILE:*\n\n{game['original']}",
        parse_mode="Markdown",
    )


async def score_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    score = get_user_score(user.id)

    await update.message.reply_text(f"🏅 Clearance Score: {score}")


async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_leaderboard(10)

    text = "🏆 Analyst Leaderboard\n\n"
    for i, (name, score) in enumerate(rows, 1):
        text += f"{i}. {name} — {score}\n"

    await update.message.reply_text(text)


# --------------------
# MESSAGE HANDLER
# --------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message or not update.message.text:
        return

    if update.effective_user.is_bot:
        return

    chat_id = update.effective_chat.id
    game = get_active_game(chat_id)

    if not game:
        return

    guess = update.message.text
    matched = check_guess(guess, game["keywords"])

    if not matched:
        return

    user = update.effective_user
    points = len(matched) * 10

    add_points(user.id, user.username or user.first_name, points)

    remaining = [k for k in game["keywords"] if k not in matched]
    pinned_id = context.chat_data.get("pinned_game_message")

    if remaining:
        new_redacted = redact_answer(game["original"], remaining)

        set_active_game(chat_id, game["original"], new_redacted, remaining)

        if pinned_id:
            await edit_message(
                context,
                chat_id,
                pinned_id,
                f"📄 *UPDATED FILE*\n\n{new_redacted}\n\n{ROUND_INSTRUCTIONS}",
            )

        await update.message.reply_text(
            f"✅ {user.first_name} recovered: {', '.join(matched)} (+{points})"
        )

    else:
        clear_active_game(chat_id)
        await unpin_message(context, chat_id)

        if pinned_id:
            await edit_message(
                context,
                chat_id,
                pinned_id,
                f"📄 *FILE FULLY DECLASSIFIED*\n\n{game['original']}",
            )

        await update.message.reply_text(
            f"🧾 {user.first_name} completed reconstruction.\n\n{game['original']}"
        )


# --------------------
# MAIN
# --------------------
def main():
    init_db()

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("rules", rules))
    app.add_handler(CommandHandler("trivia", trivia_command))
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CommandHandler("reveal", reveal_command))
    app.add_handler(CommandHandler("score", score_command))
    app.add_handler(CommandHandler("leaderboard", leaderboard_command))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
