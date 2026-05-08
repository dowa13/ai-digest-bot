# Spec: AI Digest Bot

Полное ТЗ продукта. Источник истины для кода. Если код расходится со спекой — обнови либо одно, либо другое осознанно.

## Цель

Telegram-бот, который ежедневно присылает один сводный AI-дайджест, отфильтрованный через бизнес-проекты пользователя. Профили проектов живут в Notion как single source of truth.

**Главное ограничение: $0/мес операционных расходов.** Только бесплатные сервисы.

## Стек

- Python 3.11+
- `python-telegram-bot` v21+ (long polling)
- Google Gemini API (`gemini-2.0-flash` для scoring/chat, `gemini-2.0-pro-exp` для weekly/monthly/learn)
- Supabase Postgres free tier
- Notion API (только sync, не runtime)
- GitHub Actions для cron + хостинга бота
- `feedparser` для RSS, `httpx` + `selectolax` для HTML и Telegram t.me/s

## Архитектура — три процесса

```
.
├── src/
│   ├── shared/    # config, db, models, llm/, prompts/, notion_sync.py
│   ├── worker/    # pipeline, fetchers, weekly_brief, monthly_landscape
│   └── bot/       # main, handlers
├── scripts/       # seed, sync_projects, run_pipeline_once, send_test_digest
├── tests/
├── supabase/migrations/
└── .github/workflows/
```

Pipeline: `fetch → dedup → pre-filter (regex) → score (Gemini Flash batch=10) → persist → build digest → send`.

## Cron-задачи (GitHub Actions)

| Workflow | Cron | Назначение |
|---|---|---|
| `daily-digest.yml` | `0 5 * * *` | Pipeline + ежедневный дайджест ~08:00 Vilnius |
| `weekly-brief.yml` | `0 16 * * 0` | Воскресенье 16 UTC |
| `monthly-landscape.yml` | `0 8 1 * *` | 1 числа 8 UTC |
| `sync-projects.yml` | `0 6 * * 1` | Понедельник 6 UTC — Notion sync |
| `bot-polling.yml` | `0 */6 * * *` | Каждые 6 часов перезапускаем bot polling (timeout 350m) |

## База данных

См. `supabase/migrations/0001_init.sql`.

Главные таблицы:
- `users` — пользователь (в MVP один — owner).
- `projects` — бизнес-проекты, синхронизированные из Notion.
- `sources` — источники RSS / HTML / Telegram.
- `raw_items` — сырые айтемы (dedup по `url_hash`).
- `processed_items` — отскоренные айтемы с tldr, summary, project_scores.
- `digests` / `weekly_briefs` / `monthly_landscapes` — артефакты.
- `feedback` / `chat_messages` / `user_preferences` — обратная связь.
- `bot_state` — KV для rolling logs, паузы дайджестов.
- `sync_log` — история Notion sync.

## Notion-sync

Единственный модуль, который ходит в Notion — `src/shared/notion_sync.py`. Runtime бота / worker'а **не имеет** Notion-зависимостей (если Notion упал — бот работает с последней синкнутой версией).

Парсер ищет блок `## Профиль для AI-бота` и читает поля `Описание`, `Стек`, `AI-направления` (HIGH/MEDIUM/LOW), `Keywords`, `Anti-keywords`. Все блоки до следующего heading_2 — наши, дальше — игнорируем (там пользователь пишет свои задачи).

Подробности — `docs/notion_setup.md`.

## Pre-filter

Перед scoring строим OR-regex из:
- всех `keywords` всех активных проектов пользователя;
- baseline AI-keywords (см. `src/worker/pre_filter.py`).

Если ни заголовок ни контент не матчят — айтем помечается `is_noise=True` и не идёт в LLM. Цель: 60–70% rejection rate.

## Scoring

Gemini Flash, batch=10. Промпт `src/shared/prompts/score.md` принимает batch + полные профили проектов + строгий JSON-schema. Результат: `is_noise`, `category`, `global_score`, `learning_value`, `project_scores`, `topics`, `tldr`, `summary`, `reasoning`.

Правила scoring встроены в промпт (HIGH=≥75, MEDIUM=50–70, LOW=30–50, anti-keyword cap=20).

## Digest selection

Из processed_items за 24h, не noise, выбираются те где:
- `global_score ≥ 60` ИЛИ
- `max(project_score) ≥ 65` ИЛИ
- `learning_value ≥ 75`

Sort: matched_projects DESC, trend_tag DESC, max(global, learning) DESC. Limit 8.

## Trend tagging

Топик считается «трендом» если встречается ≥3 раз за 28 дней. Пометка `trend_tag=true` поднимает айтем в сортировке.

## Calibration check (weekly)

Раз в неделю в weekly brief делается один web-поиск через Gemini Pro «major AI events week of {date}» — safety net для отлова пропусков. Результат вписывается в раздел «Что ты пропустил».

## Free tier limits

- Gemini Flash: 1500 req/day. С batch=10 хватает на ~150 фактических вызовов = ~50–100 источников × 30–50 айтемов в день.
- Gemini Pro: 50 req/day. Используется для weekly + monthly + ручных /learn.
- Supabase: 500 MB / 5 GB egress / 2 паузы в неделю при простое — не достижимо при текущем профиле.

## Costs

$0 при штатной работе. Если кончится free tier Gemini — pipeline graceful skip + уведомление owner.

## Что НЕ в MVP

- Write-back в Notion (записать «внедрено» обратно в страницу проекта).
- Embeddings / vector search.
- Multi-user (пока только TELEGRAM_OWNER_ID).
- Webhook вместо polling.
- A/B prompts.
- Anthropic API клиент (заглушка `AnthropicClient` есть для будущего переезда).

## Roadmap (после MVP)

1. **Anthropic переезд** (`docs/migration_to_anthropic.md`): заменить GeminiClient на AnthropicClient в factory, переписать score.md под их JSON formatter, проверить tool-use для chat.
2. **Notion write-back**: при тапе «✅ внедрю» — запись в подзадачу проекта в Notion.
3. **Embeddings**: семантический dedup внутри одного дня.
4. **Multi-user**: убрать привязку к OWNER_ID, добавить `/start` flow с настройкой Notion для новых пользователей.
