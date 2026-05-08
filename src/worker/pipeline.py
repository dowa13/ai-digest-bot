"""End-to-end daily pipeline: fetch → dedup → pre-filter → score → persist → build → send.

Run via `python -m src.worker.pipeline` (uses the env-configured user) or
`python -m scripts.run_pipeline_once` for a one-off.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any
from uuid import UUID

from telegram import Bot

from src.shared.config import get_settings
from src.shared.db import (
    canonical_url,
    existing_url_hashes,
    get_user_by_tg_id,
    increment_source_fail,
    insert_processed_items,
    insert_raw_items,
    list_active_sources,
    list_projects,
    mark_source_fetched,
    url_hash,
)
from src.shared.logging import get_logger
from src.shared.models import RawItemDTO
from src.worker.digest_builder import build_digest
from src.worker.digest_sender import send_digest
from src.worker.fetchers import get_fetcher
from src.worker.pre_filter import build_pre_filter_regex, passes_pre_filter
from src.worker.scoring import (
    score_all,
    to_processed_row,
)
from src.worker.trend_tracker import trending_topics

log = get_logger(__name__)

FETCH_TIMEOUT_SEC = 30


async def _safe_fetch(source: dict[str, Any]) -> tuple[dict[str, Any], list[RawItemDTO]]:
    fetcher = get_fetcher(source["kind"])
    try:
        items = await asyncio.wait_for(fetcher(source), timeout=FETCH_TIMEOUT_SEC)
        mark_source_fetched(UUID(source["id"]))
        return source, items
    except Exception as exc:
        log.warning("source_fetch_failed", source=source["name"], error=str(exc))
        try:
            increment_source_fail(UUID(source["id"]))
        except Exception:  # pragma: no cover
            pass
        return source, []


async def fetch_all_sources() -> list[tuple[dict[str, Any], list[RawItemDTO]]]:
    sources = list_active_sources()
    log.info("fetching_sources", total=len(sources))
    results = await asyncio.gather(*(_safe_fetch(s) for s in sources))
    return list(results)


def _flatten(
    fetched: list[tuple[dict[str, Any], list[RawItemDTO]]],
) -> list[tuple[dict[str, Any], RawItemDTO]]:
    out: list[tuple[dict[str, Any], RawItemDTO]] = []
    for src, items in fetched:
        for it in items:
            out.append((src, it))
    return out


def _dedup_against_db(pairs: list[tuple[dict[str, Any], RawItemDTO]]) -> list[dict[str, Any]]:
    """Compute hashes, drop already-seen ones, return raw rows ready to insert."""
    by_hash: dict[str, dict[str, Any]] = {}
    for src, it in pairs:
        h = url_hash(it.url)
        if h in by_hash:
            continue
        by_hash[h] = {
            "source_id": src["id"],
            "url": canonical_url(it.url),
            "url_hash": h,
            "title": it.title,
            "content": it.content,
            "published_at": it.published_at.isoformat() if it.published_at else None,
        }
    if not by_hash:
        return []
    seen = existing_url_hashes(list(by_hash.keys()))
    fresh = [row for h, row in by_hash.items() if h not in seen]
    log.info("dedup_done", seen=len(seen), fresh=len(fresh))
    return fresh


def _apply_pre_filter(
    raw_rows: list[dict[str, Any]], projects: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (passed, rejected) raw rows."""
    project_kw: list[str] = []
    for p in projects:
        project_kw.extend(p.get("keywords") or [])
    regex = build_pre_filter_regex(project_kw)

    passed: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for r in raw_rows:
        text = ((r.get("title") or "") + " " + (r.get("content") or ""))[:4000]
        if passes_pre_filter(text, regex):
            passed.append(r)
        else:
            rejected.append(r)
    log.info("pre_filter_done", passed=len(passed), rejected=len(rejected))
    return passed, rejected


def _build_noise_processed_rows(
    raw_rows_with_db_id: list[dict[str, Any]], user_id: UUID
) -> list[dict[str, Any]]:
    """For pre-filter-rejected rows, insert minimal processed_items so they're recorded."""
    out: list[dict[str, Any]] = []
    for r in raw_rows_with_db_id:
        out.append(
            {
                "raw_item_id": r["id"],
                "user_id": str(user_id),
                "tldr": (r.get("title") or "")[:200],
                "summary": (r.get("title") or "")[:400],
                "category": "noise",
                "is_noise": True,
                "global_score": 0,
                "learning_value": 0,
                "project_scores": {},
                "matched_projects": [],
                "topics": [],
                "reasoning": "pre-filter rejected",
            }
        )
    return out


def _apply_trend_tags(processed_rows: list[dict[str, Any]], user_id: UUID) -> list[dict[str, Any]]:
    trends = trending_topics(user_id)
    for r in processed_rows:
        if any(t in trends for t in (r.get("topics") or [])):
            r["trend_tag"] = True
    return processed_rows


async def run_pipeline(tg_user_id: int) -> dict[str, Any]:
    """Top-level entry point. Returns a stats dict."""
    settings = get_settings()
    user = get_user_by_tg_id(tg_user_id)
    if user is None:
        raise RuntimeError(f"no user with tg_user_id={tg_user_id}; run scripts/seed.py first")
    user_id = UUID(user["id"])

    fetched = await fetch_all_sources()
    pairs = _flatten(fetched)
    raw_to_insert = _dedup_against_db(pairs)
    if not raw_to_insert:
        log.info("pipeline_done_nothing_fresh")
        return {"fetched": len(pairs), "fresh": 0}

    projects = list_projects(user_id)
    project_slugs = {p["slug"] for p in projects}

    inserted = insert_raw_items(raw_to_insert)
    by_hash = {r["url_hash"]: r for r in inserted}
    raw_with_id = [by_hash[r["url_hash"]] for r in raw_to_insert if r["url_hash"] in by_hash]

    passed, rejected = _apply_pre_filter(raw_with_id, projects)

    if rejected:
        noise_rows = _build_noise_processed_rows(rejected, user_id)
        insert_processed_items(noise_rows)

    scored = await score_all(passed, projects)

    raw_id_lookup = {str(r["id"]): r for r in passed}
    processed_rows: list[dict[str, Any]] = []
    for sc in scored:
        rid = sc.raw_item_id
        if rid not in raw_id_lookup:
            continue
        row = to_processed_row(sc, user_id, UUID(rid), project_slugs)
        processed_rows.append(row)
    processed_rows = _apply_trend_tags(processed_rows, user_id)
    if processed_rows:
        insert_processed_items(processed_rows)

    selected, noise_count = build_digest(user_id)
    bot = Bot(token=settings.telegram_bot_token)
    digest_date = date.today()
    await send_digest(
        bot=bot,
        chat_id=settings.telegram_owner_id,
        user_id=user_id,
        digest_date=digest_date,
        items=selected,
        noise_count=noise_count + len(rejected),
    )

    stats = {
        "fetched": len(pairs),
        "fresh": len(raw_with_id),
        "pre_filter_passed": len(passed),
        "pre_filter_rejected": len(rejected),
        "scored": len(scored),
        "selected_for_digest": len(selected),
    }
    log.info("pipeline_done", **stats)
    return stats


async def main() -> None:
    settings = get_settings()
    settings.require_telegram()
    settings.require_supabase()
    settings.require_llm()
    await run_pipeline(settings.telegram_owner_id)


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(main())
