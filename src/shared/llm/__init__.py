"""LLM provider package — provider-agnostic helpers."""

from __future__ import annotations

import json
from typing import Any

from src.shared.llm.base import LLMClient, LLMQuotaError, LLMResponse  # noqa: F401


def parse_json_response(text: str) -> Any:
    """Best-effort JSON extraction from any LLM provider's text output.

    Some providers wrap JSON in ```json fences even when JSON mode is set.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)
