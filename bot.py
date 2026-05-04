import os
import logging
import time
import re
import random
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

# --------------------
# LOGGING
# --------------------
logging.basicConfig(level=logging.INFO)
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

round_end_time = {}

# --------------------
# DIFFICULTY WEIGHTING (45 / 35 / 20)
# --------------------
def weighted_difficulty(inferred: str) -> str:
    roll = random.random()

    if roll < 0.45:
        return "easy"
    elif roll < 0.80:
        return "medium"
    else:
        return "hard"


# --------------------
# ROUND BLOCK
# --------------------
def build_round_block(difficulty):
    d = DIFFICULTY[difficulty]
    return (
        f"🗂 ROUND ACTIVE — {d['label']}\n\n"
        f"• Guess redacted words\n"
        f"• +{d['points']} pts each\n"
        f"• /reveal unlocks after timer\n"
    )


# --------------------
# PIN HELPERS
# --------------------
async def pin_message(context, chat_id, message_id):
    try:
        await context.bot.pin_chat_message(chat_id, message_id, disable_notification=True)
    except:
        pass


async def unpin_message(context, chat_id):
    try:
        await context.bot.unpin_chat_message(chat_id)
    except:
        pass


# --------------------
# TIMER
# --------------------
async def start_round_timer(context, chat_id, message_id, duration):
    round_end_time[chat_id] = time.time() + duration

    while True:
        game = get_active_game(chat_id)
        if not game:
            return

        remaining = int(round_end_time[chat_id] - time.time())
        if remaining <= 0:
            await context.bot.send_message(chat_id, "⏱ Timer expired — you can now /reveal")
            return

        mins = remaining // 60
        secs = remaining % 60

        base = context.chat_data.get("last_round_text")
        if not base:
            return

        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=base + f"\n\n⏳ {mins:02d}:{secs:02d}",
                parse_mode="Markdown",
            )
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except:
            pass

        await asyncio.sleep(1)


# --------------------
# ROUND LAUNCH
# --------------------
async def _launch_round(update, context, question, answer, keywords, label):
    chat_id = update.effective_chat.id

    redacted = redact_answer(answer, keywords)

    inferred = "medium"
    difficulty = weighted_difficulty(inferred)

    d = DIFFICULTY[difficulty]

    set_active_game(chat_id, answer, redacted, keywords)

    context.chat_data["difficulty"] = difficulty
    context.chat_data["current_question"] = question

    msg = await update.message.reply_text(
        f"📄 *{label} — {d['label']}*\n\n"
        f"🧠 {question}\n\n"
        f"🧾 {redacted}\n\n"
        f"{build_round_block(difficulty)}",
        parse_mode="Markdown",
    )

    context.chat_data["last_round_text"] = msg.text
    context.chat_data["pinned_game_message"] = msg.message_id

    await pin_message(context, chat_id, msg.message_id)

    asyncio.create_task(start_round_timer(context, chat_id, msg.message_id, d["timer"]))


# --------------------
# COMMANDS
# --------------------
async def trivia_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q, a, k = generate_trivia()
    await _launch_round(update, context, q, a, k, "CLASSIFIED FILE")


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /ask question")

    q = " ".join(context.args)
    a, k = get_answer(q)

    await _launch_round(update, context, q, a, k, "CUSTOM FILE")


# --------------------
# REVEAL
# --------------------
async def reveal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = get_active_game(chat_id)

    if not game:
        return

    if time.time() < round_end_time.get(chat_id, 0):
        return await update.message.reply_text("⏳ wait for timer")

    clear_active_game(chat_id)
    await unpin_message(context, chat_id)

    await update.message.reply_text(f"🔓 {game['original']}")


# --------------------
# MESSAGE HANDLER
# --------------------
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id
    game = get_active_game(chat_id)
    if not game:
        return

    guess = update.message.text
    user = update.effective_user

    matched = [k for k in game["keywords"] if k.lower() in guess.lower()]
    if not matched:
        return

    difficulty = context.chat_data.get("difficulty", DEFAULT_DIFFICULTY)
    pts = DIFFICULTY[difficulty]["points"]

    add_points(user.id, user.first_name, len(matched) * pts)

    remaining = [k for k in game["keywords"] if k not in matched]

    if remaining:
        new_redacted = redact_answer(game["original"], remaining)
        set_active_game(chat_id, game["original"], new_redacted, remaining)

        question = context.chat_data.get("current_question", "")
        d = DIFFICULTY[difficulty]

        base = (
            f"📄 *ROUND IN PROGRESS — {d['label']}*\n\n"
            f"🧠 {question}\n\n"
            f"🧾 {new_redacted}\n\n"
            f"{build_round_block(difficulty)}"
        )

        context.chat_data["last_round_text"] = base

        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=context.chat_data["pinned_game_message"],
            text=base,
            parse_mode="Markdown",
        )

    else:
        clear_active_game(chat_id)
        await unpin_message(context, chat_id)

        await update.message.reply_text(f"🎉 {user.first_name} solved it!\n\n{game['original']}")


# --------------------
# MAIN
# --------------------
def main():
    init_db()

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("trivia", trivia_command))
    app.add_handler(CommandHandler("ask", ask_command))
    app.add_handler(CommandHandler("reveal", reveal_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling()


if __name__ == "__main__":
    main()
