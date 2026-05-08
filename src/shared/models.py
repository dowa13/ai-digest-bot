"""Pydantic models for DB rows, DTOs, and LLM-structured responses.

Keep these models tight — they double as the validation layer for LLM JSON.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ---------- Domain enums ----------

ItemCategory = Literal["release", "paper", "tool", "tutorial", "opinion", "noise"]
SourceKind = Literal["rss", "html", "telegram", "hf_papers", "github_trending"]
ReactionType = Literal[
    "like",
    "dislike",
    "wrong_project",
    "boring",
    "interested",
    "want_more_like_this",
    "save",
]
SyncStatus = Literal[
    "ok", "block_missing", "fetch_error", "parse_warning", "parse_error", "never"
]


# ---------- DB rows ----------


class User(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tg_user_id: int
    tg_username: str | None = None
    tz: str = "Europe/Vilnius"
    digest_time: time = time(8, 0)
    notion_root_page_id: str | None = None
    created_at: datetime


class Project(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    slug: str
    name: str
    notion_page_id: str | None = None
    description: str | None = None
    stack: str | None = None
    ai_use_cases: dict[str, list[str]] | None = None
    keywords: list[str] = Field(default_factory=list)
    anti_keywords: list[str] = Field(default_factory=list)
    is_active: bool = True
    last_synced_at: datetime | None = None
    sync_status: SyncStatus | None = None
    created_at: datetime


class Source(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: SourceKind
    url: str
    name: str
    lang: str
    is_active: bool = True
    last_fetched_at: datetime | None = None
    etag: str | None = None
    fail_count: int = 0


class RawItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    source_id: UUID
    url: str
    url_hash: str
    title: str | None = None
    content: str | None = None
    published_at: datetime | None = None
    fetched_at: datetime | None = None


class ProcessedItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    raw_item_id: UUID
    user_id: UUID
    tldr: str
    summary: str
    category: ItemCategory
    is_noise: bool = False
    global_score: int
    learning_value: int = 0
    project_scores: dict[str, int]
    matched_projects: list[str] = Field(default_factory=list)
    trend_tag: bool = False
    topics: list[str] = Field(default_factory=list)
    reasoning: str | None = None
    processed_at: datetime | None = None


class Digest(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    user_id: UUID
    digest_date: date
    tg_message_id: int | None = None
    item_ids: list[UUID]
    noise_filtered_count: int = 0
    created_at: datetime | None = None


class Feedback(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    processed_item_id: UUID
    reaction: ReactionType


class ChatMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    role: Literal["user", "assistant", "system"]
    content: str
    meta: dict[str, Any] | None = None


class UserPreferences(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    likes: list[str] = Field(default_factory=list)
    dislikes: list[str] = Field(default_factory=list)
    preferred_depth: Literal["concise", "balanced", "deep"] = "balanced"
    preferred_lang: list[str] = Field(default_factory=lambda: ["ru", "en"])


# ---------- LLM-facing structured responses ----------


class ScoredItem(BaseModel):
    """One element of the structured response from `score.md`."""

    raw_item_id: str
    tldr: str
    summary: str
    category: ItemCategory
    is_noise: bool = False
    global_score: int = Field(ge=0, le=100)
    learning_value: int = Field(ge=0, le=100, default=0)
    project_scores: dict[str, int] = Field(default_factory=dict)
    topics: list[str] = Field(default_factory=list)
    reasoning: str | None = None


class ScoreBatchResponse(BaseModel):
    items: list[ScoredItem]


class PreferencesPatch(BaseModel):
    """Output of `extract_prefs.md`. Only fields we are allowed to mutate."""

    add_likes: list[str] = Field(default_factory=list)
    add_dislikes: list[str] = Field(default_factory=list)
    deactivate_projects: list[str] = Field(default_factory=list)
    activate_projects: list[str] = Field(default_factory=list)
    preferred_depth: Literal["concise", "balanced", "deep"] | None = None


# ---------- Notion-side ----------


class AIUseCases(BaseModel):
    high: list[str] = Field(default_factory=list)
    medium: list[str] = Field(default_factory=list)
    low: list[str] = Field(default_factory=list)


class ProjectProfile(BaseModel):
    """Parsed result of the `## Профиль для AI-бота` block on a Notion page."""

    description: str | None = None
    stack: str | None = None
    ai_use_cases: AIUseCases = Field(default_factory=AIUseCases)
    keywords: list[str] = Field(default_factory=list)
    anti_keywords: list[str] = Field(default_factory=list)
    parse_warnings: list[str] = Field(default_factory=list)


class ParseError(BaseModel):
    status: SyncStatus
    message: str


class SyncResult(BaseModel):
    synced: int
    failed: int
    errors: list[dict[str, str]] = Field(default_factory=list)
    duration_ms: int = 0


# ---------- Fetcher DTOs ----------


class RawItemDTO(BaseModel):
    """What a fetcher returns. Persisted later as `RawItem`."""

    url: str
    title: str
    content: str
    published_at: datetime | None = None
