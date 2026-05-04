# ONLY CHANGED PARTS ARE MARKED WITH ### FIX

# --------------------
# DIFFICULTY WEIGHTING (NEW)
# --------------------
def weighted_difficulty(inferred: str) -> str:
    roll = random.random()

    if roll < 0.45:        ### FIX
        return "easy"
    elif roll < 0.80:      ### FIX (45% + 35%)
        return "medium"
    else:                  ### FIX (remaining 20%)
        return "hard"


# --------------------
# SHARED ROUND LAUNCH
# --------------------
async def _launch_round(update, context, question, answer, keywords, label="CLASSIFIED FILE"):
    chat_id = update.effective_chat.id

    keywords = refine_keywords(answer, keywords)

    redacted = redact_answer(answer, keywords)

    inferred = infer_difficulty(keywords)
    difficulty = weighted_difficulty(inferred)   ### FIX

    d = DIFFICULTY[difficulty]
    round_block = build_round_block(difficulty)

    set_active_game(chat_id, answer, redacted, keywords)

    context.chat_data["difficulty"] = difficulty
    context.chat_data["current_question"] = question   ### FIX

    msg = await update.message.reply_text(
        f"📄 *{label} — {d['label']}*\n\n"   ### FIX
        f"🧠 {question}\n\n"
        f"🧾 {redacted}\n\n"
        f"{round_block}",
        parse_mode="Markdown",
    )

    context.chat_data["last_round_text"] = msg.text
    context.chat_data["pinned_game_message"] = msg.message_id

    await pin_message(context, chat_id, msg.message_id)
    _start_timer(context, chat_id, msg.message_id, d["timer"])


# --------------------
# MESSAGE HANDLER (FIX QUESTION PERSIST)
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

    difficulty = context.chat_data.get("difficulty", DEFAULT_DIFFICULTY)
    pts_per_word = DIFFICULTY.get(difficulty, DIFFICULTY[DEFAULT_DIFFICULTY])["points"]
    points = len(matched) * pts_per_word

    add_points(user.id, user.username or user.first_name, points)

    remaining = [k for k in game["keywords"] if k not in matched]

    if remaining:
        new_redacted = redact_answer(game["original"], remaining)
        set_active_game(chat_id, game["original"], new_redacted, remaining)

        pinned_id = context.chat_data.get("pinned_game_message")
        question = context.chat_data.get("current_question", "")   ### FIX
        d = DIFFICULTY[difficulty]

        if pinned_id:
            try:
                base = (
                    f"📄 *ROUND IN PROGRESS — {d['label']}*\n\n"   ### FIX
                    f"🧠 {question}\n\n"   ### FIX
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
                logger.exception("Failed to update pinned message")

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
