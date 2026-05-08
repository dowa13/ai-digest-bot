# AGENTS.md

Этот файл — для AI кодинг-агентов (Claude Code, Cursor, Codex). Он содержит контекст, который не нужен людям, но нужен агентам.

## Project overview

Telegram-бот, который ежедневно присылает AI-дайджест, отфильтрованный через бизнес-проекты пользователя. Профили проектов синхронизируются из Notion. Полностью бесплатный стек.

Подробное ТЗ — в `docs/spec.md`.

## Stack

- Python 3.11+
- `python-telegram-bot` v21+ (long polling)
- Google Gemini API (через `google-genai`)
- Supabase Postgres (через `supabase-py`)
- Notion API (через `notion-client`)
- GitHub Actions для cron и хостинга бота

## Setup

```bash
pip install -e ".[dev]"
cp .env.example .env  # заполни ключи
python -m scripts.seed
```

## Common commands

- Тесты: `pytest tests/ -v`
- Линт: `ruff check . && ruff format --check .`
- Прогнать pipeline вручную: `python -m scripts.run_pipeline_once`
- Синк проектов из Notion: `python -m scripts.sync_projects`
- Тестовый дайджест: `python -m scripts.send_test_digest`

## Architecture

Три процесса:
- `src/worker/` — cron-задачи (daily digest, weekly brief, monthly landscape, sync)
- `src/bot/` — Telegram bot с long polling
- `src/shared/` — общий код (LLM-клиент, БД, Notion-парсер, промпты)

Pipeline: fetch → dedup → pre-filter (regex) → score (Gemini Flash batch) → persist → build digest → send.

## Conventions

- Async-first везде где возможно (`asyncio.gather` для fetcher'ов).
- Pydantic для валидации структурированных JSON-ответов от LLM.
- structlog в JSON в stdout.
- Никаких runtime-зависимостей от Notion в bot/worker — только sync-скрипт ходит в Notion.
- Строгие типы. `mypy --strict` на `src/shared/`.

## Domain terminology

- **action item** — айтем дайджеста с высоким `project_score` под конкретный проект.
- **learning item** — айтем с высоким `learning_value` но низкими `project_scores` (для понимания индустрии).
- **noise** — айтем который не должен показываться (`is_noise=true`).
- **trend tag** — топик встречающийся ≥3 раз за 28 дней.
- **calibration check** — еженедельный веб-поиск в weekly brief для отлова пропусков.

## Environment

Все секреты в `.env` локально и GitHub Secrets в продакшне. Список — в `.env.example`.

`NOTION_SYNC_ENABLED=false` отключает синхронизацию из Notion (бот работает с тем что в БД).

## Tests

Особое внимание на:
- `tests/test_notion_parser.py` — парсер блока «Профиль для AI-бота» с разными форматами.
- `tests/test_scoring.py` — снапшот scoring на 20 фиксированных айтемах для регрессии после правок промпта.
- `tests/test_pipeline.py` — end-to-end pipeline на mock-источниках.

## CI

GitHub Actions запускает `pytest` + `ruff` на каждый push в main. Если зелёное — workflows активны.

## See also

- `CLAUDE.md` — Claude-specific инструкции.
- `docs/spec.md` — полное ТЗ продукта.
- `docs/notion_setup.md` — инструкция по настройке Notion-страниц.
- `.claude/agents/` — специализированные subagents для этого проекта.
