"""Supabase client wrapper.

Thin layer over `supabase-py` so the rest of the code uses typed helpers
instead of poking at raw query builders. All writes use service_role.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from src.shared.config import get_settings
from src.shared.logging import get_logger
from supabase import Client, create_client

log = get_logger(__name__)


@lru_cache(maxsize=1)
def get_client() -> Client:
    settings = get_settings()
    settings.require_supabase()
    return create_client(settings.supabase_url, settings.supabase_service_key)


# ---------- Helpers ----------


_TRACKING_PARAM_PREFIXES = ("utm_", "mc_", "ref_", "fb_", "gc_")
_TRACKING_PARAMS_EXACT = {"fbclid", "gclid", "yclid", "mc_eid", "_hsenc", "_hsmi", "ref"}


def canonical_url(url: str) -> str:
    """Strip tracking params and normalise host for stable url_hash."""
    parts = urlsplit(url.strip())
    cleaned_query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k not in _TRACKING_PARAMS_EXACT
        and not any(k.startswith(p) for p in _TRACKING_PARAM_PREFIXES)
    ]
    cleaned = parts._replace(
        netloc=parts.netloc.lower(),
        fragment="",
        query=urlencode(cleaned_query),
    )
    return urlunsplit(cleaned)


def url_hash(url: str) -> str:
    return hashlib.sha256(canonical_url(url).encode("utf-8")).hexdigest()


# ---------- Users ----------


def upsert_user(tg_user_id: int, tg_username: str | None = None) -> dict[str, Any]:
    client = get_client()
    existing = (
        client.table("users").select("*").eq("tg_user_id", tg_user_id).limit(1).execute()
    )
    if existing.data:
        return existing.data[0]  # type: ignore[no-any-return]
    res = (
        client.table("users")
        .insert({"tg_user_id": tg_user_id, "tg_username": tg_username})
        .execute()
    )
    return res.data[0]  # type: ignore[no-any-return]


def get_user_by_tg_id(tg_user_id: int) -> dict[str, Any] | None:
    res = (
        get_client()
        .table("users")
        .select("*")
        .eq("tg_user_id", tg_user_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


# ---------- Projects ----------


def list_projects(user_id: UUID, only_active: bool = True) -> list[dict[str, Any]]:
    q = get_client().table("projects").select("*").eq("user_id", str(user_id))
    if only_active:
        q = q.eq("is_active", True)
    res = q.execute()
    return res.data or []


def update_project_profile(
    project_id: UUID,
    *,
    description: str | None,
    stack: str | None,
    ai_use_cases: dict[str, list[str]] | None,
    keywords: list[str],
    anti_keywords: list[str],
    sync_status: str,
) -> None:
    payload: dict[str, Any] = {
        "description": description,
        "stack": stack,
        "ai_use_cases": ai_use_cases,
        "keywords": keywords,
        "anti_keywords": anti_keywords,
        "sync_status": sync_status,
        "last_synced_at": datetime.now(UTC).isoformat(),
    }
    get_client().table("projects").update(payload).eq("id", str(project_id)).execute()


def update_project_sync_status(project_id: UUID, status: str) -> None:
    get_client().table("projects").update(
        {
            "sync_status": status,
            "last_synced_at": datetime.now(UTC).isoformat(),
        }
    ).eq("id", str(project_id)).execute()


def upsert_project_notion_id(user_id: UUID, slug: str, notion_page_id: str) -> None:
    get_client().table("projects").update(
        {"notion_page_id": notion_page_id}
    ).eq("user_id", str(user_id)).eq("slug", slug).execute()


# ---------- Sources ----------


def list_active_sources() -> list[dict[str, Any]]:
    res = get_client().table("sources").select("*").eq("is_active", True).execute()
    return res.data or []


def increment_source_fail(source_id: UUID) -> None:
    client = get_client()
    current = (
        client.table("sources")
        .select("fail_count")
        .eq("id", str(source_id))
        .single()
        .execute()
    )
    fc = (current.data or {}).get("fail_count", 0) + 1
    client.table("sources").update({"fail_count": fc}).eq("id", str(source_id)).execute()


def mark_source_fetched(source_id: UUID) -> None:
    get_client().table("sources").update(
        {
            "last_fetched_at": datetime.now(UTC).isoformat(),
            "fail_count": 0,
        }
    ).eq("id", str(source_id)).execute()


# ---------- Raw items ----------


_DB_BATCH = 100


def _sanitize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Strip null bytes and trim oversized fields before insert."""
    out = dict(row)
    for k in ("title", "content"):
        v = out.get(k)
        if isinstance(v, str):
            v = v.replace("\x00", "")
            if k == "title" and len(v) > 1000:
                v = v[:1000]
            elif k == "content" and len(v) > 20000:
                v = v[:20000]
            out[k] = v
    return out


def insert_raw_items(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Insert with on-conflict-do-nothing on url_hash. Batched + per-row fallback."""
    if not rows:
        return []
    cleaned = [_sanitize_row(r) for r in rows]
    out: list[dict[str, Any]] = []
    client = get_client()
    for i in range(0, len(cleaned), _DB_BATCH):
        chunk = cleaned[i : i + _DB_BATCH]
        try:
            res = client.table("raw_items").upsert(chunk, on_conflict="url_hash").execute()
            out.extend(res.data or [])
        except Exception as exc:
            log.warning("raw_items_batch_failed", batch_size=len(chunk), error=str(exc)[:300])
            for row in chunk:
                try:
                    res = client.table("raw_items").upsert([row], on_conflict="url_hash").execute()
                    out.extend(res.data or [])
                except Exception as inner:
                    log.warning("raw_item_skip", url=row.get("url"), error=str(inner)[:200])
    return out


def existing_url_hashes(hashes: list[str], days: int = 14) -> set[str]:
    if not hashes:
        return set()
    since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    found: set[str] = set()
    client = get_client()
    for i in range(0, len(hashes), _DB_BATCH):
        chunk = hashes[i : i + _DB_BATCH]
        res = (
            client.table("raw_items")
            .select("url_hash")
            .in_("url_hash", chunk)
            .gte("fetched_at", since)
            .execute()
        )
        for r in res.data or []:
            found.add(r["url_hash"])
    return found


# ---------- Processed items ----------


def insert_processed_items(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    out: list[dict[str, Any]] = []
    client = get_client()
    for i in range(0, len(rows), _DB_BATCH):
        chunk = rows[i : i + _DB_BATCH]
        try:
            res = client.table("processed_items").upsert(chunk, on_conflict="raw_item_id").execute()
            out.extend(res.data or [])
        except Exception as exc:
            log.warning("processed_items_batch_failed", batch_size=len(chunk), error=str(exc)[:300])
            for row in chunk:
                try:
                    res = client.table("processed_items").upsert([row], on_conflict="raw_item_id").execute()
                    out.extend(res.data or [])
                except Exception as inner:
                    log.warning("processed_item_skip", raw_item_id=row.get("raw_item_id"), error=str(inner)[:200])
    return out


def list_processed_items_window(
    user_id: UUID,
    *,
    since: datetime,
    until: datetime | None = None,
    include_noise: bool = False,
) -> list[dict[str, Any]]:
    q = (
        get_client()
        .table("processed_items")
        .select("*, raw_items(url, title, source_id)")
        .eq("user_id", str(user_id))
        .gte("processed_at", since.isoformat())
    )
    if until is not None:
        q = q.lt("processed_at", until.isoformat())
    if not include_noise:
        q = q.eq("is_noise", False)
    res = q.execute()
    return res.data or []


def get_processed_item(item_id: UUID) -> dict[str, Any] | None:
    res = (
        get_client()
        .table("processed_items")
        .select("*, raw_items(url, title, content)")
        .eq("id", str(item_id))
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


# ---------- Digests / briefs / landscapes ----------


def upsert_digest(
    user_id: UUID,
    digest_date: date,
    item_ids: list[UUID],
    noise_filtered_count: int,
    tg_message_id: int | None = None,
) -> dict[str, Any]:
    payload = {
        "user_id": str(user_id),
        "digest_date": digest_date.isoformat(),
        "item_ids": [str(i) for i in item_ids],
        "noise_filtered_count": noise_filtered_count,
    }
    if tg_message_id is not None:
        payload["tg_message_id"] = tg_message_id
    res = (
        get_client()
        .table("digests")
        .upsert(payload, on_conflict="user_id,digest_date")
        .execute()
    )
    return res.data[0]  # type: ignore[no-any-return]


def get_latest_digest(user_id: UUID) -> dict[str, Any] | None:
    res = (
        get_client()
        .table("digests")
        .select("*")
        .eq("user_id", str(user_id))
        .order("digest_date", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def insert_weekly_brief(
    user_id: UUID,
    period_start: date,
    period_end: date,
    content: str,
    item_ids: list[UUID],
) -> dict[str, Any]:
    payload = {
        "user_id": str(user_id),
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "content": content,
        "item_ids": [str(i) for i in item_ids],
    }
    res = (
        get_client()
        .table("weekly_briefs")
        .upsert(payload, on_conflict="user_id,period_start")
        .execute()
    )
    return res.data[0]  # type: ignore[no-any-return]


def get_latest_weekly(user_id: UUID) -> dict[str, Any] | None:
    res = (
        get_client()
        .table("weekly_briefs")
        .select("*")
        .eq("user_id", str(user_id))
        .order("period_start", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def insert_monthly_landscape(
    user_id: UUID,
    period_start: date,
    period_end: date,
    content: str,
) -> dict[str, Any]:
    payload = {
        "user_id": str(user_id),
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "content": content,
    }
    res = (
        get_client()
        .table("monthly_landscapes")
        .upsert(payload, on_conflict="user_id,period_start")
        .execute()
    )
    return res.data[0]  # type: ignore[no-any-return]


def get_latest_monthly(user_id: UUID) -> dict[str, Any] | None:
    res = (
        get_client()
        .table("monthly_landscapes")
        .select("*")
        .eq("user_id", str(user_id))
        .order("period_start", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


# ---------- Feedback / chat / preferences ----------


def insert_feedback(user_id: UUID, processed_item_id: UUID, reaction: str) -> None:
    get_client().table("feedback").insert(
        {
            "user_id": str(user_id),
            "processed_item_id": str(processed_item_id),
            "reaction": reaction,
        }
    ).execute()


def insert_chat_message(
    user_id: UUID, role: str, content: str, meta: dict[str, Any] | None = None
) -> None:
    payload: dict[str, Any] = {
        "user_id": str(user_id),
        "role": role,
        "content": content,
    }
    if meta is not None:
        payload["meta"] = meta
    get_client().table("chat_messages").insert(payload).execute()


def list_recent_chat_messages(user_id: UUID, limit: int = 20) -> list[dict[str, Any]]:
    res = (
        get_client()
        .table("chat_messages")
        .select("role, content, created_at")
        .eq("user_id", str(user_id))
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return list(reversed(res.data or []))


def get_user_preferences(user_id: UUID) -> dict[str, Any]:
    res = (
        get_client()
        .table("user_preferences")
        .select("*")
        .eq("user_id", str(user_id))
        .limit(1)
        .execute()
    )
    if res.data:
        return res.data[0]
    default = {"user_id": str(user_id)}
    get_client().table("user_preferences").insert(default).execute()
    return {**default, "likes": [], "dislikes": [], "preferred_depth": "balanced"}


def update_user_preferences(user_id: UUID, **kwargs: Any) -> None:
    payload = {**kwargs, "updated_at": datetime.now(UTC).isoformat()}
    get_client().table("user_preferences").update(payload).eq(
        "user_id", str(user_id)
    ).execute()


# ---------- Bot state ----------


def state_get(key: str, default: Any = None) -> Any:
    res = (
        get_client()
        .table("bot_state")
        .select("value")
        .eq("key", key)
        .limit(1)
        .execute()
    )
    if not res.data:
        return default
    return res.data[0].get("value", default)


def state_set(key: str, value: Any) -> None:
    payload = {
        "key": key,
        "value": value,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    get_client().table("bot_state").upsert(payload, on_conflict="key").execute()


# ---------- Sync log ----------


def insert_sync_log(
    user_id: UUID,
    triggered_by: str,
    status: str,
    projects_synced: int,
    errors: list[dict[str, str]] | None,
    duration_ms: int,
) -> None:
    get_client().table("sync_log").insert(
        {
            "user_id": str(user_id),
            "triggered_by": triggered_by,
            "status": status,
            "projects_synced": projects_synced,
            "errors": errors or [],
            "duration_ms": duration_ms,
        }
    ).execute()
