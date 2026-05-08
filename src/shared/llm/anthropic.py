"""Anthropic stub implementation.

Not wired in MVP — `LLM_PROVIDER=anthropic` will instantiate this and raise
NotImplementedError so the failure is loud during migration. Filled in when
we move to Claude.

See `docs/migration_to_anthropic.md` for the migration plan.
"""

from __future__ import annotations

from src.shared.llm.base import LLMClient, LLMResponse


class AnthropicClient(LLMClient):
    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    async def score_batch(self, *, system_prompt: str, user_payload: str) -> LLMResponse:
        raise NotImplementedError("AnthropicClient.score_batch is not implemented yet")

    async def summarize(self, *, system_prompt: str, user_payload: str) -> LLMResponse:
        raise NotImplementedError("AnthropicClient.summarize is not implemented yet")

    async def chat(
        self,
        *,
        system_prompt: str,
        history: list[dict[str, str]],
        user_message: str,
    ) -> LLMResponse:
        raise NotImplementedError("AnthropicClient.chat is not implemented yet")

    async def deep_dive(
        self,
        *,
        system_prompt: str,
        user_payload: str,
        enable_web: bool = False,
    ) -> LLMResponse:
        raise NotImplementedError("AnthropicClient.deep_dive is not implemented yet")
