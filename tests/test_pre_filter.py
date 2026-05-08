"""Pre-filter regex tests."""

from __future__ import annotations

from src.worker.pre_filter import build_pre_filter_regex, passes_pre_filter


def test_passes_when_global_keyword_matches() -> None:
    regex = build_pre_filter_regex([])
    assert passes_pre_filter("Anthropic releases new Claude model", regex)
    assert passes_pre_filter("Новая нейросеть от OpenAI", regex)


def test_rejects_unrelated_text() -> None:
    regex = build_pre_filter_regex([])
    assert not passes_pre_filter("Recipe for sourdough bread", regex)


def test_project_keyword_lifts_match() -> None:
    regex = build_pre_filter_regex(["woocommerce", "remnawave"])
    assert passes_pre_filter("New WooCommerce extension released", regex)
    assert passes_pre_filter("Remnawave 2.0 changelog", regex)


def test_word_boundary_avoids_substring_false_positive() -> None:
    regex = build_pre_filter_regex([])
    assert not passes_pre_filter("aiport security upgrade in Helsinki", regex)
    # Should not falsely match because "ai" needs a word boundary; 'aiport' starts 'ai' but 'aiport' has no boundary
    # However our regex uses \b which treats letter-letter as in-word. Confirm:
    # 'aiport' = a-i-p-o-r-t — \bai\b requires non-word after 'i', but 'p' is word char, so no match.


def test_empty_text_returns_false() -> None:
    regex = build_pre_filter_regex(["x"])
    assert not passes_pre_filter("", regex)
