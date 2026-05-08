# Пример прогона pipeline

Это эталонный лог — что должно появиться в stdout при штатном `python -m scripts.run_pipeline_once`. Используй для сравнения, если что-то ведёт себя странно.

## Stdout (JSON через structlog)

```json
{"event": "fetching_sources", "total": 24, "level": "info", "timestamp": "2026-05-07T05:00:01+00:00"}
{"event": "rss_fetched", "source": "OpenAI blog", "count": 4, "level": "info", "timestamp": "..."}
{"event": "rss_fetched", "source": "arXiv cs.AI", "count": 47, "level": "info", "timestamp": "..."}
{"event": "telegram_fetched", "channel": "seeallochnaya", "count": 12, "level": "info", "timestamp": "..."}
{"event": "source_fetch_failed", "source": "Some Flaky Blog", "error": "ReadTimeout", "level": "warning", "timestamp": "..."}
{"event": "hf_papers_fetched", "count": 8, "level": "info", "timestamp": "..."}
{"event": "github_trending_fetched", "count": 25, "level": "info", "timestamp": "..."}
{"event": "dedup_done", "seen": 134, "fresh": 78, "level": "info", "timestamp": "..."}
{"event": "pre_filter_done", "passed": 32, "rejected": 46, "level": "info", "timestamp": "..."}
{"event": "llm_call", "provider": "gemini", "model": "gemini-2.0-flash", "called_from": "score_batch", "input_chars": 18420, "output_chars": 5210, "latency_ms": 4302, "level": "info", "timestamp": "..."}
{"event": "llm_call", "provider": "gemini", "model": "gemini-2.0-flash", "called_from": "score_batch", "input_chars": 19200, "output_chars": 5800, "latency_ms": 4810, "level": "info", "timestamp": "..."}
{"event": "llm_call", "provider": "gemini", "model": "gemini-2.0-flash", "called_from": "score_batch", "input_chars": 17800, "output_chars": 4990, "latency_ms": 3950, "level": "info", "timestamp": "..."}
{"event": "llm_call", "provider": "gemini", "model": "gemini-2.0-flash", "called_from": "score_batch", "input_chars": 6420, "output_chars": 1800, "latency_ms": 2100, "level": "info", "timestamp": "..."}
{"event": "digest_built", "user_id": "...", "candidates": 11, "selected": 8, "noise_filtered": 24, "level": "info", "timestamp": "..."}
{"event": "pipeline_done", "fetched": 268, "fresh": 78, "pre_filter_passed": 32, "pre_filter_rejected": 46, "scored": 32, "selected_for_digest": 8, "level": "info", "timestamp": "..."}
{"event": "pipeline_stats", "fetched": 268, "fresh": 78, "pre_filter_passed": 32, "pre_filter_rejected": 46, "scored": 32, "selected_for_digest": 8, "level": "info", "timestamp": "..."}
```

## Что должен увидеть пользователь в Telegram

Header (одно сообщение):
```
📰 AI-дайджест на 7 мая
8 находок · 3 для проектов · отфильтровано 70
```

Затем 8 сообщений, каждое с inline-кнопками `[👍] [👎] [🔥 план] [📌 сохранить]`. Каждое содержит:
- проектную плашку (`🎯 TF Market` или `🎯 общее`)
- приоритет (`🔥 must-read` / `📈 тренд` / `📚 learning`)
- жирный заголовок
- 1–2 предложения tldr
- ссылку с доменом и score'ами

Footer:
```
💬 спроси о любой теме · /trends · /weekly
```

## Типичные косяки

- `gemini_quota_exceeded` посреди прогона → pipeline пропускает оставшиеся scoring batches, отправляет неполный дайджест с пометкой в логах. Owner получает дайджест из того что успело отскориться.
- `fetch_error` для отдельного источника увеличивает его `fail_count` в `sources`. После 5 фейлов имеет смысл вручную деактивировать через Supabase Studio.
- `parse_error` от LLM (вернул не-JSON) — батч пропускается, его айтемы остаются в `raw_items`, но без processed_items. Они НЕ попадут в дайджест.
