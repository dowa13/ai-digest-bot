"""Fetcher dispatch.

Each fetcher takes a `Source` row dict and returns `list[RawItemDTO]`.
Errors are caught at the dispatcher level — fetchers themselves can raise.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from src.shared.models import RawItemDTO

from . import github_trending, hf_papers, html_generic, rss, telegram_web

FetcherFn = Callable[[dict[str, Any]], Awaitable[list[RawItemDTO]]]

_REGISTRY: dict[str, FetcherFn] = {
    "rss": rss.fetch,
    "html": html_generic.fetch,
    "telegram": telegram_web.fetch,
    "hf_papers": hf_papers.fetch,
    "github_trending": github_trending.fetch,
}


def get_fetcher(kind: str) -> FetcherFn:
    if kind not in _REGISTRY:
        raise ValueError(f"unknown source kind: {kind}")
    return _REGISTRY[kind]
