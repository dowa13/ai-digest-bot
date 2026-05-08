"""Tests for digest selection / sorting logic."""

from __future__ import annotations

from src.worker.digest_builder import _is_russian_source, _qualifies, _sort_key


def _item(**kw):
    base = {
        "is_noise": False,
        "global_score": 0,
        "learning_value": 0,
        "project_scores": {},
        "matched_projects": [],
        "trend_tag": False,
    }
    base.update(kw)
    return base


def test_qualifies_global_threshold() -> None:
    assert _qualifies(_item(global_score=60))
    assert not _qualifies(_item(global_score=59))


def test_qualifies_project_threshold() -> None:
    assert _qualifies(_item(project_scores={"x": 65}))
    assert not _qualifies(_item(project_scores={"x": 64}))


def test_qualifies_learning_value() -> None:
    assert _qualifies(_item(learning_value=75))
    assert not _qualifies(_item(learning_value=74))


def test_noise_never_qualifies() -> None:
    assert not _qualifies(_item(is_noise=True, global_score=99, learning_value=99))


def test_sort_priority() -> None:
    items = [
        _item(global_score=80),
        _item(matched_projects=["a"], project_scores={"a": 70}, global_score=60),
        _item(trend_tag=True, global_score=70),
    ]
    items.sort(key=_sort_key)
    assert items[0]["matched_projects"] == ["a"]
    assert items[1]["trend_tag"] is True
    assert items[2]["global_score"] == 80


def test_is_russian_source_detects_cyrillic_title() -> None:
    item = {"raw_items": {"title": "Новый релиз Anthropic"}}
    assert _is_russian_source(item)


def test_is_russian_source_returns_false_for_english_title() -> None:
    item = {"raw_items": {"title": "Anthropic releases new Claude"}}
    assert not _is_russian_source(item)


def test_is_russian_source_handles_missing_raw_items() -> None:
    assert not _is_russian_source({})
    assert not _is_russian_source({"raw_items": {}})
    assert not _is_russian_source({"raw_items": {"title": None}})
