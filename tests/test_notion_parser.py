"""Parser unit tests using fixtures with various Notion block formats."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.shared.models import ParseError, ProjectProfile
from src.shared.notion_sync import NotionProjectParser

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_full_profile_parses_cleanly() -> None:
    blocks = _load("notion_full.json")
    result = NotionProjectParser.parse_blocks(blocks)
    assert isinstance(result, ProjectProfile)
    assert result.description and "WordPress" in result.description
    assert result.stack and "WooCommerce" in result.stack
    assert "ecommerce" in result.keywords
    assert "crypto" in result.anti_keywords
    assert "товарные описания" in result.ai_use_cases.high[0]
    assert "SEO-генерация" in result.ai_use_cases.medium[0]
    assert "видеоконтент" in result.ai_use_cases.low[0]
    assert result.parse_warnings == []


def test_sloppy_profile_parses_with_warnings() -> None:
    blocks = _load("notion_sloppy.json")
    result = NotionProjectParser.parse_blocks(blocks)
    assert isinstance(result, ProjectProfile)
    assert result.description and "VPN" in result.description
    assert result.stack and "Remnawave" in result.stack
    assert "vpn" in result.keywords
    assert "anti-fraud" in result.keywords
    assert "антифрод" in result.ai_use_cases.high[0]
    assert "голосовой саппорт" in result.ai_use_cases.low[0]


def test_missing_block_returns_error() -> None:
    blocks = _load("notion_missing_block.json")
    result = NotionProjectParser.parse_blocks(blocks)
    assert isinstance(result, ParseError)
    assert result.status == "block_missing"


def test_empty_section_yields_warnings() -> None:
    blocks = [
        {"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "Профиль для AI-бота"}]}},
        {"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "Задачи"}]}},
    ]
    result = NotionProjectParser.parse_blocks(blocks)
    assert isinstance(result, ProjectProfile)
    assert "description missing" in result.parse_warnings
    assert "keywords missing or empty" in result.parse_warnings


@pytest.mark.parametrize(
    "key_form",
    [
        "**Описание**:",
        "**Описание:**",
        "Описание:",
        "**Описание** :",
    ],
)
def test_lenient_field_separator(key_form: str) -> None:
    blocks = [
        {"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "Профиль для AI-бота"}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": f"{key_form} магазин"}]}},
        {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "**Keywords**: x"}]}},
    ]
    result = NotionProjectParser.parse_blocks(blocks)
    assert isinstance(result, ProjectProfile)
    assert result.description == "магазин"
