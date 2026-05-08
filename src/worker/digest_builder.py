"""Build the final digest list from processed items.

Selection rules:
- last 24h
- not noise
- (global_score ≥ 60) OR (max(project_score) ≥ 65) OR (learning_value ≥ 75)

Sort within a language pool: matched_projects DESC, trend_tag DESC,
max(global_score, learning_value) DESC.

Final selection targets a language ratio (default 6 RU + 2 EN of 8 items).
Falls back to filling from any pool if one is short.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from src.shared.db import list_processed_items_window
from src.shared.logging import get_logger

log = get_logger(__name__)

DIGEST_WINDOW_HOURS = 26  # generous: cron lag forgiveness
DIGEST_LIMIT = 8
RU_TARGET = 6
EN_TARGET = 2

MIN_GLOBAL = 60
MIN_PROJECT = 65
MIN_LEARNING = 75

_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")


def _is_russian_source(item: dict[str, Any]) -> bool:
    """Detect whether the source is Russian-language by inspecting the raw title.

    The `tldr` is always Russian (LLM translates), so we only inspect the
    untouched original `raw_items.title` for cyrillic characters.
    """
    raw = item.get("raw_items") or {}
    title = raw.get("title") or ""
    return bool(_CYRILLIC_RE.search(title))


def _qualifies(item: dict[str, Any]) -> bool:
    if item.get("is_noise"):
        return False
    if (item.get("global_score") or 0) >= MIN_GLOBAL:
        return True
    project_scores = item.get("project_scores") or {}
    if project_scores and max(project_scores.values()) >= MIN_PROJECT:
        return True
    return (item.get("learning_value") or 0) >= MIN_LEARNING


def _sort_key(item: dict[str, Any]) -> tuple[int, int, int]:
    matched = len(item.get("matched_projects") or [])
    trend = 1 if item.get("trend_tag") else 0
    score = max(item.get("global_score") or 0, item.get("learning_value") or 0)
    return (-matched, -trend, -score)


def build_digest(user_id: UUID) -> tuple[list[dict[str, Any]], int]:
    """Return (selected_items, noise_filtered_count) for the last 24h window.

    Implements RU/EN ratio targeting: takes top RU_TARGET from Russian sources
    and top EN_TARGET from English, then backfills from leftovers.
    """
    since = datetime.now(UTC) - timedelta(hours=DIGEST_WINDOW_HOURS)
    all_items = list_processed_items_window(user_id, since=since, include_noise=True)

    noise_count = sum(1 for it in all_items if it.get("is_noise"))
    candidates = [it for it in all_items if _qualifies(it)]
    candidates.sort(key=_sort_key)

    russian = [c for c in candidates if _is_russian_source(c)]
    english = [c for c in candidates if not _is_russian_source(c)]

    selected: list[dict[str, Any]] = []
    selected.extend(russian[:RU_TARGET])
    selected.extend(english[:EN_TARGET])

    # Backfill from leftovers if either pool was short.
    if len(selected) < DIGEST_LIMIT:
        used_ids = {it.get("id") for it in selected}
        for c in candidates:
            if c.get("id") in used_ids:
                continue
            selected.append(c)
            if len(selected) >= DIGEST_LIMIT:
                break

    selected.sort(key=_sort_key)
    selected = selected[:DIGEST_LIMIT]

    log.info(
        "digest_built",
        user_id=str(user_id),
        candidates=len(candidates),
        ru_pool=len(russian),
        en_pool=len(english),
        selected=len(selected),
        noise_filtered=noise_count,
    )
    return selected, noise_count
