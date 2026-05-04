async def ask_command(update, context):
    if not context.args:
        await update.message.reply_text("Usage: /ask [question]")
        return

    chat_id = update.effective_chat.id
    question = " ".join(context.args)

    await update.message.reply_text("🧠 thinking...")

    answer, keywords = get_answer(question)

    keywords = scale_keywords(keywords)
    answer = add_clues(answer, keywords)

    redacted = redact_answer(answer, keywords)

    set_active_game(chat_id, answer, redacted, keywords)

    msg = await update.message.reply_text(
        f"📄 *NEW ROUND BASED ON YOUR QUESTION*\n\n"
        f"{escape_md(question)}\n\n"
        f"{redacted}",
        parse_mode="Markdown",
    )

    await pin_message(context, chat_id, msg.message_id)
    context.chat_data["pinned_game_message"] = msg.message_id
