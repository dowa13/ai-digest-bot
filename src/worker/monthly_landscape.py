"""Monthly landscape generator. Cron 1st of month, 8:00 local."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from telegram import Bot
from telegram.constants import ParseMode

from src.shared.config import get_settings
from src.shared.db import (
    get_client,
    get_user_by_tg_id,
    insert_monthly_landscape,
    list_processed_items_window,
    list_projects,
)
from src.shared.llm.factory import get_llm
from src.shared.logging import get_logger
from src.shared.prompts import load as load_prompt

log = get_logger(__name__)


def _list_recent_briefs(user_id: UUID, limit: int = 5) -> list[dict[str, Any]]:
    res = (
        get_client()
        .table("weekly_briefs")
        .select("period_start, period_end, content")
        .eq("user_id", str(user_id))
        .order("period_start", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


def _summarise_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for it in items[:200]:
        raw = it.get("raw_items") or {}
        out.append(
            {
                "url": raw.get("url"),
                "title": raw.get("title"),
                "tldr": it.get("tldr"),
                "topics": it.get("topics") or [],
                "matched_projects": it.get("matched_projects") or [],
                "global_score": it.get("global_score"),
            }
        )
    return out


async def generate_landscape(tg_user_id: int) -> str:
    user = get_user_by_tg_id(tg_user_id)
    if user is None:
        raise RuntimeError("no user")
    user_id = UUID(user["id"])

    period_end = date.today()
    period_start = period_end - timedelta(days=30)
    since = datetime.now(UTC) - timedelta(days=30)
    items = list_processed_items_window(user_id, since=since, include_noise=False)

    briefs = _list_recent_briefs(user_id, limit=5)
    projects = list_projects(user_id)
    project_brief = [
        {"slug": p["slug"], "name": p["name"], "description": p.get("description") or ""}
        for p in projects
    ]

    llm = get_llm()
    prompt = load_prompt("monthly")
    payload = json.dumps(
        {
            "period": {"start": period_start.isoformat(), "end": period_end.isoformat()},
            "projects": project_brief,
            "items": _summarise_items(items),
            "weekly_briefs": briefs,
        },
        ensure_ascii=False,
    )
    resp = await llm.deep_dive(system_prompt=prompt, user_payload=payload)
    content = resp.text.strip()

    insert_monthly_landscape(user_id, period_start, period_end, content)
    return content


async def send_landscape() -> None:
    settings = get_settings()
    settings.require_telegram()
    content = await generate_landscape(settings.telegram_owner_id)
    bot = Bot(token=settings.telegram_bot_token)
    chunks = _chunk_for_telegram(content)
    for chunk in chunks:
        await bot.send_message(
            chat_id=settings.telegram_owner_id,
            text=chunk,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )


def _chunk_for_telegram(text: str, max_len: int = 3500) -> list[str]:
    if len(text) <= max_len:
        return [text]
    parts: list[str] = []
    cur = ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > max_len:
            parts.append(cur)
            cur = line + "\n"
        else:
            cur += line + "\n"
    if cur:
        parts.append(cur)
    return parts


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(send_landscape())
