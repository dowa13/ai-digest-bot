"""Seed the DB with the initial owner user, 4 placeholder projects, and the
fixed list of sources from the spec.

Idempotent — re-running just upserts existing rows.
"""

from __future__ import annotations

from typing import Any

from src.shared.config import get_settings
from src.shared.db import get_client, upsert_user
from src.shared.logging import get_logger

log = get_logger(__name__)


PROJECT_PLACEHOLDERS: list[dict[str, Any]] = [
    {"slug": "tf_market", "name": "TF Market", "notion_page_id": ""},
    {"slug": "tf_clo", "name": "TF Clo", "notion_page_id": ""},
    {"slug": "bage", "name": "BAGÉ Boutique", "notion_page_id": ""},
    {"slug": "vpn_bot", "name": "VPN Bot (Remnawave)", "notion_page_id": ""},
]


SOURCES: list[dict[str, Any]] = [
    # RSS / API
    {"kind": "hf_papers", "url": "https://huggingface.co/papers", "name": "HuggingFace daily papers", "lang": "en"},
    {"kind": "rss", "url": "http://export.arxiv.org/rss/cs.AI", "name": "arXiv cs.AI", "lang": "en"},
    {"kind": "rss", "url": "http://export.arxiv.org/rss/cs.CL", "name": "arXiv cs.CL", "lang": "en"},
    {"kind": "rss", "url": "http://export.arxiv.org/rss/cs.CV", "name": "arXiv cs.CV", "lang": "en"},
    {"kind": "html", "url": "https://www.anthropic.com/news", "name": "Anthropic news", "lang": "en"},
    {"kind": "rss", "url": "https://openai.com/blog/rss.xml", "name": "OpenAI blog", "lang": "en"},
    {"kind": "rss", "url": "https://deepmind.google/discover/blog/rss.xml", "name": "Google DeepMind", "lang": "en"},
    {"kind": "rss", "url": "https://developers.googleblog.com/feeds/posts/default", "name": "Google Developers AI", "lang": "en"},
    {"kind": "rss", "url": "https://hnrss.org/newest?q=AI+OR+LLM+OR+%22machine+learning%22&points=50", "name": "Hacker News (AI)", "lang": "en"},
    {"kind": "github_trending", "url": "https://github.com/trending/python?since=daily", "name": "GitHub trending Python", "lang": "en"},
    {"kind": "rss", "url": "https://www.producthunt.com/topics/artificial-intelligence/feed", "name": "Product Hunt AI", "lang": "en"},
    {"kind": "rss", "url": "https://habr.com/ru/rss/flows/develop/?fl=ru&hub=machine_learning", "name": "Хабр AI/ML", "lang": "ru"},
    {"kind": "rss", "url": "https://vc.ru/rss/tag/%D0%98%D0%98", "name": "vc.ru AI", "lang": "ru"},
    {"kind": "rss", "url": "https://woocommerce.com/blog/feed/", "name": "WooCommerce blog", "lang": "en"},
    {"kind": "rss", "url": "https://shopify.dev/changelog/feed.xml", "name": "Shopify dev changelog", "lang": "en"},
    {"kind": "rss", "url": "https://github.com/remnawave/panel/releases.atom", "name": "Remnawave releases", "lang": "en"},
    # Telegram channels (RU — основной источник на 80%)
    {"kind": "telegram", "url": "https://t.me/seeallochnaya", "name": "Сиолошная", "lang": "ru"},
    {"kind": "telegram", "url": "https://t.me/ai_newz", "name": "ai_newz", "lang": "ru"},
    {"kind": "telegram", "url": "https://t.me/denissexy", "name": "Denis Sexy IT", "lang": "ru"},
    {"kind": "telegram", "url": "https://t.me/addmeto", "name": "addmeto", "lang": "ru"},
    {"kind": "telegram", "url": "https://t.me/gonzo_ML", "name": "gonzo_ML", "lang": "ru"},
    {"kind": "telegram", "url": "https://t.me/aihappens", "name": "aihappens", "lang": "ru"},
    {"kind": "telegram", "url": "https://t.me/metaverse_news", "name": "Метаверсище и ИИще", "lang": "ru"},
    {"kind": "telegram", "url": "https://t.me/ai_machinelearning_big_data", "name": "ai_machinelearning_big_data", "lang": "ru"},
    {"kind": "telegram", "url": "https://t.me/data_secrets", "name": "Data Secrets", "lang": "ru"},
    {"kind": "telegram", "url": "https://t.me/abstractDL", "name": "AbstractDL", "lang": "ru"},
    {"kind": "telegram", "url": "https://t.me/cgevent", "name": "CGevent (генеративка)", "lang": "ru"},
    {"kind": "telegram", "url": "https://t.me/neuralshit", "name": "NeuralShit", "lang": "ru"},
    {"kind": "telegram", "url": "https://t.me/epsiloncorrection", "name": "epsilon correction (AI для бизнеса)", "lang": "ru"},
    {"kind": "telegram", "url": "https://t.me/ai_newschannel", "name": "AI News (RU)", "lang": "ru"},
    {"kind": "telegram", "url": "https://t.me/llm_under_hood", "name": "LLM under the hood", "lang": "ru"},
    # Habr хабы (RU)
    {"kind": "rss", "url": "https://habr.com/ru/rss/hubs/artificial_intelligence/", "name": "Хабр / AI", "lang": "ru"},
    {"kind": "rss", "url": "https://habr.com/ru/rss/hubs/natural_language_processing/", "name": "Хабр / NLP", "lang": "ru"},
    {"kind": "rss", "url": "https://habr.com/ru/rss/flows/develop/?fl=ru&hub=openai", "name": "Хабр / OpenAI", "lang": "ru"},
]


def seed_user_and_projects() -> None:
    settings = get_settings()
    settings.require_telegram()
    settings.require_supabase()

    user = upsert_user(settings.telegram_owner_id)
    user_id = user["id"]
    log.info("seeded_user", user_id=user_id, tg_user_id=settings.telegram_owner_id)

    client = get_client()
    for p in PROJECT_PLACEHOLDERS:
        existing = (
            client.table("projects")
            .select("id")
            .eq("user_id", user_id)
            .eq("slug", p["slug"])
            .limit(1)
            .execute()
        )
        if existing.data:
            log.info("project_exists", slug=p["slug"])
            continue
        client.table("projects").insert({**p, "user_id": user_id}).execute()
        log.info("project_seeded", slug=p["slug"])


def seed_sources() -> None:
    client = get_client()
    for s in SOURCES:
        existing = (
            client.table("sources")
            .select("id")
            .eq("url", s["url"])
            .limit(1)
            .execute()
        )
        if existing.data:
            continue
        client.table("sources").insert(s).execute()
        log.info("source_seeded", name=s["name"])


def main() -> None:
    seed_user_and_projects()
    seed_sources()
    log.info("seed_done")


if __name__ == "__main__":
    main()
