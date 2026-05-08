"""Markdown V2 escaping tests."""

from __future__ import annotations

from src.worker.digest_sender import md_escape


def test_escape_dot() -> None:
    assert md_escape("v2.0") == "v2\\.0"


def test_escape_brackets_and_parens() -> None:
    assert md_escape("[hi](there)") == "\\[hi\\]\\(there\\)"


def test_escape_underscore_and_star() -> None:
    assert md_escape("_bold_*") == "\\_bold\\_\\*"


def test_passthrough_plain_text() -> None:
    assert md_escape("hello world") == "hello world"
