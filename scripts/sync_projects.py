"""CLI: sync project profiles from Notion → DB for the configured owner.

Sends a short report to Telegram OWNER on completion. Also used by
.github/workflows/sync-projects.yml weekly cron.
"""

from __future__ import annotations

import asyncio

from telegram import Bot

from src.shared.config import get_settings
from src.shared.db import get_user_by_tg_id
from src.shared.logging import get_logger
from src.shared.notion_sync import NotionSyncService

log = get_logger(__name__)


async def main() -> None:
    settings = get_settings()
    if not settings.notion_sync_enabled:
        log.info("sync_skipped_env_disabled")
        return

    settings.require_notion()
    settings.require_telegram()
    settings.require_supabase()

    user = get_user_by_tg_id(settings.telegram_owner_id)
    if user is None:
        log.error("no_owner_user")
        return

    from uuid import UUID
    user_id = UUID(user["id"])

    service = NotionSyncService()
    result = await service.sync_all_projects(user_id, triggered_by="cron")

    bot = Bot(token=settings.telegram_bot_token)
    text = (
        f"🔄 Sync: {result.synced} ok, {result.failed} fail · {result.duration_ms}ms"
    )
    if result.errors:
        text += "\n" + "\n".join(
            f"- {e.get('slug')}: {e.get('error')}" for e in result.errors
        )
    try:
        await bot.send_message(chat_id=settings.telegram_owner_id, text=text)
    except Exception as exc:  # pragma: no cover
        log.warning("sync_report_send_failed", error=str(exc))

    log.info(
        "sync_done",
        synced=result.synced,
        failed=result.failed,
        duration_ms=result.duration_ms,
    )


if __name__ == "__main__":
    asyncio.run(main())
