"""Re-score existing raw_items for the owner — useful after prompt changes
(e.g. switching all output to Russian).

Drops `processed_items` + `digests` for the owner, then re-runs pre-filter +
scoring on raw_items from the last N hours. Sources / raw_items themselves
are not touched, so we don't burn HTTP budget refetching.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

from src.shared.config import get_settings
from src.shared.db import (
    get_client,
    get_user_by_tg_id,
    insert_processed_items,
    list_projects,
)
from src.shared.logging import get_logger
from src.worker.pipeline import (
    _apply_pre_filter,
    _apply_trend_tags,
    _build_noise_processed_rows,
)
from src.worker.scoring import score_all, to_processed_row

log = get_logger(__name__)

WINDOW_HOURS = 26


async def main() -> None:
    settings = get_settings()
    settings.require_telegram()
    settings.require_supabase()
    settings.require_llm()

    user = get_user_by_tg_id(settings.telegram_owner_id)
    if user is None:
        raise RuntimeError("no owner user — run scripts/seed.py first")
    user_id = UUID(user["id"])

    client = get_client()

    log.info("rescore_wipe_start", user_id=str(user_id))
    client.table("processed_items").delete().eq("user_id", str(user_id)).execute()
    client.table("digests").delete().eq("user_id", str(user_id)).execute()
    log.info("rescore_wipe_done")

    since = datetime.now(UTC) - timedelta(hours=WINDOW_HOURS)
    raw_res = (
        client.table("raw_items")
        .select("*")
        .gte("fetched_at", since.isoformat())
        .execute()
    )
    raw_rows = raw_res.data or []
    log.info("rescore_raw_items_pulled", count=len(raw_rows))

    if not raw_rows:
        log.warning("rescore_no_raw_items")
        return

    projects = list_projects(user_id)
    project_slugs = {p["slug"] for p in projects}

    passed, rejected = _apply_pre_filter(raw_rows, projects)

    if rejected:
        noise_rows = _build_noise_processed_rows(rejected, user_id)
        insert_processed_items(noise_rows)
        log.info("rescore_noise_persisted", count=len(noise_rows))

    log.info("rescore_scoring_start", to_score=len(passed))
    scored = await score_all(passed, projects)
    log.info("rescore_scoring_done", scored=len(scored))

    raw_id_lookup = {str(r["id"]): r for r in passed}
    processed_rows: list = []
    for sc in scored:
        if sc.raw_item_id not in raw_id_lookup:
            continue
        row = to_processed_row(sc, user_id, UUID(sc.raw_item_id), project_slugs)
        processed_rows.append(row)
    processed_rows = _apply_trend_tags(processed_rows, user_id)
    if processed_rows:
        insert_processed_items(processed_rows)

    log.info(
        "rescore_done",
        raw=len(raw_rows),
        passed_pre_filter=len(passed),
        rejected_pre_filter=len(rejected),
        scored=len(scored),
        persisted=len(processed_rows),
    )


if __name__ == "__main__":
    asyncio.run(main())
