import os
import logging
import time
import random
import difflib
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
    format="%(asctime)s - %(name)s - %(levelname)s - message)s",
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
# HELPERS
# --------------------
def normalize(text: str) -> str:
    return text.lower().strip()


def escape_md(text: str) -> str:
    for ch in ["_", "*", "[", "]", "`"]:
        text = text.replace(ch, f"\\{ch}")
    return text


# --------------------
# FORGIVING MATCH SYSTEM
# --------------------
def similarity(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


def fuzzy_match(guess, keyword):
    guess = normalize(guess)
    keyword = normalize(keyword)

    # remove filler words
    fillers = {"the", "a", "an"}
    guess_tokens = [g for g in guess.split() if g not in fillers]
    keyword_tokens = [k for k in keyword.split() if k not in fillers]

    guess_clean = " ".join(guess_tokens)
    keyword_clean = " ".join(keyword_tokens)

    # exact / partial match
    if keyword_clean in guess_clean or guess_clean in keyword_clean:
        return True

    # fuzzy similarity threshold
    return similarity(guess_clean, keyword_clean) > 0.82


def check_guess_flexible(guess, keywords):
    matched = []

    for k in keywords:
        parts = k.split()

        # allow partial name matching (Bill Clinton → Bill OR Clinton OR full)
        if any(fuzzy_match(guess, p) for p in parts):
            matched.append(k)
        elif fuzzy_match(guess, k):
            matched.append(k)

    return list(set(matched))


# --------------------
# CLUE ENHANCEMENT ENGINE
# --------------------
def add_clues(answer, keywords):
    """
    Ensures answer is NEVER pure guessing.
    Adds lightweight contextual hints for names/events.
    """
    clues = []

    for k in keywords:
        if len(k.split()) > 1:  # likely a name
            clues.append(f"(a well-known figure related to global politics/media/elite institutions)")

    if clues:
        return answer + "\n\nClue: " + random.choice(clues)

    return answer


def scale_keywords(keywords):
    keywords = list(set(keywords))

    # ensure minimum gameplay density
    target = max(MIN_KEYWORDS, min(MAX_KEYWORDS, len(keywords)))

    while len(keywords) < target:
        keywords.append(random.choice(keywords))

    return keywords[:target]


# --------------------
# TELEGRAM HELPERS
# --------------------
async def pin_message(context, chat_id, message_id):
    try:
        await context.bot.pin_chat_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def unpin_message(context, chat_id):
    try:
        await context.bot.unpin_chat_message(chat_id=chat_id)
    except Exception:
        pass


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
        "A meme-driven redaction simulator where names, events, and phrases are partially hidden.\n\n"
        "🎮 Commands:\n"
        "• /trivia — start timed round\n"
        "• /ask — custom prompt\n"
        "• /reveal — reveal answer\n"
        "• /score — your streak\n"
        "• /leaderboard\n\n"
        "🧠 Gameplay Notes:\n"
        "• Minor typos are allowed\n"
        "• Partial name guesses work\n"
        "• Every answer includes subtle clues\n"
    )

    msg = await update.message.reply_text(text, parse_mode="Markdown")
    await pin_message(context, update.effective_chat.id, msg.message_id)
    context.chat_data["menu_message_id"] = msg.message_id


# --------------------
# TRIVIA
# --------------------
async def trivia_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    game = get_active_game(chat_id)
    if game and time.time() - game["asked_at"] < LOCK_SECONDS:
        await update.message.reply_text("⏳ round active")
        return

    await update.message.reply_text("🧠 generating...")

    question, answer, keywords = generate_trivia()

    keywords = scale_keywords(keywords)
    answer = add_clues(answer, keywords)

    redacted = redact_answer(answer, keywords)

    set_active_game(chat_id, answer, redacted, keywords)

    msg = await update.message.reply_text(
        f"📄 *ROUND*\n\n"
        f"{escape_md(question)}\n\n"
        f"{redacted}",
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

    answer, keywords = get_answer(question)

    keywords = scale_keywords(keywords)
    answer = add_clues(answer, keywords)

    redacted = redact_answer(answer, keywords)

    set_active_game(chat_id, answer, redacted, keywords)

    msg = await update.message.reply_text(
        f"📄 *CUSTOM ROUND*\n\n{redacted}",
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

    if remaining:
        new_redacted = redact_answer(game["original"], remaining)
        set_active_game(chat_id, game["original"], new_redacted, remaining)

        await update.message.reply_text(
            f"✅ {user.first_name} got {', '.join(matched)} (+{points})"
        )
    else:
        clear_active_game(chat_id)

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

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Pepstein system running...")
    app.run_polling()


if __name__ == "__main__":
    main()
