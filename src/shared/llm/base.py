"""LLM provider abstraction.

The bot must NEVER call a provider SDK directly — go through `LLMClient`
so we can swap Gemini for Anthropic without touching downstream code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


class LLMQuotaError(Exception):
    """Raised by any provider when quota / rate-limit blocks the call.

    Pipeline catches this to skip remaining batches gracefully instead of
    crashing the whole run.
    """


@dataclass(slots=True)
class LLMResponse:
    text: str
    model: str
    input_chars: int
    output_chars: int
    latency_ms: int
    raw: Any | None = None


class LLMClient(ABC):
    """Provider-agnostic interface."""

    @abstractmethod
    async def score_batch(
        self, *, system_prompt: str, user_payload: str
    ) -> LLMResponse:
        """Cheap fast model — used for scoring batch of raw items."""

    @abstractmethod
    async def summarize(
        self, *, system_prompt: str, user_payload: str
    ) -> LLMResponse:
        """Cheap fast model — short summaries, action plans."""

    @abstractmethod
    async def chat(
        self,
        *,
        system_prompt: str,
        history: list[dict[str, str]],
        user_message: str,
    ) -> LLMResponse:
        """Cheap fast model — conversational replies."""

    @abstractmethod
    async def deep_dive(
        self,
        *,
        system_prompt: str,
        user_payload: str,
        enable_web: bool = False,
    ) -> LLMResponse:
        """Deeper / slower model — weekly brief, /learn, monthly landscape."""
