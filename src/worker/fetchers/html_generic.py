"""Generic HTML scraper for blogs that don't expose an RSS feed.

This is intentionally simple — it pulls headings + first link out of the page
body. For sites with a known structure (Anthropic news, GitHub trending) we
have a dedicated fetcher.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from src.shared.logging import get_logger
from src.shared.models import RawItemDTO

from ._common import long_enough, make_client

log = get_logger(__name__)


_ARTICLE_SELECTORS = [
    "article a[href]",
    ".post-card a[href]",
    ".article-card a[href]",
    "h2 a[href]",
    "h3 a[href]",
]


async def fetch(source: dict[str, Any]) -> list[RawItemDTO]:
    base_url = source["url"]
    async with make_client() as client:
        resp = await client.get(base_url)
        resp.raise_for_status()
        html = resp.text

    tree = HTMLParser(html)
    seen_links: set[str] = set()
    items: list[RawItemDTO] = []

    for selector in _ARTICLE_SELECTORS:
        for node in tree.css(selector):
            href = node.attributes.get("href")
            if not href:
                continue
            url = urljoin(base_url, href)
            if url in seen_links:
                continue
            title = (node.text() or "").strip()
            if not long_enough(title):
                continue
            seen_links.add(url)
            items.append(RawItemDTO(url=url, title=title, content=title))
            if len(items) >= 30:
                break
        if items:
            break

    log.info("html_fetched", source=source.get("name"), count=len(items))
    return items
