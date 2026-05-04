import os
import logging
import time
import re
import difflib
import asyncio
from collections import defaultdict

from telegram import Update
from telegram.error import RetryAfter
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
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN is missing")


# --------------------
# LOGGING
# --------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# --------------------
# DIFFICULTY CONFIG
# --------------------
DIFFICULTY = {
    "easy":   {"label": "🟢 EASY",   "points": 5,  "timer": 90},
    "medium": {"label": "🟡 MEDIUM", "points": 8,  "timer": 180},
    "hard":   {"label": "🔴 HARD",   "points": 12, "timer": 300},
}

DEFAULT_DIFFICULTY = "medium"

streaks = defaultdict(int)
round_end_time = {}


# --------------------
# ROUND UI BLOCK
# --------------------
def build_round_block(difficulty: str) -> str:
    d = DIFFICULTY.get(difficulty, DIFFICULTY[DEFAULT_DIFFICULTY])
    mins = d["timer"] // 60
    secs = d["timer"] % 60
    timer_str = f"{mins}:{secs:02d}" if secs else f"{mins}:00"
    return (
        f"• Guess the redacted words\n"
        f"• Typos tolerated — the archive is forgiving\n"
        f"• Partial names count\n"
        f"• +{d['points']} pts per word recovered\n"
        f"• Round continues until all words are found\n"
        f"• /reveal and new rounds unlock after {timer_str} timer"
    )


# --------------------
# PIN HELPERS
# --------------------
async def pin_message(context, chat_id, message_id):
    try:
        await context.bot.pin_chat_message(
            chat_id=chat_id,
            message_id=message_id,
            disable_notification=True,
        )
    except Exception:
        logger.exception("pin_message failed for chat %s", chat_id)


async def unpin_message(context, chat_id):
    try:
        await context.bot.unpin_chat_message(chat_id=chat_id)
    except Exception:
        logger.exception("unpin_message failed for chat %s", chat_id)


# --------------------
# TIMER ENGINE
# --------------------
async def start_round_timer(context, chat_id, message_id, duration):
    round_end_time[chat_id] = time.time() + duration

    try:
        while True:
            game = get_active_game(chat_id)
            if not game:
                return

            remaining = int(round_end_time[chat_id] - time.time())
            if remaining <= 0:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⏱ *TIMER EXPIRED — FILE STILL ACTIVE*\n\n"
                         "_The round continues. Keep guessing, or use /reveal to declassify._",
                    parse_mode="Markdown",
                )
                return

            mins = remaining // 60
            secs = remaining % 60
            timer_line = f"\n\n⏳ {mins:02d}:{secs:02d} remaining"

            base_text = context.chat_data.get("last_round_text")
            if not base_text:
                return

            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    
