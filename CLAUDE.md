# CLAUDE.md

См. `AGENTS.md` для общего контекста проекта. Этот файл содержит специфику для Claude Code.

## Subagents в этом проекте

В `.claude/agents/` определены специализированные агенты:

- `@agent-fetcher-builder` — построение и отладка fetcher'ов источников (RSS, HTML, Telegram t.me/s).
- `@agent-prompt-tuner` — анализ feedback и тюнинг промпта score.md.
- `@agent-notion-debugger` — диагностика парсинга Notion-страниц.
- `@agent-scoring-evaluator` — оценка качества scoring на размеченных примерах.
- `@agent-cost-optimizer` — анализ логов Gemini API и оптимизация costs.
- `@agent-migration-runner` — работа с миграциями Supabase Postgres.

Используй их через `@agent-<name>` в сообщении или через автоделегирование.

## Workflow для новых фич

1. Сначала пишем тесты в `tests/`.
2. Реализация в `src/`.
3. Прогоняем `pytest` локально.
4. Если меняли `score.md` или `chat.md` — `@agent-scoring-evaluator` прогоняет регрессию.

## Что НЕ делать

- Не использовать OpenAI API напрямую — только через `LLMClient` абстракцию.
- Не ходить в Notion из runtime бота / worker'a — только sync-скрипт.
- Не хардкодить keywords проектов в код — они приходят из Notion через `notion_sync.py`.
- Не использовать `time.sleep()` в async-коде — `asyncio.sleep()`.
