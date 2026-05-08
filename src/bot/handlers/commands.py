"""Telegram command handlers: /start, /digest, /weekly, /monthly, /learn, /trends,
/projects, /sync, /sources, /pause, /admin.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from src.bot.keyboards import projects_menu
from src.shared.config import get_settings
from src.shared.db import (
    get_client,
    get_latest_digest,
    get_latest_monthly,
    get_latest_weekly,
    get_user_by_tg_id,
    list_projects,
    state_set,
    upsert_user,
)
from src.shared.llm.factory import get_llm
from src.shared.logging import get_logger
from src.shared.notion_sync import NotionSyncService
from src.shared.prompts import load as load_prompt
from src.worker.digest_builder import build_digest
from src.worker.digest_sender import send_digest
from src.worker.trend_tracker import topic_counts

log = get_logger(__name__)


def _is_owner(update: Update) -> bool:
    if not update.effective_user:
        return False
    return update.effective_user.id == get_settings().telegram_owner_id


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return
    tg_user = update.effective_user
    upsert_user(tg_user.id, tg_user.username)
    await update.message.reply_text(
        "Привет! Я твой AI-дайджест бот.\n\n"
        "Команды:\n"
        "/digest — повторить последний дайджест\n"
        "/weekly — показать последний weekly brief\n"
        "/monthly — показать последний monthly landscape\n"
        "/learn <тема> — глубокий разбор темы\n"
        "/trends — топ трендов за 4 недели\n"
        "/projects — список проектов и статус Notion-sync\n"
        "/sync — синхронизировать профили из Notion\n"
        "/sources — управлять источниками\n"
        "/pause N — пауза дайджестов на N дней\n"
        "/admin stats — статистика за вчера"
    )


async def digest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return
    user = get_user_by_tg_id(update.effective_user.id)
    if user is None:
        await update.message.reply_text("Сначала /start")
        return
    user_id = UUID(user["id"])

    selected, noise_count = build_digest(user_id)
    await send_digest(
        bot=context.bot,
        chat_id=update.effective_chat.id,
        user_id=user_id,
        digest_date=date.today(),
        items=selected,
        noise_count=noise_count,
    )


async def weekly(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return
    user = get_user_by_tg_id(update.effective_user.id)
    if user is None:
        return
    brief = get_latest_weekly(UUID(user["id"]))
    if brief is None:
        await update.message.reply_text("Weekly brief ещё не сгенерирован.")
        return
    period = f"{brief['period_start']} — {brief['period_end']}"
    await update.message.reply_text(f"📊 Weekly brief ({period}):")
    chunks = _chunk(brief["content"])
    for chunk in chunks:
        await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


async def monthly(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return
    user = get_user_by_tg_id(update.effective_user.id)
    if user is None:
        return
    landscape = get_latest_monthly(UUID(user["id"]))
    if landscape is None:
        await update.message.reply_text("Monthly landscape ещё не сгенерирован.")
        return
    period = f"{landscape['period_start']} — {landscape['period_end']}"
    await update.message.reply_text(f"📈 Monthly landscape ({period}):")
    chunks = _chunk(landscape["content"])
    for chunk in chunks:
        await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


async def learn(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return
    if not context.args:
        await update.message.reply_text("Использование: /learn <тема>\nНапример: /learn AI агенты")
        return
    topic = " ".join(context.args).strip()
    user = get_user_by_tg_id(update.effective_user.id)
    if user is None:
        return
    user_id = UUID(user["id"])

    await update.message.reply_text(f"🔍 Готовлю разбор «{topic}»…")

    from src.shared.db import list_processed_items_window
    since = datetime.now(UTC) - timedelta(days=60)
    rows = list_processed_items_window(user_id, since=since, include_noise=False)
    matched = [
        r for r in rows if any(topic.lower() in (t or "").lower() for t in (r.get("topics") or []))
        or topic.lower() in (r.get("tldr") or "").lower()
    ][:30]

    projects = list_projects(user_id)

    import json as _json
    payload = _json.dumps(
        {
            "query": topic,
            "history_items": [
                {
                    "url": (r.get("raw_items") or {}).get("url"),
                    "title": (r.get("raw_items") or {}).get("title"),
                    "tldr": r.get("tldr"),
                    "topics": r.get("topics") or [],
                }
                for r in matched
            ],
            "projects": [
                {"slug": p["slug"], "name": p["name"], "description": p.get("description") or ""}
                for p in projects
            ],
        },
        ensure_ascii=False,
    )
    llm = get_llm()
    prompt = load_prompt("deep_dive")
    resp = await llm.deep_dive(system_prompt=prompt, user_payload=payload, enable_web=True)
    chunks = _chunk(resp.text)
    for chunk in chunks:
        await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)


async def trends(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return
    user = get_user_by_tg_id(update.effective_user.id)
    if user is None:
        return
    user_id = UUID(user["id"])
    counts = topic_counts(user_id, days=28)
    if not counts:
        await update.message.reply_text("Пока нет данных для трендов — поработай дайджест-цикл хотя бы пару дней.")
        return
    top = counts.most_common(10)
    lines = ["📈 Топ топиков за 4 недели:\n"]
    for i, (topic, n) in enumerate(top, 1):
        lines.append(f"{i}. `{topic}` — {n}")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def projects_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return
    user = get_user_by_tg_id(update.effective_user.id)
    if user is None:
        return
    rows = list_projects(UUID(user["id"]), only_active=False)
    if not rows:
        await update.message.reply_text("Проектов нет. Запусти `python -m scripts.seed`.")
        return

    text_lines = ["*Твои проекты* (🟢 ok / 🟡 warning / 🔴 error / ⚪ нет notion\\_page\\_id):\n"]
    for p in rows:
        sync = p.get("sync_status") or "never"
        last_synced = p.get("last_synced_at") or "—"
        page_id = p.get("notion_page_id") or "—"
        text_lines.append(f"*{p['name']}* (`{p['slug']}`)")
        text_lines.append(f"  status: `{sync}` · last\\_synced: `{last_synced}`")
        text_lines.append(f"  notion\\_page\\_id: `{page_id}`\n")

    text_lines.append(
        "\nЧтобы установить notion\\_page\\_id, отправь сообщение:\n"
        "`set <slug> <page_id>`\n"
        "например: `set tf_market 1a2b3c4d5e6f7890abcdef1234567890`"
    )
    await update.message.reply_text(
        "\n".join(text_lines),
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=projects_menu(rows),
    )


async def sync_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return
    if not get_settings().notion_sync_enabled:
        await update.message.reply_text("NOTION_SYNC_ENABLED=false — синк отключён в env.")
        return
    user = get_user_by_tg_id(update.effective_user.id)
    if user is None:
        return
    user_id = UUID(user["id"])

    await update.message.reply_text("🔄 Синхронизирую с Notion…")

    service = NotionSyncService()
    try:
        result = await service.sync_all_projects(user_id, triggered_by="manual")
    except Exception as exc:
        log.exception("sync_failed")
        await update.message.reply_text(f"Sync упал: `{exc}`", parse_mode=ParseMode.MARKDOWN)
        return

    text = f"Sync: {result.synced}/{result.synced + result.failed} проектов обновлено за {result.duration_ms}ms"
    if result.errors:
        text += "\n\nОшибки:"
        for err in result.errors:
            text += f"\n- `{err.get('slug')}`: {err.get('error')}"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def sources_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return
    res = get_client().table("sources").select("*").execute()
    rows = res.data or []
    lines = ["*Источники*:\n"]
    for s in rows:
        active = "🟢" if s.get("is_active") else "🔴"
        fail = s.get("fail_count") or 0
        lines.append(
            f"{active} `{s['name']}` ({s['kind']}) — fails: {fail}"
        )
    lines.append(
        "\nПереключение пока вручную через Supabase Studio: "
        "`update sources set is_active = false where name = '...';`"
    )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def pause_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return
    if not context.args:
        await update.message.reply_text("Использование: /pause N (дней)")
        return
    try:
        days = int(context.args[0])
    except ValueError:
        await update.message.reply_text("N должно быть числом.")
        return
    until = (datetime.now(UTC) + timedelta(days=days)).isoformat()
    state_set("digest_paused_until", until)
    await update.message.reply_text(f"Пауза до {until[:10]} ({days} дн).")


async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return
    if not context.args or context.args[0] != "stats":
        await update.message.reply_text("Использование: /admin stats")
        return
    user = get_user_by_tg_id(update.effective_user.id)
    if user is None:
        return
    user_id = UUID(user["id"])

    yesterday = datetime.now(UTC) - timedelta(days=1)
    from src.shared.db import list_processed_items_window
    rows = list_processed_items_window(user_id, since=yesterday, include_noise=True)
    n_total = len(rows)
    n_noise = sum(1 for r in rows if r.get("is_noise"))

    digest = get_latest_digest(user_id)
    digest_count = len(digest.get("item_ids") or []) if digest else 0

    res = get_client().table("sources").select("name, fail_count").gt("fail_count", 0).execute()
    failing = res.data or []

    sync_log_res = (
        get_client()
        .table("sync_log")
        .select("created_at, status, projects_synced")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    last_sync = (sync_log_res.data or [{}])[0]

    text = (
        "*Stats за последние 24ч*\n\n"
        f"processed\\_items: {n_total} (noise: {n_noise})\n"
        f"в дайджесте: {digest_count}\n"
        f"failing sources: {len(failing)}\n"
        f"last sync: `{last_sync.get('created_at', '—')}` "
        f"({last_sync.get('status', '—')}, {last_sync.get('projects_synced', 0)} проектов)\n"
    )
    if failing:
        text += "\nПроблемные источники:\n"
        for s in failing[:10]:
            text += f"- `{s['name']}` ({s['fail_count']})\n"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def set_notion_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle plain text 'set <slug> <page_id>' — returns True if it consumed the message."""
    if not update.message or not update.message.text:
        return False
    text = update.message.text.strip()
    if not text.lower().startswith("set "):
        return False
    parts = text.split(maxsplit=2)
    if len(parts) != 3:
        await update.message.reply_text("Формат: `set <slug> <notion_page_id>`", parse_mode=ParseMode.MARKDOWN)
        return True
    _, slug, page_id = parts
    page_id = page_id.replace("-", "").strip()
    if len(page_id) != 32:
        await update.message.reply_text("notion_page_id должен быть 32-символьным hex (без дефисов).")
        return True
    user = get_user_by_tg_id(update.effective_user.id)
    if user is None:
        return True
    from src.shared.db import upsert_project_notion_id
    upsert_project_notion_id(UUID(user["id"]), slug, page_id)
    await update.message.reply_text(f"OK: установлен notion_page_id для `{slug}`. Теперь /sync.", parse_mode=ParseMode.MARKDOWN)
    return True


def _chunk(text: str, max_len: int = 3500) -> list[str]:
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
