"""RSS / Atom fetcher via feedparser."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import feedparser

from src.shared.logging import get_logger
from src.shared.models import RawItemDTO

from ._common import long_enough, make_client

log = get_logger(__name__)


async def fetch(source: dict[str, Any]) -> list[RawItemDTO]:
    url = source["url"]
    async with make_client() as client:
        resp = await client.get(url)
        resp.raise_for_status()
        body = resp.text

    parsed = await asyncio.to_thread(feedparser.parse, body)
    items: list[RawItemDTO] = []
    for entry in parsed.entries[:50]:
        link = entry.get("link") or ""
        title = (entry.get("title") or "").strip()
        content = _extract_content(entry)
        if not link or not title:
            continue
        if not long_enough(title + " " + content):
            continue
        items.append(
            RawItemDTO(
                url=link,
                title=title,
                content=content,
                published_at=_parse_date(entry),
            )
        )
    log.info("rss_fetched", source=source.get("name"), count=len(items))
    return items


def _extract_content(entry: Any) -> str:
    if "content" in entry and entry.content:
        c = entry.content[0].get("value", "")
        if c:
            return c
    if "summary" in entry and entry.summary:
        return entry.summary
    if "description" in entry:
        return entry.description
    return ""


def _parse_date(entry: Any) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        val = entry.get(key)
        if val:
            try:
                return datetime(*val[:6], tzinfo=UTC)
            except (TypeError, ValueError):
                continue
    return None
