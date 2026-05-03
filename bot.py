import os
import logging
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

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

ROUND_INSTRUCTIONS = (
    "🎮 *Round in progress:*\n"
    "_• Anyone in this chat can guess — first correct answer wins the points\n"
    "• Each redacted word is worth 10 points\n"
    "• Type your guess as a normal message\n"
    "• Use /reveal after 5 minutes if nobody can guess\n"
    "• Use /leaderboard to see who's winning_"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *Pepstein's Fill in the Redacted!*\n\n"
        "The bot that knows everything about everyone — "
        "but redacts the parts that would get it suicided in a jail cell.\n\n"
        "🎮 *How to play:*\n\n"
        "▶️ *Starting a round:*\n"
        "• /trivia — Pepstein picks an Epstein-adjacent question automatically\n"
        "• /ask [question] — Ask your own question on any topic\n\n"
        "🔍 *During a round:*\n"
        "• Pepstein answers but redacts the important parts\n"
        "• Type any message to guess a redacted word\n"
        "• First correct guess wins 10 points per word\n"
        "• Anyone in the chat can guess — not just who asked\n"
        "• Use /reveal after 5 minutes to give up and see the answer\n\n"
        "📊 *Scoring:*\n"
        "• /score — Check your own points\n"
        "• /leaderboard — See the top players\n"
        "• /help — Show this message again",
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def trivia_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    await update.message.reply_text("🕵️ Consulting the manifest...")

    question, answer, keywords = generate_trivia()
    redacted = redact_answer(answer, keywords)

    set_active_game(chat_id, answer, redacted, keywords)

    await update.message.reply_text(
        f"📋 *Pepstein's Fill in the Redacted!*\n\n"
        f"❓ *{question}*\n\n"
        f"{redacted}\n\n"
        f"{ROUND_INSTRUCTIONS}",
        parse_mode="Markdown"
    )

async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: /ask [your question]\nExample: /ask What is the speed of light?"
        )
        return

    question = " ".join(context.args)
    chat_id = update.effective_chat.id

    await update.message.reply_text("🤔 Consulting my vast knowledge...")

    answer, keywords = get_answer(question)
    redacted = redact_answer(answer, keywords)

    set_active_game(chat_id, answer, redacted, keywords)

    await update.message.reply_text(
        f"📋 *Pepstein's Fill in the Redacted!*\n\n"
        f"❓ *{question}*\n\n"
        f"{redacted}\n\n"
        f"{ROUND_INSTRUCTIONS}",
        parse_mode="Markdown"
    )

async def reveal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import time
    chat_id = update.effective_chat.id
    game = get_active_game(chat_id)

    if not game:
        await update.message.reply_text(
            "There's no active question right now.\n"
            "Use /trivia to start a round or /ask to ask your own question!"
        )
        return

    elapsed = time.time() - game["asked_at"]
    if elapsed < 300:
        seconds_left = int(300 - elapsed)
        await update.message.reply_text(
            f"⏳ Too soon! You must wait *{seconds_left} seconds* before revealing.\n"
            f"Keep guessing!",
            parse_mode="Markdown"
        )
        return

    clear_active_game(chat_id)
    await update.message.reply_text(
        f"🔓 *Full Answer:*\n\n{game['original']}\n\n"
        f"The redacted words were: *{', '.join(game['keywords'])}*\n\n"
        f"Use /trivia to start a new round!",
        parse_mode="Markdown"
    )

async def score_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    points = get_user_score(user.id)
    name = user.first_name or user.username or "You"
    await update.message.reply_text(
        f"🏅 *{name}'s Score:* {points} point{'s' if points != 1 else ''}",
        parse_mode="Markdown"
    )

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_leaderboard(10)
    if not rows:
        await update.message.reply_text("No scores yet! Use /trivia to start playing.")
        return

    lines = ["🏆 *Pepstein's Fill in the Redacted — Leaderboard*\n"]
    medals = ["🥇", "🥈", "🥉"]
    for i, (username, points) in enumerate(rows):
        medal = medals[i] if i < 3 else f"{i+1}."
        lines.append(f"{medal} {username} — {points} pts")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.is_bot:
        return

    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    if text.startswith("/"):
        return

    game = get_active_game(chat_id)
    if not game:
        return

    matched = check_guess(text, game["keywords"])

    if matched:
        user = update.effective_user
        username = user.username or user.first_name or "Someone"
        points_earned = len(matched) * 10

        add_points(user.id, username, points_earned)

        remaining = [k for k in game["keywords"] if k not in matched]

        if remaining:
            remaining_redacted = redact_answer(game["original"], remaining)
            set_active_game(chat_id, game["original"], remaining_redacted, remaining)

            await update.message.reply_text(
                f"✅ *{username}* guessed: _{', '.join(matched)}_\n"
                f"+{points_earned} points!\n\n"
                f"Still missing {len(remaining)} word(s):\n{remaining_redacted}",
                parse_mode="Markdown"
            )
        else:
            clear_active_game(chat_id)
            total = get_user_score(user.id)
            await update.message.reply_text(
                f"🎉 *{username}* found the last redacted word: _{', '.join(matched)}_\n"
                f"+{points_earned} points! Round over!\n\n"
                f"Full answer: _{game['original']}_\n\n"
                f"Your total: *{total} pts*\n"
                f"Use /trivia to start a new round!",
                parse_mode="Markdown"
            )

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

    logger.info("Pepstein is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
