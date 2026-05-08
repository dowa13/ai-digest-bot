"""Bot entrypoint — long polling.

Run via `python -m src.bot.main`. Designed to be wrapped in a GitHub Actions
job with timeout-minutes ≈ 350 (so the Action finishes before the 6h cron
spawns the next one — see `.github/workflows/bot-polling.yml`).
"""

from __future__ import annotations

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from src.bot.handlers import callbacks, chat, commands
from src.shared.config import get_settings
from src.shared.logging import get_logger

log = get_logger(__name__)


def build_application() -> Application:
    settings = get_settings()
    settings.require_telegram()
    settings.require_supabase()
    settings.require_llm()

    app = Application.builder().token(settings.telegram_bot_token).build()

    app.add_handler(CommandHandler("start", commands.start))
    app.add_handler(CommandHandler("digest", commands.digest))
    app.add_handler(CommandHandler("weekly", commands.weekly))
    app.add_handler(CommandHandler("monthly", commands.monthly))
    app.add_handler(CommandHandler("learn", commands.learn))
    app.add_handler(CommandHandler("trends", commands.trends))
    app.add_handler(CommandHandler("projects", commands.projects_cmd))
    app.add_handler(CommandHandler("sync", commands.sync_cmd))
    app.add_handler(CommandHandler("sources", commands.sources_cmd))
    app.add_handler(CommandHandler("pause", commands.pause_cmd))
    app.add_handler(CommandHandler("admin", commands.admin_cmd))

    app.add_handler(CallbackQueryHandler(callbacks.handle_callback))

    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, chat.handle_message)
    )

    return app


def main() -> None:
    app = build_application()
    log.info("bot_starting")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
