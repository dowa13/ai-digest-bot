"""Centralised configuration loaded from environment.

All settings are validated at startup via Pydantic. Any missing required value
raises immediately, before the bot/worker starts processing.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration."""

    # LLM
    llm_provider: Literal["gemini", "groq", "anthropic"] = "gemini"
    gemini_api_key: str = ""
    gemini_model_fast: str = "gemini-2.0-flash"
    gemini_model_deep: str = "gemini-2.0-pro-exp"
    groq_api_key: str = ""
    groq_model_fast: str = "llama-3.3-70b-versatile"
    groq_model_deep: str = "llama-3.3-70b-versatile"
    anthropic_api_key: str = ""

    # Telegram
    telegram_bot_token: str = ""
    telegram_owner_id: int = 0

    # Supabase
    supabase_url: str = ""
    supabase_service_key: str = ""

    # Notion
    notion_api_key: str = ""
    notion_sync_enabled: bool = True

    # Misc
    env: Literal["development", "production"] = "production"
    log_level: str = "INFO"
    tz: str = "Europe/Vilnius"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, v: str) -> str:
        return v.upper()

    def require_gemini(self) -> None:
        if not self.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not set")

    def require_llm(self) -> None:
        """Validate the env var for the currently selected provider."""
        if self.llm_provider == "gemini":
            self.require_gemini()
        elif self.llm_provider == "groq" and not self.groq_api_key:
            raise RuntimeError("GROQ_API_KEY is not set")
        elif self.llm_provider == "anthropic" and not self.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")

    def require_telegram(self) -> None:
        if not self.telegram_bot_token or not self.telegram_owner_id:
            raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_OWNER_ID is not set")

    def require_supabase(self) -> None:
        if not self.supabase_url or not self.supabase_service_key:
            raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_KEY is not set")

    def require_notion(self) -> None:
        if not self.notion_api_key:
            raise RuntimeError("NOTION_API_KEY is not set")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor — single instance per process."""
    return Settings()
