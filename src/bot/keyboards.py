"""Reusable inline keyboards."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def projects_menu(projects: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for p in projects:
        slug = str(p.get("slug"))
        name = str(p.get("name") or slug)
        sync = p.get("sync_status") or "never"
        page_id_present = bool(p.get("notion_page_id"))
        marker = "🟢" if sync == "ok" and page_id_present else (
            "🟡" if sync == "parse_warning" else ("⚪" if not page_id_present else "🔴")
        )
        rows.append(
            [
                InlineKeyboardButton(
                    f"{marker} {name}",
                    callback_data=f"project:edit:{slug}",
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton("🔄 Sync now", callback_data="project:sync_all")]
    )
    return InlineKeyboardMarkup(rows)
