"""Weekly brief generator. Cron Sunday 16:00 UTC."""

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
    get_user_by_tg_id,
    insert_weekly_brief,
    list_processed_items_window,
    list_projects,
)
from src.shared.llm.factory import get_llm
from src.shared.logging import get_logger
from src.shared.prompts import load as load_prompt
from src.worker.trend_tracker import topic_delta

log = get_logger(__name__)


def _summarise_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for it in items[:80]:
        raw = it.get("raw_items") or {}
        out.append(
            {
                "id": str(it["id"]),
                "url": raw.get("url"),
                "title": raw.get("title"),
                "tldr": it.get("tldr"),
                "topics": it.get("topics") or [],
                "global_score": it.get("global_score"),
                "learning_value": it.get("learning_value"),
                "matched_projects": it.get("matched_projects") or [],
            }
        )
    return out


async def generate_brief(tg_user_id: int) -> str:
    user = get_user_by_tg_id(tg_user_id)
    if user is None:
        raise RuntimeError("no user")
    user_id = UUID(user["id"])

    period_end = date.today()
    period_start = period_end - timedelta(days=7)
    since = datetime.now(UTC) - timedelta(days=7)
    items = list_processed_items_window(user_id, since=since, include_noise=False)

    delta = topic_delta(user_id, days=7, prev_days=7)
    top_delta = sorted(
        ((t, this, prev) for t, (this, prev) in delta.items()),
        key=lambda x: -x[1],
    )[:10]

    projects = list_projects(user_id)
    project_brief = [
        {"slug": p["slug"], "name": p["name"], "description": p.get("description") or ""}
        for p in projects
    ]

    llm = get_llm()
    web_query = f"major AI events week of {period_start.isoformat()}"
    try:
        web_resp = await llm.deep_dive(
            system_prompt="Summarize major AI events of the week. Plain bullet list, ≤ 200 words.",
            user_payload=web_query,
            enable_web=True,
        )
        calibration = web_resp.text
    except Exception as exc:  # pragma: no cover
        log.warning("calibration_search_failed", error=str(exc))
        calibration = ""

    prompt = load_prompt("weekly")
    payload = json.dumps(
        {
            "period": {"start": period_start.isoformat(), "end": period_end.isoformat()},
            "projects": project_brief,
            "items": _summarise_items(items),
            "topic_delta": [
                {"topic": t, "this_week": this, "prev_week": prev}
                for t, this, prev in top_delta
            ],
            "calibration_search": calibration,
        },
        ensure_ascii=False,
    )
    resp = await llm.deep_dive(system_prompt=prompt, user_payload=payload)
    content = resp.text.strip()

    item_ids = [UUID(it["id"]) for it in items]
    insert_weekly_brief(user_id, period_start, period_end, content, item_ids)
    return content


async def send_brief() -> None:
    settings = get_settings()
    settings.require_telegram()
    content = await generate_brief(settings.telegram_owner_id)
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
    asyncio.run(send_brief())
