r"""Render and send the daily digest to Telegram.

Markdown V2 escape rules: every literal `_*[]()~\`>#+-=|{}.!` must be escaped.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from src.shared.config import get_settings
from src.shared.db import upsert_digest
from src.shared.logging import get_logger

log = get_logger(__name__)


_ESC_CHARS = r"_*[]()~`>#+-=|{}.!\\"


def md_escape(text: str) -> str:
    """Escape Markdown V2 special characters."""
    out: list[str] = []
    for ch in text:
        if ch in _ESC_CHARS:
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc
        return host.replace("www.", "")
    except Exception:
        return url


def _format_header(digest_date: date, items: list[dict[str, Any]], noise_count: int) -> str:
    actionable = sum(1 for it in items if it.get("matched_projects"))
    date_str = digest_date.strftime("%-d %B")
    header = f"📰 *AI\\-дайджест на {md_escape(date_str)}*\n"
    header += f"{len(items)} находок · {actionable} для проектов · отфильтровано {noise_count}\n"
    return header


def _format_item(item: dict[str, Any]) -> str:
    matched = item.get("matched_projects") or []
    project_label = matched[0] if matched else "общее"
    trend = item.get("trend_tag")

    raw = item.get("raw_items") or {}
    url = raw.get("url") or ""

    g_score = item.get("global_score") or 0
    p_score = max((item.get("project_scores") or {}).values(), default=0)
    l_score = item.get("learning_value") or 0

    if matched and p_score >= 75:
        priority = "🔥 must\\-read"
    elif trend:
        priority = "📈 тренд"
    elif l_score >= 75:
        priority = "📚 learning"
    else:
        priority = ""

    header = f"🎯 *{md_escape(project_label)}*"
    if priority:
        header += f" · {priority}"

    title = md_escape((raw.get("title") or "").strip())
    tldr = md_escape(item.get("tldr") or "")
    domain = md_escape(_domain(url))

    score_line = f"score {g_score}"
    if p_score and matched:
        score_line += f" · project {p_score}"
    if l_score >= 60:
        score_line += f" · learning {l_score}"

    safe_url = url.replace(")", "\\)").replace("(", "\\(")

    return (
        f"{header}\n"
        f"*{title}*\n\n"
        f"{tldr}\n\n"
        f"[{domain}]({safe_url}) · {md_escape(score_line)}"
    )


def build_keyboard(item_id: UUID, has_match: bool, learning_only: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    rows.append(
        [
            InlineKeyboardButton("👍", callback_data=f"fb:{item_id}:like"),
            InlineKeyboardButton("👎", callback_data=f"fb:{item_id}:dislike"),
        ]
    )
    second: list[InlineKeyboardButton] = []
    if has_match:
        second.append(
            InlineKeyboardButton("🔥 план", callback_data=f"plan:{item_id}")
        )
    if learning_only:
        second.append(
            InlineKeyboardButton("📚 разбор", callback_data=f"learn:{item_id}")
        )
    second.append(InlineKeyboardButton("📌 сохранить", callback_data=f"fb:{item_id}:save"))
    rows.append(second)
    return InlineKeyboardMarkup(rows)


async def send_digest(
    bot: Any,
    chat_id: int,
    user_id: UUID,
    digest_date: date,
    items: list[dict[str, Any]],
    noise_count: int,
) -> dict[str, Any] | None:
    """Send digest as a series of messages (one per item) plus header.

    Telegram caps single message at ~4096 chars and inline keyboards live on
    one message — so each item is its own message. The header goes first.
    """
    if not items:
        text = (
            "🌙 *Сегодня релевантного нет*\n\n"
            "Пока тишина — ни релизов, ни заметных публикаций под твои проекты\\. "
            "Загляну завтра в 8:00\\."
        )
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.MARKDOWN_V2)
        upsert_digest(user_id, digest_date, [], noise_count)
        return None

    header = _format_header(digest_date, items, noise_count)
    head_msg = await bot.send_message(
        chat_id=chat_id, text=header, parse_mode=ParseMode.MARKDOWN_V2
    )

    item_ids: list[UUID] = []
    for it in items:
        body = _format_item(it)
        has_match = bool(it.get("matched_projects"))
        learning_only = (not has_match) and (it.get("learning_value") or 0) >= 70
        kb = build_keyboard(UUID(it["id"]), has_match=has_match, learning_only=learning_only)
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=body,
                parse_mode=ParseMode.MARKDOWN_V2,
                reply_markup=kb,
                disable_web_page_preview=False,
            )
            item_ids.append(UUID(it["id"]))
        except Exception as exc:
            log.warning(
                "digest_item_send_failed",
                item_id=str(it.get("id")),
                error=str(exc),
            )

    footer = "💬 спроси о любой теме · /trends · /weekly"
    await bot.send_message(chat_id=chat_id, text=footer)

    record = upsert_digest(
        user_id,
        digest_date,
        item_ids,
        noise_count,
        tg_message_id=head_msg.message_id,
    )
    return record


def get_owner_chat_id() -> int:
    return get_settings().telegram_owner_id
