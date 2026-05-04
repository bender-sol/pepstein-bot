import os
import logging
import time
from collections import defaultdict

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
LOCK_SECONDS = 120
MIN_KEYWORDS = 3

streaks = defaultdict(int)

ROUND_INSTRUCTIONS = (
    "🧠 *PEPSTEIN ARCHIVE ACTIVE ROUND*\n\n"
    "• Decode the redacted chaos\n"
    "• Restore missing words\n"
    "• First correct answer wins points\n"
    "• Streaks = bonus multipliers\n"
    "• This round expires in 2 minutes unless solved\n"
)


# --------------------
# HELPERS
# --------------------
def normalize(text: str) -> str:
    return text.lower().strip()


def escape_md(text: str) -> str:
    for ch in ["_", "*", "[", "]", "`"]:
        text = text.replace(ch, f"\\{ch}")
    return text


def get_multiplier(streak: int) -> float:
    if streak >= 10:
        return 2.5
    if streak >= 5:
        return 2.0
    if streak >= 3:
        return 1.5
    return 1.0


async def pin_message(context, chat_id, message_id):
    try:
        await context.bot.pin_chat_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        logger.warning(f"Pin failed: {e}")


async def unpin_message(context, chat_id):
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
    except Exception:
        pass


# --------------------
# START
# --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📁 *PEPSTEIN ARCHIVE SYSTEM ONLINE*\n\n"
        "A chaotic word-reconstruction game where redactions appear for no reason and your job is to recover them.\n\n"
        "🎮 COMMANDS:\n"
        "• /trivia — start a random round (2 min timer)\n"
        "• /ask [question] — custom round (2 min timer)\n"
        "• /reveal — reveal answer (after timer or early if allowed)\n"
        "• /rules — full instructions\n"
        "• /score — your points\n"
        "• /leaderboard — top players\n\n"
        "⚡ Gameplay:\n"
        "• Guess missing words in chat\n"
        "• Earn +10 points per correct word\n"
        "• Streaks increase multipliers\n"
    )

    msg = await update.message.reply_text(text, parse_mode="Markdown")

    await pin_message(context, update.effective_chat.id, msg.message_id)
    context.chat_data["menu_message_id"] = msg.message_id


# --------------------
# RULES
# --------------------
async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📜 *FULL RULES*\n\n"
        "🎯 Objective:\n"
        "Guess the missing redacted words in each prompt.\n\n"
        "⏱ Timers:\n"
        "• /trivia = 2 minute round\n"
        "• /ask = 2 minute round\n"
        "• /reveal = unlocks answer after timer\n\n"
        "🏆 Scoring:\n"
        "• +10 points per correct word\n"
        "• streak multiplier applies (up to 2.5x)\n\n"
        "🔥 Streaks:\n"
        "• consecutive correct answers increase multiplier\n"
        "• missing a round resets streak\n\n"
        "🧠 Tip:\n"
        "Answers are often proper nouns, names, or key entities"
    )

    await update.message.reply_text(text, parse_mode="Markdown")


# --------------------
# TRIVIA
# --------------------
async def trivia_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    game = get_active_game(chat_id)
    if game and time.time() - game["asked_at"] < LOCK_SECONDS:
        await update.message.reply_text("⏳ Round already active (2 min timer running).")
        return

    await update.message.reply_text("🧠 generating chaos...")

    question, answer, keywords = generate_trivia()
    keywords = list(set(keywords))
    redacted = redact_answer(answer, keywords)

    set_active_game(chat_id, answer, redacted, keywords)

    msg = await update.message.reply_text(
        f"📄 *ROUND STARTED*\n\n"
        f"{escape_md(question)}\n\n"
        f"{redacted}\n\n"
        f"{ROUND_INSTRUCTIONS}",
        parse_mode="Markdown",
    )

    await pin_message(context, chat_id, msg.message_id)
    context.chat_data["pinned_game_message"] = msg.message_id


# --------------------
# ASK
# --------------------
async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /ask [question]")
        return

    chat_id = update.effective_chat.id
    question = " ".join(context.args)

    await update.message.reply_text("🧠 thinking...")

    answer, keywords = get_answer(question)
    keywords = list(set(keywords))
    redacted = redact_answer(answer, keywords)

    set_active_game(chat_id, answer, redacted, keywords)

    msg = await update.message.reply_text(
        f"📄 *CUSTOM ROUND*\n\n"
        f"{escape_md(question)}\n\n"
        f"{redacted}\n\n"
        f"{ROUND_INSTRUCTIONS}",
        parse_mode="Markdown",
    )

    await pin_message(context, chat_id, msg.message_id)
    context.chat_data["pinned_game_message"] = msg.message_id


# --------------------
# REVEAL
# --------------------
async def reveal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = get_active_game(chat_id)

    if not game:
        await update.message.reply_text("No active round.")
        return

    clear_active_game(chat_id)
    await unpin_message(context, chat_id)

    await update.message.reply_text(
        f"🔓 *FULL ANSWER:*\n\n{game['original']}",
        parse_mode="Markdown",
    )


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

    guess = normalize(update.message.text)

    matched = [k for k in game["keywords"] if normalize(k) in guess]

    if not matched:
        return

    user = update.effective_user
    uid = user.id

    streaks[uid] += 1
    mult = get_multiplier(streaks[uid])

    base_points = len(matched) * 10
    points = int(base_points * mult)

    add_points(uid, user.username or user.first_name, points)

    remaining = [k for k in game["keywords"] if normalize(k) not in [normalize(m) for m in matched]]

    pinned_id = context.chat_data.get("pinned_game_message")

    if remaining:
        new_redacted = redact_answer(game["original"], remaining)

        set_active_game(chat_id, game["original"], new_redacted, remaining)

        if pinned_id:
            await edit_message(
                context,
                chat_id,
                pinned_id,
                f"📄 UPDATED ROUND\n\n{new_redacted}\n\n{ROUND_INSTRUCTIONS}",
            )

        await update.message.reply_text(
            f"✅ {user.first_name} got {', '.join(matched)} (+{points}) | streak {streaks[uid]}x"
        )

    else:
        clear_active_game(chat_id)
        await unpin_message(context, chat_id)
        streaks[uid] = 0

        await update.message.reply_text(
            f"🎉 {user.first_name} cleared the round!\n\n{game['original']}"
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

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Pepstein system running...")
    app.run_polling()


if __name__ == "__main__":
    main()
