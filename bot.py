async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📁 *THE PEPSTEIN FILES GAME*\n\n"
        "🧠 WHAT THIS IS:\n"
        "A document reconstruction game where answers are deliberately redacted to keep people from needing to get suicided. Guess the correct word for points!\n"
        "Think: internet conspiracy energy meets word puzzle game.\n\n"
        "🎮 HOW IT WORKS:\n"
        "• /trivia — starts a timed round (2 minutes)\n"
        "• /ask — new round based on your own question (2 minutes)\n"
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
