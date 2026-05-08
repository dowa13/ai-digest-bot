"""Free-form chat handler.

Loads recent history, fresh project profiles, fresh user_preferences, and
asks the LLM. In parallel, the message is also fed to extract_prefs to update
user preferences.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from telegram import Update
from telegram.ext import ContextTypes

from src.bot.handlers.commands import set_notion_id
from src.shared.config import get_settings
from src.shared.db import (
    get_user_by_tg_id,
    get_user_preferences,
    insert_chat_message,
    list_projects,
    list_recent_chat_messages,
    update_user_preferences,
)
from src.shared.llm import parse_json_response
from src.shared.llm.factory import get_llm
from src.shared.logging import get_logger
from src.shared.models import PreferencesPatch
from src.shared.prompts import load as load_prompt

log = get_logger(__name__)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user is None:
        return
    if update.effective_user.id != get_settings().telegram_owner_id:
        return
    if update.message is None or not update.message.text:
        return

    if await set_notion_id(update, context):
        return

    user = get_user_by_tg_id(update.effective_user.id)
    if user is None:
        return
    user_id = UUID(user["id"])

    user_text = update.message.text.strip()
    insert_chat_message(user_id, "user", user_text)

    history_rows = list_recent_chat_messages(user_id, limit=20)
    projects = list_projects(user_id)
    prefs = get_user_preferences(user_id)

    await update.message.chat.send_action("typing")

    reply_task = asyncio.create_task(
        _generate_reply(user_id, user_text, history_rows, projects, prefs)
    )
    prefs_task = asyncio.create_task(
        _extract_and_apply_prefs(user_id, user_text, [p["slug"] for p in projects])
    )
    reply, _ = await asyncio.gather(reply_task, prefs_task, return_exceptions=False)

    insert_chat_message(user_id, "assistant", reply)
    await update.message.reply_text(reply)


async def _generate_reply(
    user_id: UUID,
    user_text: str,
    history_rows: list[dict[str, Any]],
    projects: list[dict[str, Any]],
    prefs: dict[str, Any],
) -> str:
    history = [
        {"role": r.get("role"), "content": r.get("content") or ""}
        for r in history_rows[:-1]
    ]

    project_brief = [
        {
            "slug": p["slug"],
            "name": p["name"],
            "description": p.get("description") or "",
            "is_active": p.get("is_active"),
        }
        for p in projects
    ]
    context_block = (
        "USER CONTEXT:\n"
        f"projects: {json.dumps(project_brief, ensure_ascii=False)}\n"
        f"likes: {prefs.get('likes') or []}\n"
        f"dislikes: {prefs.get('dislikes') or []}\n"
        f"preferred_depth: {prefs.get('preferred_depth') or 'balanced'}\n"
    )
    system_prompt = load_prompt("chat") + "\n\n" + context_block

    llm = get_llm()
    resp = await llm.chat(
        system_prompt=system_prompt,
        history=history,
        user_message=user_text,
    )
    return resp.text.strip()


async def _extract_and_apply_prefs(
    user_id: UUID, user_text: str, project_slugs: list[str]
) -> None:
    payload = json.dumps(
        {"user_message": user_text, "project_slugs": project_slugs},
        ensure_ascii=False,
    )
    try:
        llm = get_llm()
        resp = await llm.summarize(
            system_prompt=load_prompt("extract_prefs"),
            user_payload=payload,
        )
        data = parse_json_response(resp.text)
        patch = PreferencesPatch.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        log.warning("extract_prefs_parse_failed", error=str(exc))
        return
    except Exception as exc:
        log.warning("extract_prefs_failed", error=str(exc))
        return

    if not any(
        [
            patch.add_likes,
            patch.add_dislikes,
            patch.deactivate_projects,
            patch.activate_projects,
            patch.preferred_depth,
        ]
    ):
        return

    prefs = get_user_preferences(user_id)
    likes = list(set((prefs.get("likes") or []) + patch.add_likes))
    dislikes = list(set((prefs.get("dislikes") or []) + patch.add_dislikes))
    update_kwargs: dict[str, Any] = {"likes": likes, "dislikes": dislikes}
    if patch.preferred_depth:
        update_kwargs["preferred_depth"] = patch.preferred_depth
    update_user_preferences(user_id, **update_kwargs)

    if patch.deactivate_projects or patch.activate_projects:
        from src.shared.db import get_client
        client = get_client()
        for slug in patch.deactivate_projects:
            client.table("projects").update({"is_active": False}).eq(
                "user_id", str(user_id)
            ).eq("slug", slug).execute()
        for slug in patch.activate_projects:
            client.table("projects").update({"is_active": True}).eq(
                "user_id", str(user_id)
            ).eq("slug", slug).execute()
