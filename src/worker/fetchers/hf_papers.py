"""HuggingFace daily papers — https://huggingface.co/papers."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from src.shared.logging import get_logger
from src.shared.models import RawItemDTO

from ._common import long_enough, make_client

log = get_logger(__name__)

BASE = "https://huggingface.co"


async def fetch(source: dict[str, Any]) -> list[RawItemDTO]:
    async with make_client() as client:
        resp = await client.get(source["url"])
        resp.raise_for_status()
        html = resp.text

    tree = HTMLParser(html)
    items: list[RawItemDTO] = []
    seen: set[str] = set()

    for link in tree.css("a[href^='/papers/']"):
        href = link.attributes.get("href")
        if not href or "/papers/" not in href or href.endswith("/papers"):
            continue
        url = urljoin(BASE, href)
        if url in seen:
            continue
        title = (link.text() or "").strip()
        if not long_enough(title):
            continue
        seen.add(url)
        items.append(RawItemDTO(url=url, title=title, content=title))

    log.info("hf_papers_fetched", count=len(items))
    return items
