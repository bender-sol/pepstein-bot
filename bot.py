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

# TODO: hook MIN/MAX into refine_keywords once keyword count scaling is added
MIN_KEYWORDS = 3
MAX_KEYWORDS = 8

streaks = defaultdict(int)          # TODO: wire into scoring multiplier
chat_difficulty = defaultdict(int)  # TODO: wire into trivia generation

round_end_time = {}


# --------------------
# ROUND UI BLOCK
# --------------------
ROUND_BLOCK = (
    "🗂 *ROUND ACTIVE*\n\n"
    "• Guess the ███ redacted ███ words\n"
    "• Typos tolerated — the archive is forgiving\n"
    "• Partial names count\n"
    "• First correct match wins points\n"
    "• /reveal unlocks after timer expires\n"
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
# TIMER ENGINE (1s UPDATE)
# --------------------
async def start_round_timer(context, chat_id, message_id, duration=120):
    round_end_time[chat_id] = time.time() + duration

    try:
        while True:
            game = get_active_game(chat_id)
            if not game:
                return

            remaining = int(round_end_time[chat_id] - time.time())
            if remaining <= 0:
                # Time expired — auto-reveal
                clear_active_game(chat_id)
                await unpin_message(context, chat_id)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        "⏱ *TIME'S UP — FILE DECLASSIFIED*\n\n"
                        f"{game['original']}\n\n"
                        "_No one cracked it. The archive remembers._"
                    ),
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
                    text=base_text + timer_line,
                    parse_mode="Markdown",
                )
            except Exception:
                # Message may have been deleted or too many edits — not fatal
                logger.exception("Timer edit failed for chat %s", chat_id)

            await asyncio.sleep(1)

    except asyncio.CancelledError:
        # Clean cancellation from a completed/revealed round — expected
        pass
    except Exception:
        logger.exception("start_round_timer crashed for chat %s", chat_id)


# --------------------
# KEYWORD INTELLIGENCE
# --------------------
# Stopwords that are never worth redacting
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "was", "are", "were", "be", "been",
    "it", "its", "this", "that", "these", "those", "not", "no", "so",
    "as", "if", "then", "than", "also", "just", "he", "she", "they",
    "his", "her", "their", "we", "our", "you", "your", "i", "my",
}

# Words that look important but are generic filler in trivia answers
_GENERIC_FILLER = {
    "known", "used", "made", "called", "named", "based", "including",
    "during", "after", "before", "first", "second", "third", "world",
    "part", "place", "time", "year", "years", "people", "person",
    "group", "system", "type", "form", "way", "things", "something",
    "someone", "number", "large", "small", "major", "several", "many",
}


def refine_keywords(answer: str, keywords: list[str]) -> list[str]:
    """
    From the raw keyword list, extract the words most central to
    understanding the answer — names, orgs, specific nouns.

    Priority order:
      1. Multi-word phrases (likely named entities)
      2. Capitalized single words (proper nouns)
      3. Long meaningful words (>6 chars, not generic filler)
      4. Any remaining keyword as fallback

    Returns 2–4 keywords, deduplicated, order-preserved.
    """
    # Deduplicate while preserving order
    seen = set()
    words = []
    for w in keywords:
        key = w.lower().strip()
        if key not in seen and key not in _STOPWORDS:
            seen.add(key)
            words.append(w.strip())

    multi_word   = [w for w in words if len(w.split()) > 1]
    capitalized  = [w for w in words if w[0].isupper() and len(w.split()) == 1 and w.lower() not in _STOPWORDS]
    long_words   = [w for w in words if len(w) > 6 and w not in multi_word and w not in capitalized and w.lower() not in _GENERIC_FILLER]
    fallback     = [w for w in words if w not in multi_word and w not in capitalized and w not in long_words]

    pool = multi_word + capitalized + long_words + fallback

    # Aim for 2–4 redactions — enough to be a puzzle, not a blackout
    final = []
    for w in pool:
        if len(final) >= 4:
            break
        final.append(w)

    # Hard minimum: always redact at least 2 words or the game is trivial
    while len(final) < 2 and words:
        candidate = words.pop(0)
        if candidate not in final:
            final.append(candidate)

    return final


# --------------------
# TASK HELPERS
# --------------------
def _cancel_timer(context):
    """Cancel any running timer task for this chat."""
    task = context.chat_data.pop("timer_task", None)
    if task and not task.done():
        task.cancel()


def _start_timer(context, chat_id, message_id):
    """Spawn a timer task and store the reference."""
    _cancel_timer(context)
    task = asyncio.create_task(
        start_round_timer(context, chat_id, message_id, LOCK_SECONDS)
    )
    context.chat_data["timer_task"] = task


# --------------------
# START
# --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📁 *PEPSTEIN ARCHIVE — ACCESS GRANTED*\n\n"
        "You have been connected to a classified trivia reconstruction system.\n"
        "Critical words have been ███ redacted ███. Your job is to recover them.\n\n"
        "🎮 *COMMANDS:*\n"
        "• /trivia — pull a random file from the archive\n"
        "• /ask [question] — submit your own inquiry\n"
        "• /reveal — declassify the answer _(timer must expire first)_\n"
        "• /score — your current standing\n"
        "• /leaderboard — who's been reading the files\n"
        "• /rules — full mechanics\n\n"
        "⚠️ _The archive does not forget. Neither do we._"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# --------------------
# RULES
# --------------------
async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📜 *PEPSTEIN ARCHIVE — OPERATIONAL BRIEFING*\n\n"
        "🎯 *OBJECTIVE:*\n"
        "Identify the ███ redacted ███ words in each classified file.\n"
        "The redacted words are always central to the answer — no decoys.\n\n"
        "🧠 *COMMANDS:*\n"
        "• /trivia — random classified file\n"
        "• /ask — submit your own question to the system\n"
        "• /reveal — unlock the file _(only after 2 min timer expires)_\n"
        "• /score — your dossier\n"
        "• /leaderboard — archive rankings\n\n"
        "🏆 *SCORING:*\n"
        "• +10 per recovered word\n"
        "• Streak multipliers apply\n"
        "• Typos tolerated. Partial names accepted.\n\n"
        "🔒 *TIMER RULES:*\n"
        "• Each round locks for 2 minutes\n"
        "• /reveal is blocked until the timer runs out\n"
        "• If nobody guesses in time, the archive auto-declassifies\n\n"
        "⚠️ _All communications are monitored. Guess accordingly._"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# --------------------
# SCORE
# --------------------
async def score_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    points = get_user_score(user.id)
    await update.message.reply_text(
        f"🗂 *DOSSIER: {user.first_name}*\n\n"
        f"Archive standing: *{points} pts*\n\n"
        "_The archive keeps score even when you don't._",
        parse_mode="Markdown",
    )


# --------------------
# LEADERBOARD
# --------------------
async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_leaderboard()
    if not rows:
        await update.message.reply_text("📭 The archive has no records yet.")
        return

    lines = ["🏛 *PEPSTEIN ARCHIVE — TOP OPERATIVES*\n"]
    medals = ["🥇", "🥈", "🥉"]
    for i, (username, pts) in enumerate(rows[:10]):
        prefix = medals[i] if i < 3 else f"{i+1}."
        lines.append(f"{prefix} {username} — {pts} pts")

    lines.append("\n_They read the files. Did you?_")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# --------------------
# GAME FUNCTIONS
# --------------------
def normalize(text: str) -> str:
    return text.lower().strip()


def similarity(a, b):
    return difflib.SequenceMatcher(None, a, b).ratio()


def fuzzy_match(guess: str, keyword: str) -> bool:
    guess = normalize(guess)
    keyword = normalize(keyword)

    fillers = {"the", "a", "an"}
    guess_tokens   = [g for g in guess.split()   if g not in fillers]
    keyword_tokens = [k for k in keyword.split() if k not in fillers]

    guess_clean   = " ".join(guess_tokens)
    keyword_clean = " ".join(keyword_tokens)

    if keyword_clean in guess_clean or guess_clean in keyword_clean:
        return True

    return similarity(guess_clean, keyword_clean) > 0.82


def check_guess_flexible(guess: str, keywords: list[str]) -> list[str]:
    matched = []
    for k in keywords:
        parts = k.split()
        if any(fuzzy_match(guess, p) for p in parts) or fuzzy_match(guess, k):
            matched.append(k)
    return list(set(matched))


# --------------------
# SHARED ROUND LAUNCH
# --------------------
async def _launch_round(update, context, question, answer, keywords, label="CLASSIFIED FILE"):
    """Shared logic for trivia and ask commands."""
    chat_id = update.effective_chat.id

    keywords = refine_keywords(answer, keywords)
    redacted = redact_answer(answer, keywords)

    set_active_game(chat_id, answer, redacted, keywords)

    msg = await update.message.reply_text(
        f"📄 *{label}*\n\n"
        f"🧠 {question}\n\n"
        f"🧾 {redacted}\n\n"
        f"{ROUND_BLOCK}",
        parse_mode="Markdown",
    )

    # Store base text WITHOUT timer suffix — timer appends its own line
    context.chat_data["last_round_text"] = msg.text
    context.chat_data["pinned_game_message"] = msg.message_id

    await pin_message(context, chat_id, msg.message_id)
    _start_timer(context, chat_id, msg.message_id)


# --------------------
# TRIVIA
# --------------------
async def trivia_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    game = get_active_game(chat_id)
    if game and time.time() - game["asked_at"] < LOCK_SECONDS:
        remaining = int(LOCK_SECONDS - (time.time() - game["asked_at"]))
        await update.message.reply_text(f"⏳ round active — {remaining}s remaining")
        return

    await update.message.reply_text("🗂 pulling file from the archive...")

    question, answer, keywords = generate_trivia()
    await _launch_round(update, context, question, answer, keywords, label="CLASSIFIED FILE")


# --------------------
# ASK
# --------------------
async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: `/ask [question]`\n_Submit your inquiry to the archive._",
            parse_mode="Markdown",
        )
        return

    chat_id = update.effective_chat.id

    game = get_active_game(chat_id)
    if game and time.time() - game["asked_at"] < LOCK_SECONDS:
        remaining = int(LOCK_SECONDS - (time.time() - game["asked_at"]))
        await update.message.reply_text(f"⏳ round active — {remaining}s remaining")
        return

    question = " ".join(context.args)
    await update.message.reply_text("🧠 cross-referencing the archive...")

    answer, keywords = get_answer(question)
    await _launch_round(update, context, question, answer, keywords, label="CUSTOM INQUIRY")


# --------------------
# REVEAL
# --------------------
async def reveal_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    game = get_active_game(chat_id)

    if not game:
        await update.message.reply_text("📭 no active round")
        return

    # Use DB asked_at as source of truth — survives restarts
    elapsed = time.time() - game["asked_at"]
    if elapsed < LOCK_SECONDS:
        remaining = int(LOCK_SECONDS - elapsed)
        await update.message.reply_text(
            f"🔒 file still locked — {remaining}s remaining\n"
            "_The archive releases on its own schedule._"
        )
        return

    _cancel_timer(context)
    clear_active_game(chat_id)
    await unpin_message(context, chat_id)

    await update.message.reply_text(
        f"🔓 *FILE DECLASSIFIED*\n\n{game['original']}\n\n"
        "_Now you know. Act accordingly._",
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

        # Update the pinned message to reflect newly revealed words
        pinned_id = context.chat_data.get("pinned_game_message")
        if pinned_id:
            try:
                base = (
                    f"📄 *ROUND IN PROGRESS*\n\n"
                    f"🧾 {new_redacted}\n\n"
                    f"{ROUND_BLOCK}"
                )
                context.chat_data["last_round_text"] = base
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=pinned_id,
                    text=base,
                    parse_mode="Markdown",
                )
            except Exception:
                logger.exception("Failed to update pinned message after partial guess")

        await update.message.reply_text(
            f"✅ *{user.first_name}* recovered `{', '.join(matched)}` _(+{points} pts)_\n"
            f"🔎 {len(remaining)} word(s) still redacted.",
            parse_mode="Markdown",
        )

    else:
        _cancel_timer(context)
        clear_active_game(chat_id)
        await unpin_message(context, chat_id)

        await update.message.reply_text(
            f"🎉 *{user.first_name} cracked the file!* _(+{points} pts)_\n\n"
            f"🔓 {game['original']}\n\n"
            "_The archive has been compromised._",
            parse_mode="Markdown",
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
    app.add_handler(CommandHandler("score", score_command))
    app.add_handler(CommandHandler("leaderboard", leaderboard_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Pepstein Archive online.")
    app.run_polling()


if __name__ == "__main__":
    main()
