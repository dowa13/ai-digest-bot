"""Shared bits for fetchers — HTTP client, length filter, etc."""

from __future__ import annotations

import httpx

DEFAULT_TIMEOUT = 30.0
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36 ai-digest-bot/0.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
}

MIN_TEXT_LEN = 100


def make_client(*, timeout: float = DEFAULT_TIMEOUT) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout,
        headers=DEFAULT_HEADERS,
        follow_redirects=True,
    )


def long_enough(text: str) -> bool:
    return len(text.strip()) >= MIN_TEXT_LEN
