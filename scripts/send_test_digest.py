"""Send a synthetic digest using whatever processed_items are already in DB.

Useful to validate Markdown V2 rendering and Telegram delivery without
running the full pipeline.
"""

from __future__ import annotations

import asyncio
from datetime import date
from uuid import UUID

from telegram import Bot

from src.shared.config import get_settings
from src.shared.db import get_user_by_tg_id
from src.shared.logging import get_logger
from src.worker.digest_builder import build_digest
from src.worker.digest_sender import send_digest

log = get_logger(__name__)


async def main() -> None:
    settings = get_settings()
    settings.require_telegram()
    settings.require_supabase()

    user = get_user_by_tg_id(settings.telegram_owner_id)
    if user is None:
        log.error("no_owner_user — run scripts/seed.py first")
        return

    user_id = UUID(user["id"])
    selected, noise_count = build_digest(user_id)
    log.info("test_digest_built", selected=len(selected), noise=noise_count)

    bot = Bot(token=settings.telegram_bot_token)
    await send_digest(
        bot=bot,
        chat_id=settings.telegram_owner_id,
        user_id=user_id,
        digest_date=date.today(),
        items=selected,
        noise_count=noise_count,
    )


if __name__ == "__main__":
    asyncio.run(main())
