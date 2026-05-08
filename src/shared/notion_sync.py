"""Notion → DB synchroniser for project profiles.

Each user's project page in Notion is expected to contain a section like:

    ## Профиль для AI-бота

    **Описание**: ...

    **Стек**: ...

    **AI-направления:**
    - HIGH: ...
    - MEDIUM: ...
    - LOW: ...

    **Keywords**: ai, ml, ...

    **Anti-keywords**: crypto, ...

We parse just that section and ignore the rest of the page (which is for the
human). The parser is intentionally lenient — we accept variations in
punctuation and case so users don't have to be pixel-perfect.

Runtime bot/worker code MUST NEVER import this module — only `scripts/sync_projects.py`
calls it. If Notion is down, the bot keeps working off the last sync.
"""

from __future__ import annotations

import asyncio
import re
import time as _time
from typing import Any
from uuid import UUID

from notion_client import AsyncClient
from notion_client.errors import APIResponseError

from src.shared.config import get_settings
from src.shared.db import (
    increment_source_fail,  # noqa: F401  # re-export anchor for completeness
    insert_sync_log,
    list_projects,
    update_project_profile,
    update_project_sync_status,
)
from src.shared.logging import get_logger
from src.shared.models import (
    AIUseCases,
    ParseError,
    ProjectProfile,
    SyncResult,
)

log = get_logger(__name__)

PROFILE_HEADING = "Профиль для AI-бота"
NOTION_RPS_DELAY = 0.4  # 3 req/s with safety margin


# ---------- Block helpers ----------


def _rich_text(block: dict[str, Any], key: str) -> str:
    rich = block.get(key, {}).get("rich_text", [])
    return "".join(part.get("plain_text", "") for part in rich)


def _block_text(block: dict[str, Any]) -> str:
    """Best-effort plain text for any supported block type."""
    btype = block.get("type")
    if btype is None:
        return ""
    return _rich_text(block, btype)


# ---------- Parser ----------


def _strip_md_markers(text: str) -> str:
    """Strip leading/trailing `*` and whitespace; collapse internal whitespace."""
    return text.strip().strip("*").strip()


def _split_field_line(text: str) -> tuple[str, str] | None:
    """Try to interpret `text` as a `Key: Value` line, lenient about `**` markers.

    Examples that should all parse to ('Описание', 'магазин'):
      - `**Описание**: магазин`
      - `**Описание:** магазин`
      - `Описание : магазин`
      - `**Описание** : магазин`
    """
    raw = text.strip()
    if not raw:
        return None
    for sep in (":", "："):
        idx = raw.find(sep)
        if idx > 0:
            key = _strip_md_markers(raw[:idx])
            value = _strip_md_markers(raw[idx + 1 :])
            if key:
                return key, value
    return None


def _normalise_key(key: str) -> str:
    k = key.strip().lower()
    if k.startswith("описание"):
        return "description"
    if k.startswith("стек") or k == "stack":
        return "stack"
    if "ai-направ" in k or "ai направ" in k or k.startswith("ai use"):
        return "ai_use_cases"
    if k == "keywords" or k.startswith("ключев"):
        return "keywords"
    if "anti" in k:
        return "anti_keywords"
    return k


def _split_csv(value: str) -> list[str]:
    return [p.strip() for p in value.replace(";", ",").split(",") if p.strip()]


_BUCKET_RE = re.compile(r"^\s*(HIGH|MEDIUM|LOW)\s*[:：]\s*(.+)$", re.IGNORECASE)


def _parse_bucket_line(text: str) -> tuple[str, list[str]] | None:
    m = _BUCKET_RE.match(text.strip())
    if not m:
        return None
    bucket = m.group(1).lower()
    items = _split_csv(m.group(2))
    return bucket, items


class NotionProjectParser:
    """Parses the `## Профиль для AI-бота` block from a Notion page."""

    def __init__(self, client: AsyncClient | None = None) -> None:
        settings = get_settings()
        if client is None:
            settings.require_notion()
            client = AsyncClient(auth=settings.notion_api_key)
        self._client = client

    async def fetch_blocks(self, page_id: str) -> list[dict[str, Any]]:
        """Pull all blocks under a page, paginated."""
        blocks: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            kwargs: dict[str, Any] = {"block_id": page_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            res = await self._client.blocks.children.list(**kwargs)
            blocks.extend(res.get("results", []))
            if not res.get("has_more"):
                break
            cursor = res.get("next_cursor")
            await asyncio.sleep(NOTION_RPS_DELAY)
        return blocks

    async def parse_page(self, page_id: str) -> ProjectProfile | ParseError:
        try:
            blocks = await self.fetch_blocks(page_id)
        except APIResponseError as exc:
            log.warning("notion_fetch_error", page_id=page_id, code=exc.code)
            return ParseError(status="fetch_error", message=str(exc))
        except Exception as exc:  # pragma: no cover
            log.warning("notion_fetch_error_generic", page_id=page_id, error=str(exc))
            return ParseError(status="fetch_error", message=str(exc))

        return self.parse_blocks(blocks)

    @staticmethod
    def parse_blocks(blocks: list[dict[str, Any]]) -> ProjectProfile | ParseError:
        """Pure-function parser — easy to unit-test with fixtures."""
        section = _slice_profile_section(blocks)
        if section is None:
            return ParseError(status="block_missing", message=f"'{PROFILE_HEADING}' heading not found")

        profile = ProjectProfile()
        warnings: list[str] = []

        i = 0
        while i < len(section):
            blk = section[i]
            text = _block_text(blk).strip()
            btype = blk.get("type")

            if not text and btype not in ("bulleted_list_item", "numbered_list_item"):
                i += 1
                continue

            kv = _split_field_line(text) if text else None
            if kv:
                raw_key, value = kv
                key = _normalise_key(raw_key)

                if key == "description":
                    profile.description = value or None
                elif key == "stack":
                    profile.stack = value or None
                elif key == "keywords":
                    profile.keywords = _split_csv(value)
                elif key == "anti_keywords":
                    profile.anti_keywords = _split_csv(value)
                elif key == "ai_use_cases":
                    j = i + 1
                    buckets = AIUseCases()
                    while j < len(section) and section[j].get("type") in (
                        "bulleted_list_item",
                        "numbered_list_item",
                    ):
                        line_text = _block_text(section[j]).strip()
                        parsed = _parse_bucket_line(line_text)
                        if parsed:
                            bucket, items = parsed
                            current = getattr(buckets, bucket)
                            current.extend(items)
                        j += 1
                    profile.ai_use_cases = buckets
                    i = j
                    continue
                else:
                    pass
            i += 1

        if profile.description is None:
            warnings.append("description missing")
        if not profile.keywords:
            warnings.append("keywords missing or empty")
        if not (
            profile.ai_use_cases.high
            or profile.ai_use_cases.medium
            or profile.ai_use_cases.low
        ):
            warnings.append("ai_use_cases missing or empty")

        profile.parse_warnings = warnings
        return profile


def _slice_profile_section(blocks: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """Return the blocks between the profile heading and the next heading_2."""
    start: int | None = None
    end: int | None = None
    for idx, blk in enumerate(blocks):
        btype = blk.get("type")
        text = _block_text(blk).strip()
        if start is None:
            if btype == "heading_2" and PROFILE_HEADING.lower() in text.lower():
                start = idx + 1
            continue
        if btype == "heading_2":
            end = idx
            break
    if start is None:
        return None
    return blocks[start : end if end is not None else len(blocks)]


# ---------- Service ----------


class NotionSyncService:
    """Sync all projects of a given user from Notion to DB."""

    def __init__(self, parser: NotionProjectParser | None = None) -> None:
        self._parser = parser or NotionProjectParser()

    async def sync_all_projects(
        self, user_id: UUID, triggered_by: str = "manual"
    ) -> SyncResult:
        start = _time.monotonic()
        rows = list_projects(user_id, only_active=False)
        synced = 0
        failed = 0
        errors: list[dict[str, str]] = []

        for row in rows:
            slug = row["slug"]
            page_id = (row.get("notion_page_id") or "").strip()
            if not page_id:
                continue
            try:
                result = await self._parser.parse_page(page_id)
            except Exception as exc:  # pragma: no cover
                failed += 1
                errors.append({"slug": slug, "error": f"unhandled: {exc}"})
                update_project_sync_status(UUID(row["id"]), "fetch_error")
                continue

            if isinstance(result, ParseError):
                failed += 1
                errors.append({"slug": slug, "error": result.status})
                update_project_sync_status(UUID(row["id"]), result.status)
                continue

            sync_status = "ok" if not result.parse_warnings else "parse_warning"
            ai_use_cases_dict = (
                {
                    "high": result.ai_use_cases.high,
                    "medium": result.ai_use_cases.medium,
                    "low": result.ai_use_cases.low,
                }
                if result.ai_use_cases
                else None
            )
            update_project_profile(
                UUID(row["id"]),
                description=result.description,
                stack=result.stack,
                ai_use_cases=ai_use_cases_dict,
                keywords=result.keywords,
                anti_keywords=result.anti_keywords,
                sync_status=sync_status,
            )
            synced += 1
            await asyncio.sleep(NOTION_RPS_DELAY)

        duration_ms = int((_time.monotonic() - start) * 1000)
        if failed == 0 and synced > 0:
            status = "success"
        elif synced > 0:
            status = "partial"
        else:
            status = "fail"

        insert_sync_log(
            user_id=user_id,
            triggered_by=triggered_by,
            status=status,
            projects_synced=synced,
            errors=errors,
            duration_ms=duration_ms,
        )
        return SyncResult(synced=synced, failed=failed, errors=errors, duration_ms=duration_ms)
