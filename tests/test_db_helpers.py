"""Tests for canonical_url / url_hash."""

from __future__ import annotations

from src.shared.db import canonical_url, url_hash


def test_canonical_url_strips_utm() -> None:
    raw = "https://example.com/post?utm_source=tw&utm_campaign=x&id=42"
    assert canonical_url(raw) == "https://example.com/post?id=42"


def test_canonical_url_strips_fbclid() -> None:
    raw = "https://Example.com/post?fbclid=abc&id=1"
    assert canonical_url(raw) == "https://example.com/post?id=1"


def test_canonical_url_normalises_host_case() -> None:
    raw = "https://EXAMPLE.com/foo"
    assert canonical_url(raw) == "https://example.com/foo"


def test_canonical_url_drops_fragment() -> None:
    raw = "https://example.com/foo#section"
    assert canonical_url(raw) == "https://example.com/foo"


def test_url_hash_is_stable_across_tracking_params() -> None:
    a = "https://example.com/post?utm_source=tw&id=42"
    b = "https://example.com/post?id=42"
    assert url_hash(a) == url_hash(b)


def test_url_hash_changes_for_different_paths() -> None:
    assert url_hash("https://example.com/a") != url_hash("https://example.com/b")
