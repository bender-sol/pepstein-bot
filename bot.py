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
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # set ADMIN_ID in Railway variables

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
# DIFFICULTY CONFIG
#
# Timer philosophy: the timer exists to prevent stall, not to add pressure.
# Harder questions need more time because they take longer to work through,
# not because we want to punish players.
#
# Easy   — common knowledge, single well-known name/date. 90s is plenty.
# Medium — requires some background knowledge, 2-3 keywords. 3 min is fair.
# Hard   — obscure figures, specific numbers, multi-part answers. 5 min.
# --------------------
DIFFICULTY = {
    "easy":   {"label": "🟢 EASY",   "points": 5,  "timer": 90},
    "medium": {"label": "🟡 MEDIUM", "points": 8,  "timer": 180},
    "hard":   {"label": "🔴 HARD",   "points": 12, "timer": 300},
}

DEFAULT_DIFFICULTY = "medium"

streaks = defaultdict(int)  # TODO: wire into scoring multiplier

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
        f"🗂 *ROUND ACTIVE* — {d['label']}\\n\\n"
        f"• Guess the redacted words\\n"
        f"• Typos tolerated — the archive is forgiving\\n"
        f"• Partial names count\\n"
        f"• +{d['points']} pts per word recovered\\n"
        f"• Round continues until all words are found\\n"
        f"• /reveal and new rounds unlock after {timer_str} timer\\n"
    )


# --------------------
# PIN HELPERS
# --------------------
async def pin_message(context, chat_id, message_id):
    try:
        await context.bot.pin_chat_message(
            chat_id=chat_id,
            message_id=message_id
