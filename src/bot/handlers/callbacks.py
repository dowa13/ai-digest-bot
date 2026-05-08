"""Callback query handlers — feedback buttons, action plans, deep dives."""

from __future__ import annotations

import json
from uuid import UUID

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from src.shared.config import get_settings
from src.shared.db import (
    get_processed_item,
    get_user_by_tg_id,
    insert_feedback,
    list_projects,
)
from src.shared.llm.factory import get_llm
from src.shared.logging import get_logger
from src.shared.notion_sync import NotionSyncService
from src.shared.prompts import load as load_prompt

log = get_logger(__name__)


REACTION_MAP = {
    "like": "like",
    "dislike": "dislike",
    "save": "save",
    "wrong_project": "wrong_project",
    "boring": "boring",
    "interested": "interested",
    "more": "want_more_like_this",
}


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return
    if update.effective_user is None or update.effective_user.id != get_settings().telegram_owner_id:
        await query.answer("Not for you.")
        return

    data = query.data
    parts = data.split(":")
    if not parts:
        await query.answer()
        return

    kind = parts[0]
    user = get_user_by_tg_id(update.effective_user.id)
    if user is None:
        await query.answer("Сначала /start")
        return
    user_id = UUID(user["id"])

    try:
        if kind == "fb" and len(parts) == 3:
            await _handle_feedback(query, user_id, parts[1], parts[2])
        elif kind == "plan" and len(parts) == 2:
            await _handle_plan(query, user_id, parts[1])
        elif kind == "learn" and len(parts) == 2:
            await _handle_learn(query, user_id, parts[1])
        elif kind == "project" and len(parts) >= 2 and parts[1] == "sync_all":
            await _handle_sync_all(query, user_id)
        else:
            await query.answer("OK")
    except Exception as exc:
        log.exception("callback_failed", data=data)
        await query.answer(f"Ошибка: {exc}", show_alert=True)


async def _handle_feedback(query, user_id: UUID, item_id: str, reaction_key: str) -> None:
    reaction = REACTION_MAP.get(reaction_key, reaction_key)
    insert_feedback(user_id, UUID(item_id), reaction)
    await query.answer({"like": "👍 учёл", "dislike": "👎 учёл", "save": "📌 сохранено"}.get(
        reaction, "ок"
    ))


async def _handle_plan(query, user_id: UUID, item_id: str) -> None:
    item = get_processed_item(UUID(item_id))
    if item is None:
        await query.answer("Айтем не найден", show_alert=True)
        return
    matched = item.get("matched_projects") or []
    if not matched:
        await query.answer("Этот айтем не привязан к проекту", show_alert=True)
        return

    projects = list_projects(user_id)
    matched_profiles = [p for p in projects if p["slug"] in matched]
    raw = item.get("raw_items") or {}

    payload = json.dumps(
        {
            "item": {
                "title": raw.get("title"),
                "url": raw.get("url"),
                "tldr": item.get("tldr"),
                "summary": item.get("summary"),
                "content": (raw.get("content") or "")[:2000],
            },
            "projects": [
                {
                    "slug": p["slug"],
                    "name": p["name"],
                    "description": p.get("description") or "",
                    "stack": p.get("stack") or "",
                    "ai_use_cases": p.get("ai_use_cases") or {},
                }
                for p in matched_profiles
            ],
        },
        ensure_ascii=False,
    )
    await query.answer("🔥 Готовлю план…")
    llm = get_llm()
    resp = await llm.summarize(system_prompt=load_prompt("action_plan"), user_payload=payload)
    await query.message.reply_text(resp.text, parse_mode=ParseMode.MARKDOWN)


async def _handle_learn(query, user_id: UUID, item_id: str) -> None:
    item = get_processed_item(UUID(item_id))
    if item is None:
        await query.answer("Айтем не найден", show_alert=True)
        return
    raw = item.get("raw_items") or {}
    payload = json.dumps(
        {
            "query": (raw.get("title") or item.get("tldr") or "")[:200],
            "history_items": [
                {
                    "url": raw.get("url"),
                    "title": raw.get("title"),
                    "tldr": item.get("tldr"),
                    "topics": item.get("topics") or [],
                }
            ],
            "projects": [],
        },
        ensure_ascii=False,
    )
    await query.answer("📚 Готовлю разбор…")
    llm = get_llm()
    resp = await llm.deep_dive(system_prompt=load_prompt("deep_dive"), user_payload=payload)
    await query.message.reply_text(resp.text, parse_mode=ParseMode.MARKDOWN)


async def _handle_sync_all(query, user_id: UUID) -> None:
    if not get_settings().notion_sync_enabled:
        await query.answer("Notion sync disabled in env", show_alert=True)
        return
    await query.answer("🔄 Синхронизирую…")
    service = NotionSyncService()
    result = await service.sync_all_projects(user_id, triggered_by="manual")
    text = f"Sync: {result.synced} ok, {result.failed} fail"
    await query.message.reply_text(text)
