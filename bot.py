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
    raise ValueError("TELEGRAM_TOKEN is missing (set it in Railway Variables)")


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
LOCK_SECONDS = 120  # ✅ 2 minutes

ROUND_INSTRUCTIONS = (
    "🎮 *Round in progress:*\n"
    "• Anyone can guess\n"
    "• First correct answer wins points\n"
    "• Each correct word = 10 pts\n"
    "• Use /reveal after 2 minutes\n"
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
        await context.bot.pin_chat_message(
            chat_id=chat_id,
            message_id=message_id,
            disable_notification=True,
        )
    except Exception as e:
        logger.warning(f"Pin failed: {e}")


async def unpin_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    try:
        await context.bot.unpin_chat_message(chat_id=chat_id)
    except Exception as e:
        logger.warning(f"Unpin failed: {e}")


# --------------------
# COMMANDS
# --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📋 *Welcome to Pepstein's Redacted Game!*\n\n"
        "🎮 Commands:\n"
        "• /trivia — start a round\n"
        "• /ask [question] — custom question\n"
        "• /score\n"
        "• /leaderboard\n"
        "• /reveal\n"
    )

    msg = await update.message.reply_text(text, parse_mode="Markdown")

    await pin_message(context, update.effective_chat.id, msg.message_id)

    context.chat_data["menu_message_id"] = msg.message_id


async def trivia_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    game = get_active_game(chat_id)
    if game and time.time() - game["asked_at"] < LOCK_SECONDS:
        await update.message.reply_text("⏳ A round is already active.")
        return

    await update.message.reply_text("🧠 Generating trivia...")

    question, answer, keywords = generate_trivia()
    redacted = redact_answer(answer, keywords)

    set_active_game(chat_id, answer, redacted, keywords)

    msg = await update.message.reply_text(
        f"❓ *{escape_md(question)}*\n\n"
        f"{redacted}\n\n"
        f"{ROUND_INSTRUCTIONS}",
        parse_mode="Markdown",
    )

    await pin_message(context, chat_id, msg.message_id)

    context.chat_data["pinned_game_message"] = msg.message_id


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /ask [question]")
        return

    chat_id = update.effective_chat.id
    question = " ".join(context.args)

    await update.message.reply_text("🤔 Thinking...")

    answer, keywords = get_answer(question)
    redacted = redact_answer(answer, keywords)

    set_active_game(chat_id, answer, redacted, keywords)

    msg = await update.message.reply_text(
        f"❓ *{escape_md(question)}*\n\n"
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
        await update.message.reply_text("No active round.")
        return

    if time.time() - game["asked_at"] < LOCK_SECONDS:
        remaining = int(LOCK_SECONDS - (time.time() - game["asked_at"]))
        await update.message.reply_text(f"⏳ Wait {remaining}s more.")
        return

    clear_active_game(chat_id)
    await unpin_message(context, chat_id)

    await update.message.reply_text(
        f"🔓 *Answer:*\n\n{game['original']}",
        parse_mode="Markdown",
    )


async def score_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    score = get_user_score(user.id)

    await update.message.reply_text(f"🏅 Score: {score}")


async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_leaderboard(10)

    if not rows:
        await update.message.reply_text("No scores yet.")
        return

    text = "🏆 Leaderboard\n\n"
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

    if remaining:
        set_active_game(chat_id, game["original"], game["redacted"], remaining)

        await update.message.reply_text(
            f"✅ {user.first_name} got {', '.join(matched)} (+{points})"
        )
    else:
        clear_active_game(chat_id)
        await unpin_message(context, chat_id)

        await update.message.reply_text(
            f"🎉 {user.first_name} completed it!\n\n{game['original']}"
        )


# --------------------
# MAIN
# --------------------
def main():
    init_db()

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
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
