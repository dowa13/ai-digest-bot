"""Groq client implementation of `LLMClient`.

Uses the `groq` SDK (OpenAI-compatible API). Free tier on
`llama-3.3-70b-versatile` gives ~30 RPM and 14400 RPD — way more than our
pipeline needs.

Notes vs Gemini:
- No built-in web search tool. `deep_dive(enable_web=True)` logs a warning
  and proceeds without web grounding. Calibration check in weekly_brief
  becomes a no-op for now (TODO: integrate Tavily / Serper free tier).
- JSON mode is supported via `response_format={"type": "json_object"}` —
  used for `score_batch` and `extract_prefs`.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from groq import APIError, Groq, RateLimitError
from tenacity import retry, stop_after_attempt, wait_exponential

from src.shared.config import get_settings
from src.shared.db import state_get, state_set
from src.shared.llm.base import LLMClient, LLMQuotaError, LLMResponse
from src.shared.logging import get_logger

log = get_logger(__name__)


class GroqQuotaError(LLMQuotaError):
    """Raised when Groq returns 429 / quota error after retries."""


def _is_quota_error(exc: BaseException) -> bool:
    if isinstance(exc, RateLimitError):
        return True
    msg = str(exc).lower()
    return "429" in msg or "rate" in msg or "quota" in msg or "tokens per" in msg


class GroqClient(LLMClient):
    def __init__(self, api_key: str | None = None) -> None:
        settings = get_settings()
        if not (api_key or settings.groq_api_key):
            raise RuntimeError("GROQ_API_KEY is not set")
        self._client = Groq(api_key=api_key or settings.groq_api_key)
        self._fast = settings.groq_model_fast
        self._deep = settings.groq_model_deep

    # ---- public API ----

    async def score_batch(
        self, *, system_prompt: str, user_payload: str
    ) -> LLMResponse:
        return await self._call(
            model=self._fast,
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": user_payload}],
            json_mode=True,
            called_from="score_batch",
        )

    async def summarize(
        self, *, system_prompt: str, user_payload: str
    ) -> LLMResponse:
        # JSON mode auto-enabled when the system prompt looks like JSON-strict.
        json_mode = "JSON" in system_prompt and "schema" in system_prompt.lower()
        return await self._call(
            model=self._fast,
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": user_payload}],
            json_mode=json_mode,
            called_from="summarize",
        )

    async def chat(
        self,
        *,
        system_prompt: str,
        history: list[dict[str, str]],
        user_message: str,
    ) -> LLMResponse:
        msgs: list[dict[str, str]] = []
        for m in history:
            role = m.get("role")
            if role not in ("user", "assistant"):
                continue
            content = m.get("content") or ""
            if not content:
                continue
            msgs.append({"role": role, "content": content})
        msgs.append({"role": "user", "content": user_message})
        return await self._call(
            model=self._fast,
            system_prompt=system_prompt,
            messages=msgs,
            json_mode=False,
            called_from="chat",
        )

    async def deep_dive(
        self,
        *,
        system_prompt: str,
        user_payload: str,
        enable_web: bool = False,
    ) -> LLMResponse:
        if enable_web:
            log.warning(
                "groq_no_web_search",
                note="enable_web=True ignored — Groq has no built-in web search; calibration step degrades to model knowledge only",
            )
        return await self._call(
            model=self._deep,
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": user_payload}],
            json_mode=False,
            called_from="deep_dive",
        )

    # ---- internals ----

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10), reraise=True)
    async def _call(
        self,
        *,
        model: str,
        system_prompt: str,
        messages: list[dict[str, str]],
        json_mode: bool,
        called_from: str,
    ) -> LLMResponse:
        full_messages = [{"role": "system", "content": system_prompt}, *messages]
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": full_messages,
            "temperature": 0.4,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        input_chars = sum(len(m.get("content") or "") for m in full_messages)
        start = time.monotonic()
        try:
            response = await asyncio.to_thread(
                self._client.chat.completions.create, **kwargs
            )
        except RateLimitError as exc:
            log.error("groq_rate_limit", model=model, called_from=called_from)
            raise GroqQuotaError(str(exc)) from exc
        except APIError as exc:
            if _is_quota_error(exc):
                raise GroqQuotaError(str(exc)) from exc
            log.error(
                "groq_call_failed",
                model=model,
                called_from=called_from,
                error=str(exc),
            )
            raise
        latency_ms = int((time.monotonic() - start) * 1000)

        text = (response.choices[0].message.content or "").strip() if response.choices else ""
        out_chars = len(text)

        log.info(
            "llm_call",
            provider="groq",
            model=model,
            called_from=called_from,
            input_chars=input_chars,
            output_chars=out_chars,
            latency_ms=latency_ms,
        )
        _record_call(
            model=model,
            called_from=called_from,
            input_chars=input_chars,
            output_chars=out_chars,
        )
        return LLMResponse(
            text=text,
            model=model,
            input_chars=input_chars,
            output_chars=out_chars,
            latency_ms=latency_ms,
            raw=response,
        )


def _record_call(
    *, model: str, called_from: str, input_chars: int, output_chars: int
) -> None:
    """Append to bot_state['llm_calls_log'] rolling window."""
    try:
        log_data: list[dict[str, Any]] = state_get("llm_calls_log", []) or []
        log_data.append(
            {
                "ts": time.time(),
                "model": model,
                "called_from": called_from,
                "input_chars": input_chars,
                "output_chars": output_chars,
            }
        )
        if len(log_data) > 1000:
            log_data = log_data[-1000:]
        state_set("llm_calls_log", log_data)
    except Exception as exc:  # pragma: no cover
        log.warning("llm_log_persist_failed", error=str(exc))


def parse_json_response(text: str) -> Any:
    """Best-effort JSON extraction. Groq with JSON mode is usually clean,
    but occasionally wraps in ```json fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)
