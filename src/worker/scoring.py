"""Scoring step: send a batch of raw items + project profiles to the LLM.

Returns a list of `ScoredItem` we then persist into `processed_items`.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from src.shared.config import get_settings
from src.shared.llm import LLMQuotaError, parse_json_response
from src.shared.llm.factory import get_llm
from src.shared.logging import get_logger
from src.shared.models import ScoreBatchResponse, ScoredItem
from src.shared.prompts import load as load_prompt

log = get_logger(__name__)

# Groq free tier on llama-3.3-70b is 12K TPM — verified via x-ratelimit headers.
# Each batch must stay <~3.5K tokens total (input + output) so the 25s sleep
# is enough for replenishment. Trim content_max_chars below in lockstep.
_PROVIDER_BATCH_SIZE = {"groq": 8, "gemini": 10, "anthropic": 8}
_PROVIDER_INTER_BATCH_SLEEP = {"groq": 22.0, "gemini": 0.0, "anthropic": 0.0}
_PROVIDER_CONTENT_MAX_CHARS = {"groq": 350, "gemini": 1500, "anthropic": 800}

MIN_PROJECT_SCORE_MATCH = 60


def _provider_settings() -> tuple[int, float]:
    p = get_settings().llm_provider
    return _PROVIDER_BATCH_SIZE.get(p, 8), _PROVIDER_INTER_BATCH_SLEEP.get(p, 0.0)


def _content_max_chars() -> int:
    p = get_settings().llm_provider
    return _PROVIDER_CONTENT_MAX_CHARS.get(p, 800)


# Backwards-compat name (used in tests / docs).
BATCH_SIZE = 10


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


def _project_payload(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in projects:
        out.append(
            {
                "slug": p["slug"],
                "name": p["name"],
                "description": p.get("description") or "",
                "stack": p.get("stack") or "",
                "ai_use_cases": p.get("ai_use_cases") or {"high": [], "medium": [], "low": []},
                "keywords": p.get("keywords") or [],
                "anti_keywords": p.get("anti_keywords") or [],
            }
        )
    return out


def _items_payload(raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cmax = _content_max_chars()
    out: list[dict[str, Any]] = []
    for it in raw_items:
        out.append(
            {
                "raw_item_id": str(it["id"]),
                "url": it["url"],
                "title": _truncate(it.get("title") or "", 180),
                "content": _truncate(it.get("content") or "", cmax),
            }
        )
    return out


async def score_batch(
    raw_items: list[dict[str, Any]],
    projects: list[dict[str, Any]],
) -> list[ScoredItem]:
    if not raw_items:
        return []
    llm = get_llm()
    prompt = load_prompt("score")
    payload = json.dumps(
        {"projects": _project_payload(projects), "items": _items_payload(raw_items)},
        ensure_ascii=False,
    )
    try:
        resp = await llm.score_batch(system_prompt=prompt, user_payload=payload)
    except LLMQuotaError:
        log.error("scoring_skipped_quota", batch_size=len(raw_items))
        return []
    try:
        data = parse_json_response(resp.text)
        parsed = ScoreBatchResponse.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        log.error("scoring_parse_failed", error=str(exc), text_preview=resp.text[:300])
        return []
    return parsed.items


async def score_all(
    raw_items: list[dict[str, Any]],
    projects: list[dict[str, Any]],
) -> list[ScoredItem]:
    """Score all items in provider-tuned batches."""
    batch_size, inter_sleep = _provider_settings()
    out: list[ScoredItem] = []
    total_batches = (len(raw_items) + batch_size - 1) // batch_size
    for i in range(0, len(raw_items), batch_size):
        batch = raw_items[i : i + batch_size]
        scored = await score_batch(batch, projects)
        out.extend(scored)
        is_last = (i + batch_size) >= len(raw_items)
        if not is_last and inter_sleep > 0:
            log.info(
                "scoring_inter_batch_sleep",
                seconds=inter_sleep,
                progress=f"{i // batch_size + 1}/{total_batches}",
            )
            await asyncio.sleep(inter_sleep)
    return out


def to_processed_row(
    scored: ScoredItem,
    user_id: UUID,
    raw_item_id: UUID,
    project_slugs: set[str],
) -> dict[str, Any]:
    """Convert a ScoredItem into the payload we persist to `processed_items`."""
    matched = [
        slug
        for slug, val in scored.project_scores.items()
        if slug in project_slugs and val >= MIN_PROJECT_SCORE_MATCH
    ]
    return {
        "raw_item_id": str(raw_item_id),
        "user_id": str(user_id),
        "tldr": scored.tldr,
        "summary": scored.summary,
        "category": scored.category,
        "is_noise": scored.is_noise,
        "global_score": scored.global_score,
        "learning_value": scored.learning_value,
        "project_scores": scored.project_scores,
        "matched_projects": matched,
        "topics": scored.topics,
        "reasoning": scored.reasoning,
    }
