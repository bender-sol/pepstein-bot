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
# START (UPDATED ONLY)
# --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📁 *PEPSTEIN ARCHIVE SYSTEM ONLINE*\n\n"
        "A meme-driven redaction simulator where words, names, and phrases are partially hidden for you to reconstruct.\n\n"
        "🧠 WHAT THIS IS:\n"
        "You are entering a chaotic trivia reconstruction system where answers are deliberately redacted, but always contain clues to help you solve them.\n"
        "Think: internet conspiracy energy meets word puzzle game.\n\n"
        "🎮 HOW IT WORKS:\n"
        "• /trivia — starts a timed round (2 minutes)\n"
        "• /ask — generates a custom timed question (2 minutes)\n"
        "• /reveal — ends the round and shows full answer\n"
        "• /rules — full breakdown of mechanics\n"
        "• /score — shows your current streak score\n"
        "• /leaderboard — top players in the archive\n\n"
        "⚠️ GAME RULES IN PRACTICE:\n"
        "• Minor typos are allowed\n"
        "• Partial names (first or last) still count\n"
        "• Every round includes hidden contextual clues\n"
        "• Difficulty scales over time automatically\n\n"
        "📌 Type /rules for full technical breakdown."
    )

    msg = await update.message.reply_text(text, parse_mode="Markdown")
    context.chat_data["menu_message_id"] = msg.message_id


# --------------------
# RULES (NEW COMMAND)
# --------------------
async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📜 *PEPSTEIN ARCHIVE — FULL RULESET*\n\n"
        "🎯 OBJECTIVE:\n"
        "Guess the missing words in redacted prompts before the timer ends.\n\n"
        "🧠 COMMANDS:\n"
        "• /trivia — start random timed round (2 min)\n"
        "  → Generates a random reconstructed knowledge fragment\n\n"
        "• /ask [question] — custom timed round (2 min)\n"
        "  → You control the topic, bot generates redacted answer\n\n"
        "• /reveal — ends current round\n"
        "  → Shows full original answer\n\n"
        "• /score — shows your current streak multiplier and points\n"
        "• /leaderboard — shows top scoring players\n\n"
        "🏆 SCORING:\n"
        "• +10 points per correct word\n"
        "• streaks increase multipliers over time\n"
        "• partial name guesses count as correct\n\n"
        "🧠 MATCHING SYSTEM:\n"
        "• Minor spelling mistakes allowed\n"
        "• 'the / a / an' ignored automatically\n"
        "• first or last names alone can count\n\n"
        "🔍 GAME DESIGN:\n"
        "• Every answer contains subtle contextual clues\n"
        "• Nothing is pure guesswork\n"
        "• Difficulty increases as you perform better\n"
    )

    await update.message.reply_text(text, parse_mode="Markdown")


# --------------------
# EVERYTHING ELSE UNCHANGED
# --------------------
def normalize(text: str) -> str:
    return text.lower().strip()


def escape_md(text: str) -> str:
    for ch in ["_", "*", "[", "]", "`"]:
        text = text.replace(ch, f"\\{ch}")
    return text


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


def add_clues(answer, keywords):
    clues = []

    for k in keywords:
        if len(k.split()) > 1:
            clues.append("(contextually linked to major public figures, institutions, or widely reported events)")

    if clues:
        return answer + "\n\nClue: " + random.choice(clues)

    return answer


def scale_keywords(keywords):
    keywords = list(set(keywords))
    target = max(MIN_KEYWORDS, min(MAX_KEYWORDS, len(keywords)))

    while len(keywords) < target:
        keywords.append(random.choice(keywords))

    return keywords[:target]


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
# KEEP REST EXACTLY SAME
# --------------------
# (no changes below this point)

async def trivia_command(update, context): ...
async def ask_command(update, context): ...
async def reveal_command(update, context): ...
async def handle_message(update, context): ...
def main(): ...
