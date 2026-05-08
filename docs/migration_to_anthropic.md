# Migration plan: Gemini → Anthropic Claude

Этот документ — план переезда с Gemini на Claude API когда (а) появится бюджет либо (б) Anthropic откроет аналог free tier.

## Когда переезжать

- Гibcli Gemini Free tier систематически не хватает (>3 fail/неделю по quota).
- Качество scoring заметно лучше у Claude на reference set (см. `tests/test_scoring.py`).
- Появилась подписка / бюджет.

## Что меняется

### 1. SDK + клиент

- В `pyproject.toml` добавить `anthropic>=0.40.0`.
- Заполнить `src/shared/llm/anthropic.py`. Уже стоит заглушка с интерфейсом `LLMClient`.
- Все 4 метода (`score_batch`, `summarize`, `chat`, `deep_dive`) — через `client.messages.create(...)` с системным промптом и user content.

### 2. Маппинг моделей

| Gemini | Claude |
|---|---|
| `gemini-2.0-flash` | `claude-haiku-4-5` (или `claude-sonnet-4-5` для качества) |
| `gemini-2.0-pro-exp` | `claude-opus-4-7` |

Env: `ANTHROPIC_MODEL_FAST` / `ANTHROPIC_MODEL_DEEP`.

### 3. Структурированный output

Claude поддерживает [tool use](https://docs.claude.com/en/docs/build-with-claude/tool-use). Для `score_batch` и `extract_prefs` надо:
- Описать «инструмент» — Pydantic-схему (можно сгенерировать из `ScoreBatchResponse.model_json_schema()`).
- Передать как `tools=[...]` + `tool_choice={"type": "tool", "name": "score_items"}`.
- Парсить из `response.content[0].input` вместо `response.text`.

В `gemini.py` мы используем `response_mime_type="application/json"` — у Claude эквивалент через tool_choice.

### 4. Web search

В weekly_brief / deep_dive мы вызываем `enable_web=True` через Gemini Google Search tool. У Claude — встроенный web search tool. Замена 1:1 на уровне сигнатуры.

### 5. Prompt caching

У Claude есть [prompt caching](https://docs.claude.com/en/docs/build-with-claude/prompt-caching) — большие system prompts (наши `score.md` ~3.5KB) кешируются между вызовами. Это даёт большую экономию для batch scoring (один system prompt × сотни вызовов в день). Включить через `cache_control: {"type": "ephemeral"}` на блоке system prompt.

### 6. Tests

Регрессионные тесты scoring (`tests/test_scoring.py` — будет добавлен) должны пройти на новом провайдере с tolerance ±15. Если падают — переписать score.md под особенности Claude (он лучше понимает неструктурированные правила, хуже — длинные JSON-схемы).

## Шаги

1. Заполнить `AnthropicClient`.
2. Включить `LLM_PROVIDER=anthropic` локально, прогнать `pytest`.
3. Запустить `python -m scripts.run_pipeline_once` — сравнить scoring на одном дне.
4. Прогнать `tests/test_scoring.py` (когда будет) — accuracy ≥ 80% на reference set.
5. Откатить флаг → проверить fallback на Gemini работает.
6. В прод: переключить `LLM_PROVIDER=anthropic` в GitHub Secrets, оставить `GEMINI_API_KEY` как backup.

## Риски

- Anthropic дороже Gemini (Claude Haiku 4.5 ~ $1/M input, $5/M output vs Gemini Flash free). Прикинуть месячный объём токенов до переезда.
- Tool use overhead у Claude больше чем у Gemini JSON mode — батч 10 → возможно 5–7 чтобы не упереться в context.
