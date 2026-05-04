import os
import logging
import time
import random
import difflib
import asyncio
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

from redactor import get_answer, generate_trivia, redact_answer


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
MAX_KEYWORDS = 8

streaks = defaultdict(int)
chat_difficulty = defaultdict(int)


# --------------------
# ROUND UI BLOCK
# --------------------
ROUND_BLOCK = (
    "🧠 *ROUND ACTIVE*\n\n"
    "• Guess the missing words\n"
    "• Typos are allowed\n"
    "• Partial names count\n"
    "• First correct match wins points\n"
    "• Use /reveal to end round\n"
)


# --------------------
# TELEGRAM HELPERS
# --------------------
async def pin_message(context, chat_id, message_id):
    try:
        await context.bot.pin_chat_message(
            chat_id=chat_id,
            message_id=message_id,
            disable_notification=True
        )
    except Exception:
        pass


async def unpin_message(context, chat_id):
    try:
        await context.bot.unpin_chat_message(chat_id=chat_id)
    except Exception:
        pass


# --------------------
# TIMER ENGINE
# --------------------
async def start_round_timer(context, chat_id, message_id, duration=120):
    start_time = time.time()

    try:
        while True:
            game = get_active_game(chat_id)
            if not game:
                return

            elapsed = int(time.time() - start_time)
            remaining = duration - elapsed

            if remaining <= 0:
                return

            mins = remaining // 60
            secs = remaining % 60

            timer_line = f"\n\n⏳ {mins:02d}:{secs:02d}"

            base_text = context.chat_data.get("last_round_text")
            if not base_text:
                return

            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=base_text + timer_line,
                parse_mode="Markdown",
            )

            await asyncio.sleep(15)

    except Exception:
        pass


# --------------------
# START
# --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📁 *PEPSTEIN ARCHIVE SYSTEM ONLINE*\n\n"
        "🧠 WHAT THIS IS:\n"
        "You are entering a chaotic trivia reconstruction system where answers are redacted but always contain clues.\n"
        "Think: internet conspiracy energy meets word puzzle game.\n\n"
        "🎮 HOW IT WORKS:\n"
        "• /trivia — starts a timed round (2 minutes)\n"
        "• /ask — new round based on your own question (2 minutes)\n"
        "• /reveal — ends the round and shows full answer\n"
        "• /rules — full breakdown of mechanics\n"
        "• /score — shows your current streak score\n"
        "• /leaderboard — top players in the archive\n\n"
        "⚠️ GAME RULES:\n"
        "• Minor typos allowed\n"
        "• Partial names count\n"
        "• Clues always exist in answers\n"
    )

    msg = await update.message.reply_text(text, parse_mode="Markdown")
    context.chat_data["menu_message_id"] = msg.message_id


# --------------------
# RULES
# --------------------
async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📜 *PEPSTEIN ARCHIVE — FULL RULESET*\n\n"
        "🎯 OBJECTIVE:\n"
        "Guess the missing words in redacted prompts.\n\n"
        "🧠 COMMANDS:\n"
        "• /trivia — random timed round\n"
        "• /ask — custom round based on your question\n"
        "• /reveal — ends current round\n"
        "• /score — shows score\n"
        "• /leaderboard — top players\n\n"
        "🏆 SCORING:\n"
        "• +10 per correct word\n"
        "• streak multipliers apply\n"
    )

    await update.message.reply_text(text, parse_mode="Markdown")


# --------------------
# GAME FUNCTIONS
# --------------------
def normalize(text: str) -> str:
    return text.lower().strip()


def similarity(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


def fuzzy_match(guess, keyword):
    guess = normalize(guess)
    keyword = normalize(keyword)

    fillers = {"the", "a", "an"}

    guess_tokens = [g for g in guess.split() if g not in fillers]
    keyword_tokens = [k for k in keyword.split() if k not in fillers]

    guess_clean = " ".join(guess_tokens)
    keyword_clean = " ".join(keyword_tokens)

    if keyword_clean in guess_clean or guess_clean in keyword_clean:
        return True

    return similarity(guess_clean, keyword_clean) > 0.82


def check_guess_flexible(guess, keywords):
    matched = []

    for k in keywords:
        parts = k.split()

        if any(fuzzy_match(guess, p) for p in parts):
            matched.append(k)
        elif fuzzy_match(guess, k):
            matched.append(k)

    return list(set(matched))


# --------------------
# TRIVIA
# --------------------
async def trivia_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    game = get_active_game(chat_id)
    if game and time.time() - game["asked_at"] < LOCK_SECONDS:
        await update.message.reply_text("⏳ round active")
        return

    await update.message.reply_text("🧠 generating trivia...")

    question, answer, keywords = generate_trivia()

    redacted = redact_answer(answer, keywords)

    set_active_game(chat_id, answer, redacted, keywords)

    msg = await update.message.reply_text(
        "📄 *ROUND STARTED*\n\n"
        f"🧠 {question}\n\n"
        f"🧾 {redacted}\n\n"
        f"{ROUND_BLOCK}",
        parse_mode="Markdown",
    )

    context.chat_data["last_round_text"] = msg.text

    await pin_message(context, chat_id, msg.message_id)
    context.chat_data["pinned_game_message"] = msg.message_id

    asyncio.create_task(
        start_round_timer(context, chat_id, msg.message_id, LOCK_SECONDS)
    )


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

    redacted = redact_answer(answer, keywords)

    set_active_game(chat_id, answer, redacted, keywords)

    msg = await update.message.reply_text(
        "📄 *CUSTOM ROUND*\n\n"
        f"🧠 {question}\n\n"
        f"🧾 {redacted}\n\n"
        f"{ROUND_BLOCK}",
        parse_mode="Markdown",
    )

    context.chat_data["last_round_text"] = msg.text

    await pin_message(context, chat_id, msg.message_id)
    context.chat_data["pinned_game_message"] = msg.message_id

    asyncio.create_task(
        start_round_timer(context, chat_id, msg.message_id, LOCK_SECONDS)
    )


# --------------------
# REVEAL
# --------------------
async def reveal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = get_active_game(chat_id)

    if not game:
        await update.message.reply_text("no active round")
        return

    clear_active_game(chat_id)
    await unpin_message(context, chat_id)

    await update.message.reply_text(
        f"🔓 ANSWER:\n\n{game['original']}",
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

    user = update.effective_user
    guess = update.message.text

    matched = check_guess_flexible(guess, game["keywords"])

    if not matched:
        return

    points = len(matched) * 10
    add_points(user.id, user.username or user.first_name, points)

    remaining = [k for k in game["keywords"] if k not in matched]

    pinned_id = context.chat_data.get("pinned_game_message")

    if remaining:
        new_redacted = redact_answer(game["original"], remaining)
        set_active_game(chat_id, game["original"], new_redacted, remaining)

        await update.message.reply_text(
            f"✅ {user.first_name} got {', '.join(matched)} (+{points})"
        )

    else:
        clear_active_game(chat_id)

        if pinned_id:
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
    app.add_handler(CommandHandler("rules", rules))
    app.add_handler(CommandHandler("trivia", trivia_command))
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CommandHandler("reveal", reveal_command))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
