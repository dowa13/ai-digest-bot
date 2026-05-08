"""One-off pipeline run for the owner. Useful for first deploy / debugging."""

from __future__ import annotations

import asyncio

from src.shared.config import get_settings
from src.shared.logging import get_logger
from src.worker.pipeline import run_pipeline

log = get_logger(__name__)


async def main() -> None:
    settings = get_settings()
    settings.require_telegram()
    settings.require_llm()
    settings.require_supabase()

    stats = await run_pipeline(settings.telegram_owner_id)
    log.info("pipeline_stats", **stats)


if __name__ == "__main__":
    asyncio.run(main())
