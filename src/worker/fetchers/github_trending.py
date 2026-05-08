"""GitHub trending — https://github.com/trending/python?since=daily etc."""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from src.shared.logging import get_logger
from src.shared.models import RawItemDTO

from ._common import make_client

log = get_logger(__name__)

BASE = "https://github.com"


async def fetch(source: dict[str, Any]) -> list[RawItemDTO]:
    async with make_client() as client:
        resp = await client.get(source["url"])
        resp.raise_for_status()
        html = resp.text

    tree = HTMLParser(html)
    items: list[RawItemDTO] = []

    for repo in tree.css("article.Box-row"):
        title_link = repo.css_first("h2 a")
        if title_link is None:
            continue
        href = title_link.attributes.get("href")
        if not href:
            continue
        url = urljoin(BASE, href)
        repo_path = href.strip("/")
        desc_node = repo.css_first("p")
        desc = (desc_node.text() if desc_node else "").strip()
        title = repo_path
        content = f"{repo_path} — {desc}" if desc else repo_path
        if len(content) < 20:
            continue
        items.append(RawItemDTO(url=url, title=title, content=content))

    log.info("github_trending_fetched", count=len(items))
    return items
