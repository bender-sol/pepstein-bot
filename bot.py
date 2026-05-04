import os
import logging
import time
import random
import asyncio
import difflib

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
    set_active_game,
    get_active_game,
    clear_active_game,
)

from redactor import get_answer, generate_trivia, redact_answer


# --------------------
# ENV
# --------------------
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

# --------------------
# LOGGING
# --------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --------------------
# DIFFICULTY
# --------------------
DIFFICULTY = {
    "easy":   {"label": "🟢 EASY",   "points": 5,  "timer": 90},
    "medium": {"label": "🟡 MEDIUM", "points": 8,  "timer": 180},
    "hard":   {"label": "🔴 HARD",   "points": 12, "timer": 300},
}

DEFAULT_DIFFICULTY = "medium"
round_end_time = {}

# --------------------
# WEIGHTED DIFFICULTY
# --------------------
def weighted_difficulty():
    roll = random.random()
    if roll < 0.45:
        return "easy"
    elif roll < 0.80:
        return "medium"
    else:
        return "hard"

# --------------------
# UI BLOCK
# --------------------
def build_round_block(diff):
    d = DIFFICULTY[diff]
    return (
        f"🗂 ROUND ACTIVE — {d['label']}\n"
        f"• +{d['points']} pts per word\n"
        f"• /reveal unlocks after timer"
    )

# --------------------
# PIN
# --------------------
async def pin(context, chat_id, msg_id):
    try:
        await context.bot.pin_chat_message(chat_id, msg_id, disable_notification=True)
    except:
        pass

async def unpin(context, chat_id):
    try:
        await context.bot.unpin_chat_message(chat_id)
    except:
        pass

# --------------------
# TIMER
# --------------------
async def timer(context, chat_id, msg_id, duration):
    round_end_time[chat_id] = time.time() + duration

    while True:
        game = get_active_game(chat_id)
        if not game:
            return

        remaining = int(round_end_time[chat_id] - time.time())
        if remaining <= 0:
            await context.bot.send_message(chat_id, "⏱ Timer expired — /reveal unlocked")
            return

        mins, secs = divmod(remaining, 60)
        base = context.chat_data.get("base_text")
        if not base:
            return

        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=f"{base}\n\n⏳ {mins:02d}:{secs:02d}",
                parse_mode="Markdown",
            )
        except RetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except:
            pass

        await asyncio.sleep(1)

# --------------------
# START
# --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📁 *PEPSTEIN ARCHIVE*\n\n"
        "Recover redacted answers.\n\n"
        "Commands:\n"
        "/trivia\n"
        "/ask [question]\n"
        "/reveal",
        parse_mode="Markdown"
    )

# --------------------
# ROUND LAUNCH
# --------------------
async def launch(update, context, question, answer, keywords, label):
    chat_id = update.effective_chat.id

    redacted = redact_answer(answer, keywords)
    difficulty = weighted_difficulty()
    d = DIFFICULTY[difficulty]

    set_active_game(chat_id, answer, redacted, keywords)

    context.chat_data["difficulty"] = difficulty
    context.chat_data["question"] = question

    base = (
        f"📄 *{label} — {d['label']}*\n\n"
        f"🧠 {question}\n\n"
        f"🧾 {redacted}\n\n"
        f"{build_round_block(difficulty)}"
    )

    msg = await update.message.reply_text(base, parse_mode="Markdown")

    context.chat_data["base_text"] = base
    context.chat_data["msg_id"] = msg.message_id

    await pin(context, chat_id, msg.message_id)

    asyncio.create_task(timer(context, chat_id, msg.message_id, d["timer"]))

# --------------------
# COMMANDS
# --------------------
async def trivia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q, a, k = generate_trivia()
    await launch(update, context, q, a, k, "CLASSIFIED FILE")

async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /ask question")

    q = " ".join(context.args)
    a, k = get_answer(q)

    await launch(update, context, q, a, k, "CUSTOM FILE")

# --------------------
# REVEAL
# --------------------
async def reveal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = get_active_game(chat_id)

    if not game:
        return

    if time.time() < round_end_time.get(chat_id, 0):
        return await update.message.reply_text("⏳ wait for timer")

    clear_active_game(chat_id)
    await unpin(context, chat_id)

    await update.message.reply_text(f"🔓 {game['original']}")

# --------------------
# GUESS HANDLER
# --------------------
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id
    game = get_active_game(chat_id)
    if not game:
        return

    guess = update.message.text.lower()
    user = update.effective_user

    matched = [k for k in game["keywords"] if k.lower() in guess]
    if not matched:
        return

    diff = context.chat_data.get("difficulty", DEFAULT_DIFFICULTY)
    pts = DIFFICULTY[diff]["points"]

    add_points(user.id, user.first_name, len(matched) * pts)

    remaining = [k for k in game["keywords"] if k not in matched]

    if remaining:
        new_redacted = redact_answer(game["original"], remaining)
        set_active_game(chat_id, game["original"], new_redacted, remaining)

        question = context.chat_data["question"]
        d = DIFFICULTY[diff]

        base = (
            f"📄 *ROUND IN PROGRESS — {d['label']}*\n\n"
            f"🧠 {question}\n\n"
            f"🧾 {new_redacted}\n\n"
            f"{build_round_block(diff)}"
        )

        context.chat_data["base_text"] = base

        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=context.chat_data["msg_id"],
            text=base,
            parse_mode="Markdown",
        )

    else:
        clear_active_game(chat_id)
        await unpin(context, chat_id)

        await update.message.reply_text(
            f"🎉 {user.first_name} solved it!\n\n{game['original']}"
        )

# --------------------
# MAIN
# --------------------
def main():
    init_db()

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("trivia", trivia))
    app.add_handler(CommandHandler("ask", ask))
    app.add_handler(CommandHandler("reveal", reveal))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

    app.run_polling()

if __name__ == "__main__":
    main()
