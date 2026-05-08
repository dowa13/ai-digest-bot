"""Tests for Telegram t.me/s parser."""

from __future__ import annotations

from src.worker.fetchers.telegram_web import _channel_from_url


def test_channel_from_normal_url() -> None:
    assert _channel_from_url("https://t.me/seeallochnaya") == "seeallochnaya"


def test_channel_from_s_url() -> None:
    assert _channel_from_url("https://t.me/s/ai_newz") == "ai_newz"


def test_channel_from_invalid_returns_none() -> None:
    assert _channel_from_url("https://example.com") is None
    assert _channel_from_url("https://t.me/") is None
