"""Factory that picks the LLM provider based on env."""

from __future__ import annotations

from functools import lru_cache

from src.shared.config import get_settings
from src.shared.llm.anthropic import AnthropicClient
from src.shared.llm.base import LLMClient
from src.shared.llm.gemini import GeminiClient
from src.shared.llm.groq_client import GroqClient


@lru_cache(maxsize=1)
def get_llm() -> LLMClient:
    provider = get_settings().llm_provider
    if provider == "gemini":
        return GeminiClient()
    if provider == "groq":
        return GroqClient()
    if provider == "anthropic":
        return AnthropicClient()
    raise ValueError(f"unknown LLM_PROVIDER: {provider}")
