import os
import logging
import time
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
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

# --- Load env ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN is not set in .env")

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Constants ---
ROUND_INSTRUCTIONS = (
    "🎮 *Round in progress:*\n"
    "_• Anyone in this chat can guess — first correct answer wins the points\n"
    "• Each redacted word is worth 10 points\n"
    "• Type your guess as a normal message\n"
    "• Use /reveal after 2.5 minutes if nobody can guess\n"
    "• Use /leaderboard to see who's winning_"
)

LOCK_SECONDS = 150  # 2.5 minutes


# --- Helpers ---
def _escape_md(text: str) -> str:
    """Basic Markdown escaping (Telegram Markdown v1 safe-ish)."""
    for ch in ['_', '*', '[', '`']:
        text = text.replace(ch, f'\\{ch}')
    return text


# --- Commands ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *Welcome to Pepstein's Fill In The Redacted Game!*\n\n"
        "🎮 *How to play:*\n\n"
        "▶️ *Starting a round:*\n"
        "• /trivia — random question\n"
        "• /ask [question] — ask your own\n\n"
        "🔍 *During a round:*\n"
        "• Guess missing words\n"
        "• First correct guess earns points\n"
        "• /reveal after 2.5 minutes\n\n"
        "📊 *Commands:*\n"
        "• /score\n"
        "• /leaderboard\n"
        "• /help",
        parse_mode="Markdown"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def trivia_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = get_active_game(chat_id)

    if game:
        elapsed = time.time() - game["asked_at"]
        if elapsed < LOCK_SECONDS:
            seconds_left = int(LOCK_SECONDS - elapsed)
            await update.message.reply_text(
                f"🔒 A round is already in progress.\n"
                f"{seconds_left}s remaining.\n\n"
                f"{game['redacted']}",
                parse_mode="Markdown"
            )
            return

    await update.message.reply_text("🕵️ Generating trivia...")

    try:
        question, answer, keywords = generate_trivia()
    except Exception as e:
        logger.error(e)
        await update.message.reply_text("Failed to generate trivia.")
        return

    redacted = redact_answer(answer, keywords)
    set_active_game(chat_id, answer, redacted, keywords)

    await update.message.reply_text(
        f"❓ *{_escape_md(question)}*\n\n"
        f"{redacted}\n\n"
        f"{ROUND_INSTRUCTIONS}",
        parse_mode="Markdown"
    )


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: /ask [question]\nExample: /ask What is gravity?"
        )
        return

    chat_id = update.effective_chat.id
    game = get_active_game(chat_id)

    if game:
        elapsed = time.time() - game["asked_at"]
        if elapsed < LOCK_SECONDS:
            seconds_left = int(LOCK_SECONDS - elapsed)
            await update.message.reply_text(
                f"🔒 Round in progress.\n{seconds_left}s remaining."
            )
            return

    question = " ".join(context.args)
    await update.message.reply_text("🤔 Thinking...")

    try:
        answer, keywords = get_answer(question)
    except Exception as e:
        logger.error(e)
        await update.message.reply_text("Failed to generate answer.")
        return

    redacted = redact_answer(answer, keywords)
    set_active_game(chat_id, answer, redacted, keywords)

    await update.message.reply_text(
        f"❓ *{_escape_md(question)}*\n\n"
        f"{redacted}\n\n"
        f"{ROUND_INSTRUCTIONS}",
        parse_mode="Markdown"
    )


async def reveal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = get_active_game(chat_id)

    if not game:
        await update.message.reply_text("No active round.")
        return

    elapsed = time.time() - game["asked_at"]
    if elapsed < LOCK_SECONDS:
        seconds_left = int(LOCK_SECONDS - elapsed)
        await update.message.reply_text(f"⏳ Wait {seconds_left}s more.")
        return

    clear_active_game(chat_id)

    await update.message.reply_text(
        f"🔓 *Answer:*\n\n"
        f"{game['original']}\n\n"
        f"Words: *{', '.join(game['keywords'])}*",
        parse_mode="Markdown"
    )


async def score_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    points = get_user_score(user.id)
    name = _escape_md(user.first_name or user.username or "You")

    await update.message.reply_text(
        f"🏅 *{name}:* {points} pts",
        parse_mode="Markdown"
    )


async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_leaderboard(10)

    if not rows:
        await update.message.reply_text("No scores yet.")
        return

    lines = ["🏆 *Leaderboard*\n"]

    for i, (username, points) in enumerate(rows, start=1):
        name = _escape_md(username or "Unknown")
        lines.append(f"{i}. {name} — {points}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# --- Message handler ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    if update.effective_user.is_bot:
        return

    text = update.message.text.strip()

    if text.startswith("/"):
        return

    chat_id = update.effective_chat.id
    game = get_active_game(chat_id)

    if not game:
        return

    matched = check_guess(text, game["keywords"])

    if not matched:
        return

    user = update.effective_user
    username = _escape_md(user.username or user.first_name or "Someone")
    points_earned = len(matched) * 10

    add_points(user.id, user.username or user.first_name, points_earned)

    remaining = [k for k in game["keywords"] if k not in matched]

    if remaining:
        new_redacted = redact_answer(game["original"], remaining)
        set_active_game(chat_id, game["original"], new_redacted, remaining)

        await update.message.reply_text(
            f"✅ *{username}* got: {', '.join(matched)}\n"
            f"+{points_earned} pts\n\n"
            f"{new_redacted}",
            parse_mode="Markdown"
        )
    else:
        clear_active_game(chat_id)
        total = get_user_score(user.id)

        await update.message.reply_text(
            f"🎉 *{username}* finished it!\n"
            f"+{points_earned} pts\n\n"
            f"{game['original']}\n\n"
            f"Total: *{total}*",
            parse_mode="Markdown"
        )


# --- Main ---
def main():
    init_db()

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
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
