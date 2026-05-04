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
        f"🗂 *ROUND ACTIVE* — {d['label']}\n\n"
        f"• Guess the redacted words\n"
        f"• Typos tolerated — the archive is forgiving\n"
        f"• Partial names count\n"
        f"• +{d['points']} pts per word recovered\n"
        f"• Round continues until all words are found\n"
        f"• /reveal and new rounds unlock after {timer_str} timer\n"
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
async def start_round_timer(context, chat_id, message_id, duration):
    round_end_time[chat_id] = time.time() + duration

    try:
        while True:
            game = get_active_game(chat_id)
            if not game:
                return

            remaining = int(round_end_time[chat_id] - time.time())
            if remaining <= 0:
                # Timer expired — notify but keep the round alive.
                # /reveal and new rounds are now unlocked.
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        "⏱ *TIMER EXPIRED — FILE STILL ACTIVE*\n\n"
                        "_The round continues. Keep guessing, or use /reveal to declassify._"
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
            except RetryAfter as e:
                # Telegram is rate-limiting — back off as instructed, then resume
                await asyncio.sleep(e.retry_after)
            except Exception:
                # Message deleted or too many edits — not fatal
                logger.exception("Timer edit failed for chat %s", chat_id)

            await asyncio.sleep(1)

    except asyncio.CancelledError:
        # Clean cancellation from a completed/revealed/forced round — expected
        pass
    except Exception:
        logger.exception("start_round_timer crashed for chat %s", chat_id)


# --------------------
# KEYWORD INTELLIGENCE
# --------------------

# Never redact these — pure grammar/function words
_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "was", "are", "were", "be", "been",
    "it", "its", "this", "that", "these", "those", "not", "no", "so",
    "as", "if", "then", "than", "also", "just", "he", "she", "they",
    "his", "her", "their", "we", "our", "you", "your", "i", "my",
    "have", "has", "had", "do", "did", "does", "will", "would", "could",
    "should", "may", "might", "can", "one", "two", "more", "most",
}

# Looks meaningful but adds nothing to the puzzle — don't redact
_GENERIC_FILLER = {
    "known", "used", "made", "called", "named", "based", "including",
    "during", "after", "before", "part", "place", "time", "way",
    "things", "something", "someone", "large", "small", "major",
    "several", "many", "became", "while", "within", "across",
    "between", "around", "through", "about", "other", "another",
    "however", "therefore", "although", "because", "since", "when",
    "where", "which", "who", "what", "how", "often", "later", "early",
    "new", "old", "long", "high", "low", "good", "well", "back",
    "first", "second", "third", "world", "people", "person", "group",
    "system", "type", "form", "number", "year", "years",
}


def _extract_numbers(answer: str) -> list[str]:
    """Pull standalone numbers and years — always high-value redactions."""
    return re.findall(r'\b\d{4}\b|\b\d+(?:\.\d+)?(?:%|million|billion|thousand)?\b', answer)


def refine_keywords(answer: str, keywords: list[str]) -> list[str]:
    """
    Extract the words most central to answering the question:
    names, organisations, specific numbers, key proper nouns.

    Priority order:
      1. Numbers / years found directly in the answer text
      2. Multi-word phrases (named entities — most valuable)
      3. Capitalized single words (proper nouns)
      4. Long specific words (>6 chars, not generic filler)
      5. Any remaining keyword as last resort

    Target: 3-6 redactions. Never fewer than 3.
    """
    # Deduplicate while preserving order, drop pure stopwords
    seen = set()
    words = []
    for w in keywords:
        key = w.lower().strip()
        if key and key not in seen and key not in _STOPWORDS:
            seen.add(key)
            words.append(w.strip())

    # Tier 1 — numbers and years pulled directly from the answer
    numbers = _extract_numbers(answer)
    tier1 = [n for n in numbers if n not in seen]

    # Tier 2 — multi-word phrases (e.g. "Barack Obama", "British Virgin Islands")
    tier2 = [w for w in words if len(w.split()) > 1]

    # Tier 3 — capitalized single words (proper nouns)
    tier3 = [
        w for w in words
        if w[0].isupper()
        and len(w.split()) == 1
        and w not in tier2
        and w.lower() not in _STOPWORDS
    ]

    # Tier 4 — long specific words not already captured
    captured = set(tier2 + tier3)
    tier4 = [
        w for w in words
        if w not in captured
        and len(w) > 6
        and w.lower() not in _GENERIC_FILLER
    ]

    # Tier 5 — anything left as absolute fallback
    captured.update(tier4)
    tier5 = [w for w in words if w not in captured]

    pool = tier1 + tier2 + tier3 + tier4 + tier5

    # Take up to 6, enforce minimum of 3
    final = []
    for w in pool:
        if len(final) >= 6:
            break
        if w not in final:
            final.append(w)

    # Safety net: if still under 3, mine words directly from answer text
    if len(final) < 3:
        answer_words = [w.strip(".,;:()[]\"'") for w in answer.split()]
        for w in answer_words:
            if len(final) >= 3:
                break
            key = w.lower()
            if (
                w not in final
                and key not in _STOPWORDS
                and key not in _GENERIC_FILLER
                and len(w) > 3
            ):
                final.append(w)

    return final


def infer_difficulty(keywords: list[str]) -> str:
    """
    Infer difficulty from the refined keyword list.
    Target distribution: easy ~50%, medium ~35%, hard ~15%.

    Easy:   3 or fewer keywords, no obscure terms, no numbers+multiword combo
    Hard:   6 keywords, OR numbers AND multi-word phrases together,
            OR 3+ keywords longer than 10 chars (genuinely obscure)
    Medium: everything else
    """
    count = len(keywords)
    has_number = any(re.match(r'^\d', k) for k in keywords)
    has_multiword = any(len(k.split()) > 1 for k in keywords)
    long_obscure = sum(1 for k in keywords if len(k) > 10)

    if count >= 6 or (has_number and has_multiword) or long_obscure >= 3:
        return "hard"
    elif count <= 3 and long_obscure == 0:
        return "easy"
    else:
        return "medium"


# --------------------
# TASK HELPERS
# --------------------
def _cancel_timer(context):
    """Cancel any running timer task for this chat."""
    task = context.chat_data.pop("timer_task", None)
    if task and not task.done():
        task.cancel()


def _start_timer(context, chat_id, message_id, duration):
    """Spawn a timer task and store the reference."""
    _cancel_timer(context)
    task = asyncio.create_task(
        start_round_timer(context, chat_id, message_id, duration)
    )
    context.chat_data["timer_task"] = task


# --------------------
# END ROUND HELPER
# --------------------
async def _end_round(context, chat_id, game, reason="revealed"):
    """Shared teardown for any round-ending path."""
    _cancel_timer(context)
    clear_active_game(chat_id)
    await unpin_message(context, chat_id)

    if reason == "forced":
        return "_Round terminated. The archive does not negotiate._"
    elif reason == "revealed":
        return "_Now you know. Act accordingly._"
    else:
        return "_The file has been closed._"


# --------------------
# START
# --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📁 *PEPSTEIN ARCHIVE — ACCESS GRANTED*\n\n"
        "You have been connected to a classified trivia reconstruction system.\n"
        "Critical words have been redacted. Your job is to recover them.\n\n"
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
        "Identify the redacted words in each classified file.\n"
        "The redacted words are always central to the answer — no decoys.\n\n"
        "🧠 *COMMANDS:*\n"
        "• /trivia — random classified file\n"
        "• /ask — submit your own question to the system\n"
        "• /reveal — unlock the file _(only after timer expires)_\n"
        "• /score — your dossier\n"
        "• /leaderboard — archive rankings\n\n"
        "🏆 *SCORING:*\n"
        "• 🟢 Easy — +5 pts per word\n"
        "• 🟡 Medium — +8 pts per word\n"
        "• 🔴 Hard — +12 pts per word\n"
        "• Typos tolerated. Partial names accepted.\n\n"
        "⏱ *TIMER:*\n"
        "• Easy — 1:30\n"
        "• Medium — 3:00\n"
        "• Hard — 5:00\n"
        "• Timer prevents stall — round continues after it expires\n"
        "• /reveal unlocks once the timer runs out\n\n"
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
    logger.info("KEYWORDS for chat %s: %s", chat_id, keywords)

    redacted = redact_answer(answer, keywords)
    logger.info("REDACTED result for chat %s: %s", chat_id, redacted)

    difficulty = infer_difficulty(keywords)
    d = DIFFICULTY[difficulty]
    round_block = build_round_block(difficulty)

    set_active_game(chat_id, answer, redacted, keywords)
    context.chat_data["difficulty"] = difficulty

    msg = await update.message.reply_text(
        f"📄 *{label}* — {d['label']}\n\n"
        f"🧠 {question}\n\n"
        f"🧾 {redacted}\n\n"
        f"{round_block}",
        parse_mode="Markdown",
    )

    context.chat_data["last_round_text"] = msg.text
    context.chat_data["pinned_game_message"] = msg.message_id
    context.chat_data["active_question"] = question

    await pin_message(context, chat_id, msg.message_id)
    _start_timer(context, chat_id, msg.message_id, d["timer"])


# --------------------
# TRIVIA
# --------------------
async def trivia_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    game = get_active_game(chat_id)
    if game:
        lock = DIFFICULTY.get(
            context.chat_data.get("difficulty", DEFAULT_DIFFICULTY),
            DIFFICULTY[DEFAULT_DIFFICULTY]
        )["timer"]
        if time.time() - game["asked_at"] < lock:
            remaining = int(lock - (time.time() - game["asked_at"]))
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
    if game:
        lock = DIFFICULTY.get(
            context.chat_data.get("difficulty", DEFAULT_DIFFICULTY),
            DIFFICULTY[DEFAULT_DIFFICULTY]
        )["timer"]
        if time.time() - game["asked_at"] < lock:
            remaining = int(lock - (time.time() - game["asked_at"]))
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

    # Use DB asked_at + difficulty timer as source of truth — survives restarts
    lock = DIFFICULTY.get(
        context.chat_data.get("difficulty", DEFAULT_DIFFICULTY),
        DIFFICULTY[DEFAULT_DIFFICULTY]
    )["timer"]
    elapsed = time.time() - game["asked_at"]

    if elapsed < lock:
        remaining = int(lock - elapsed)
        await update.message.reply_text(
            f"🔒 file still locked — {remaining}s remaining\n"
            "_The archive releases on its own schedule._"
        )
        return

    flavour = await _end_round(context, chat_id, game, reason="revealed")

    await update.message.reply_text(
        f"🔓 *FILE DECLASSIFIED*\n\n{game['original']}\n\n{flavour}",
        parse_mode="Markdown",
    )


# --------------------
# FORCE (admin/testing only — not listed in /start or /rules)
# --------------------
async def force_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if ADMIN_ID and user.id != ADMIN_ID:
        await update.message.reply_text("🚫 clearance denied")
        return

    chat_id = update.effective_chat.id
    game = get_active_game(chat_id)

    if not game:
        await update.message.reply_text("📭 no active round to terminate")
        return

    flavour = await _end_round(context, chat_id, game, reason="forced")

    await update.message.reply_text(
        f"⛔ *ROUND TERMINATED*\n\n"
        f"🔓 {game['original']}\n\n{flavour}",
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

    # Points scale with difficulty
    difficulty = context.chat_data.get("difficulty", DEFAULT_DIFFICULTY)
    pts_per_word = DIFFICULTY.get(difficulty, DIFFICULTY[DEFAULT_DIFFICULTY])["points"]
    points = len(matched) * pts_per_word

    add_points(user.id, user.username or user.first_name, points)

    remaining = [k for k in game["keywords"] if k not in matched]

    if remaining:
        new_redacted = redact_answer(game["original"], remaining)
        set_active_game(chat_id, game["original"], new_redacted, remaining)

        pinned_id = context.chat_data.get("pinned_game_message")
        if pinned_id:
            try:
                active_q = context.chat_data.get("active_question", "")
                d_label = DIFFICULTY.get(difficulty, DIFFICULTY[DEFAULT_DIFFICULTY])["label"]
                base = (
                    f"📄 *ROUND IN PROGRESS* — {d_label}\n\n"
                    f"🧠 {active_q}\n\n"
                    f"🧾 {new_redacted}\n\n"
                    f"{build_round_block(difficulty)}"
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
        flavour = await _end_round(context, chat_id, game, reason="solved")

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
    app.add_handler(CommandHandler("force", force_command))  # unlisted admin command
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Pepstein Archive online.")
    app.run_polling()


if __name__ == "__main__":
    main()
