# AI Digest Bot

Telegram-бот, который ежедневно присылает один сводный AI-дайджест, отфильтрованный через бизнес-проекты пользователя. Профили проектов синхронизируются из Notion. **$0/мес операционных расходов** — только бесплатные сервисы.

---

## TL;DR

- 24+ источника (RSS, HF papers, GitHub trending, Telegram-каналы, блоги OpenAI / Anthropic / DeepMind).
- Pre-filter regex отрезает мусор без LLM.
- Gemini Flash скорит batch=10 — в день расход ~150 LLM-вызовов = укладываемся в free tier.
- Дайджест в 8:00 Vilnius каждый день. Weekly brief в воскресенье. Monthly landscape 1 числа.
- Свободный чат с ботом на любые темы — он подтянет последние процесснутые айтемы как контекст.
- Профили проектов в Notion: меняешь там → `/sync` → бот учитывает в скоринге.

## Stack

- Python 3.11+
- python-telegram-bot v21+ (long polling)
- Google Gemini API (`google-genai`)
- Supabase Postgres (`supabase-py`)
- Notion API (`notion-client`) — только для sync
- GitHub Actions для cron + хостинга бота polling
- httpx + selectolax + feedparser для парсинга

См. полное ТЗ: [`docs/spec.md`](docs/spec.md).

---

## Онбординг (15 минут на чистом аккаунте)

### 1. Telegram Bot

1. Открой [@BotFather](https://t.me/BotFather) в Telegram.
2. `/newbot` → имя → username.
3. Сохрани **bot token** (`12345:AAAA…`).
4. Узнай свой **Telegram user ID**: напиши [@userinfobot](https://t.me/userinfobot), он вернёт твой `id` (число).

### 2. Supabase

1. [supabase.com](https://supabase.com) → New project (free tier, любой регион).
2. Project Settings → API → скопируй:
   - `URL` (`https://xxxxx.supabase.co`)
   - `service_role` key (НЕ anon — тебе нужен service для записи).
3. SQL Editor → New query → вставь содержимое [`supabase/migrations/0001_init.sql`](supabase/migrations/0001_init.sql) → Run.

### 3. Google Gemini API

1. [aistudio.google.com](https://aistudio.google.com) → API Keys → Create API key.
2. Скопируй ключ. Free tier: 1500 req/day для Flash, 50 req/day для Pro.

### 4. Notion integration

Подробно: [`docs/notion_setup.md`](docs/notion_setup.md). Вкратце:

1. [notion.so/my-integrations](https://www.notion.so/my-integrations) → New integration → копируй token (`secret_…`).
2. Для каждой страницы проекта в Notion: `•••` → **Add connections** → выбери свою integration.
3. Создай на каждой странице проекта раздел `## Профиль для AI-бота` (формат — в `docs/notion_setup.md`).

### 5. Локально: проверить что всё запускается

```bash
git clone <repo>
cd ai-digest-bot

cp .env.example .env
# заполни в .env: GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_OWNER_ID,
# SUPABASE_URL, SUPABASE_SERVICE_KEY, NOTION_API_KEY

python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Тесты — должны пройти без сетевых вызовов
pytest

# Засеять БД owner-юзером, 4 placeholder-проектами и источниками
python -m scripts.seed
```

### 6. Привязать Notion-страницы к проектам

В Telegram-чате с ботом отправь (для каждого проекта):
```
set tf_market 1a2b3c4d5e6f7890abcdef1234567890
set tf_clo    fedcba0987654321...
set bage      ...
set vpn_bot   ...
```

Где правую часть берёшь из URL Notion-страницы (последние 32 hex-символа).

Затем:
```
/sync
```

Бот выкачает профили из Notion и заполнит `description`, `keywords`, `ai_use_cases` в БД.

### 7. Прогнать pipeline вручную

```bash
python -m scripts.run_pipeline_once
```

Через ~1–2 минуты в Telegram должен прилететь дайджест. Если что-то пошло не так — смотри stdout (JSON-логи).

### 8. Деплой на GitHub Actions

1. Запуш репо в свой GitHub.
2. Settings → Secrets and variables → Actions → добавь:
   - `GEMINI_API_KEY`
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_OWNER_ID`
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_KEY`
   - `NOTION_API_KEY`
3. Workflows активируются автоматически. Первый запуск — через `Actions → Daily AI Digest → Run workflow`.

После этого:
- Каждый день в 5:00 UTC (~8:00 Vilnius) приходит дайджест.
- Каждое воскресенье в 16 UTC — weekly brief.
- 1-го числа в 8 UTC — monthly landscape.
- Каждый понедельник в 6 UTC — Notion sync (плюс по запросу через `/sync`).
- Бот живёт через `bot-polling.yml` — 350-минутный workflow, перезапускается каждые 6 часов.

---

## Команды бота

| Команда | Что делает |
|---|---|
| `/start` | Регистрирует owner-пользователя |
| `/digest` | Перепосылает последний дневной дайджест |
| `/weekly` | Последний weekly brief |
| `/monthly` | Последний monthly landscape |
| `/learn <тема>` | Глубокий разбор темы (Gemini Pro + web search) |
| `/trends` | Топ 10 тем за 4 недели |
| `/projects` | Список проектов и их sync-статусы |
| `/sync` | Синхронизировать профили из Notion |
| `/sources` | Показать источники |
| `/pause N` | Пауза дайджестов на N дней |
| `/admin stats` | Статистика за последние 24 часа |
| `set <slug> <id>` | Установить notion_page_id для проекта |

Свободные сообщения → бот отвечает через chat-промпт, опираясь на обработанные айтемы.

Кнопки под айтемами в дайджесте: `👍 / 👎 / 🔥 план / 📌 сохранить` (для матчей с проектами) или `📚 разбор` (для learning items).

---

## Скрипты

```bash
python -m scripts.seed              # засеять БД (idempotent)
python -m scripts.sync_projects     # вручную запустить Notion → DB sync
python -m scripts.run_pipeline_once # одноразовый прогон pipeline
python -m scripts.send_test_digest  # отправить дайджест из текущего состояния БД
```

---

## Архитектура

```
src/
├── shared/
│   ├── config.py        # Pydantic Settings из env
│   ├── db.py            # Supabase wrapper
│   ├── models.py        # Pydantic models + LLM response schemas
│   ├── notion_sync.py   # Notion → DB sync (только в sync-скрипте!)
│   ├── llm/             # LLMClient + GeminiClient + AnthropicClient (stub)
│   └── prompts/         # *.md промпты
├── worker/
│   ├── pipeline.py      # fetch → dedup → pre-filter → score → persist → digest
│   ├── fetchers/        # rss, html, telegram, hf_papers, github_trending
│   ├── pre_filter.py
│   ├── scoring.py
│   ├── trend_tracker.py
│   ├── digest_builder.py
│   ├── digest_sender.py
│   ├── weekly_brief.py
│   └── monthly_landscape.py
└── bot/
    ├── main.py
    ├── keyboards.py
    └── handlers/  (commands, callbacks, chat)
```

Подробнее — [`docs/spec.md`](docs/spec.md).

---

## Тесты

```bash
pytest                  # все тесты — без сетевых вызовов
pytest -k notion        # только parsing tests
pytest -v --tb=short    # подробный вывод
```

Покрыто:
- Парсер блока «Профиль для AI-бота» с разными форматами.
- Pre-filter regex.
- canonical_url / url_hash.
- Digest selection / sorting.
- Telegram t.me/s URL parser.
- Pydantic-валидация LLM-ответов.

---

## Что дальше

- [ ] Регрессионный набор для scoring (`tests/test_scoring.py` с 20 размеченными айтемами) — план в `.claude/agents/scoring-evaluator.md`.
- [ ] Notion write-back: при тапе «✅ внедрю» — запись в подзадачу проекта.
- [ ] Embedding-based dedup внутри одного дня.
- [ ] Multi-user.

См. также:
- [`AGENTS.md`](AGENTS.md) — для AI-кодинг агентов
- [`CLAUDE.md`](CLAUDE.md) — Claude-specific инструкции и subagents
- [`docs/migration_to_anthropic.md`](docs/migration_to_anthropic.md) — план переезда с Gemini

---

## Лицензия

MIT
