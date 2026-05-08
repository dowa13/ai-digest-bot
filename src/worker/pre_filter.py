"""Cheap regex-based pre-filter. Cuts roughly 60-70% of items before LLM scoring.

Builds an OR-regex from:
  - all keywords across the user's active projects (lowercased)
  - global AI keywords baseline

If neither title nor content matches, item is marked `is_noise=True` and the
LLM doesn't see it. Saves ~70% of Gemini budget.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

GLOBAL_AI_KEYWORDS: list[str] = [
    "ai", "ml", "llm", "gpt", "claude", "gemini", "openai", "anthropic",
    "deepmind", "huggingface", "transformer", "agent", "rag", "embedding",
    "fine-tune", "finetune", "prompt", "inference", "diffusion", "multimodal",
    "vision-language", "vlm", "ии", "нейросет", "промпт", "агент",
    "обучение модели", "обучение моделей", "генеративн", "open source model",
]


def build_pre_filter_regex(project_keywords: Iterable[str]) -> re.Pattern[str]:
    """Compile a case-insensitive OR-regex over project + global keywords."""
    all_kw: set[str] = set()
    for kw in project_keywords:
        kw = kw.strip().lower()
        if kw:
            all_kw.add(kw)
    for kw in GLOBAL_AI_KEYWORDS:
        all_kw.add(kw.strip().lower())

    if not all_kw:
        return re.compile(r"^$")

    escaped = sorted((re.escape(kw) for kw in all_kw), key=len, reverse=True)
    pattern = r"\b(?:" + "|".join(escaped) + r")\b"
    return re.compile(pattern, re.IGNORECASE | re.UNICODE)


def passes_pre_filter(text: str, regex: re.Pattern[str]) -> bool:
    if not text:
        return False
    return regex.search(text) is not None
