"""Telegram channel fetcher via the public web preview at https://t.me/s/{channel}.

We can't use the Bot API for this — those previews are how non-Bot scrapers
read public channels without a userbot session.

Skipped messages: pinned, media-only, anything < 100 chars.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from selectolax.parser import HTMLParser

from src.shared.logging import get_logger
from src.shared.models import RawItemDTO

from ._common import long_enough, make_client

log = get_logger(__name__)


def _channel_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    if "t.me" not in parsed.netloc:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return None
    if parts[0] == "s" and len(parts) >= 2:
        return parts[1]
    return parts[0]


async def fetch(source: dict[str, Any]) -> list[RawItemDTO]:
    channel = _channel_from_url(source["url"])
    if channel is None:
        log.warning("telegram_invalid_url", url=source["url"])
        return []

    preview_url = f"https://t.me/s/{channel}"
    async with make_client() as client:
        resp = await client.get(preview_url)
        resp.raise_for_status()
        html = resp.text

    tree = HTMLParser(html)
    items: list[RawItemDTO] = []

    for msg in tree.css(".tgme_widget_message"):
        if msg.css_first(".tgme_widget_message_pinned"):
            continue
        text_node = msg.css_first(".tgme_widget_message_text")
        if text_node is None:
            continue
        text = text_node.text(separator="\n").strip()
        if not long_enough(text):
            continue

        date_link = msg.css_first(".tgme_widget_message_date")
        if date_link is None:
            continue
        href = date_link.attributes.get("href")
        if not href:
            continue
        time_el = date_link.css_first("time")
        published_at: datetime | None = None
        if time_el is not None:
            dt_attr = time_el.attributes.get("datetime")
            if dt_attr:
                try:
                    published_at = datetime.fromisoformat(dt_attr.replace("Z", "+00:00"))
                except ValueError:
                    published_at = None

        title = text.split("\n", 1)[0][:200]
        items.append(
            RawItemDTO(
                url=href,
                title=title,
                content=text,
                published_at=published_at,
            )
        )

    log.info("telegram_fetched", channel=channel, count=len(items))
    return items
