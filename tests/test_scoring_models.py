"""Pydantic validation of LLM-structured responses."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.shared.models import ScoreBatchResponse, ScoredItem


def test_valid_score_batch() -> None:
    payload = {
        "items": [
            {
                "raw_item_id": "abc",
                "tldr": "x",
                "summary": "y",
                "category": "release",
                "is_noise": False,
                "global_score": 70,
                "learning_value": 50,
                "project_scores": {"tf_market": 80},
                "topics": ["agents"],
                "reasoning": "z",
            }
        ]
    }
    parsed = ScoreBatchResponse.model_validate(payload)
    assert len(parsed.items) == 1
    assert parsed.items[0].project_scores["tf_market"] == 80


def test_global_score_out_of_range() -> None:
    with pytest.raises(ValidationError):
        ScoredItem.model_validate(
            {
                "raw_item_id": "x",
                "tldr": "x",
                "summary": "x",
                "category": "release",
                "global_score": 150,
            }
        )


def test_invalid_category() -> None:
    with pytest.raises(ValidationError):
        ScoredItem.model_validate(
            {
                "raw_item_id": "x",
                "tldr": "x",
                "summary": "x",
                "category": "weird",
                "global_score": 50,
            }
        )
