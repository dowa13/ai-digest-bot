"""Google Gemini client implementation of `LLMClient`.

We use the `google-genai` SDK. All calls log input/output sizes so the
cost-optimizer agent has data to work with.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from google import genai
from google.genai import types
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.shared.config import get_settings
from src.shared.db import state_get, state_set
from src.shared.llm.base import LLMClient, LLMQuotaError, LLMResponse
from src.shared.logging import get_logger

log = get_logger(__name__)


class GeminiQuotaError(LLMQuotaError):
    """Raised when Gemini returns a 429/quota error after retries."""


# Backwards-compat alias.
GeminiQuotaExceeded = GeminiQuotaError


def _is_quota_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "quota" in msg or "resource_exhausted" in msg


class GeminiClient(LLMClient):
    def __init__(self, api_key: str | None = None) -> None:
        settings = get_settings()
        settings.require_gemini()
        self._client = genai.Client(api_key=api_key or settings.gemini_api_key)
        self._fast = settings.gemini_model_fast
        self._deep = settings.gemini_model_deep

    # ---- public API ----

    async def score_batch(
        self, *, system_prompt: str, user_payload: str
    ) -> LLMResponse:
        return await self._call(
            model=self._fast,
            system_prompt=system_prompt,
            user_payload=user_payload,
            response_mime_type="application/json",
            called_from="score_batch",
        )

    async def summarize(
        self, *, system_prompt: str, user_payload: str
    ) -> LLMResponse:
        return await self._call(
            model=self._fast,
            system_prompt=system_prompt,
            user_payload=user_payload,
            response_mime_type=None,
            called_from="summarize",
        )

    async def chat(
        self,
        *,
        system_prompt: str,
        history: list[dict[str, str]],
        user_message: str,
    ) -> LLMResponse:
        contents: list[Any] = []
        for msg in history:
            role = "user" if msg["role"] == "user" else "model"
            contents.append(
                types.Content(role=role, parts=[types.Part.from_text(text=msg["content"])])
            )
        contents.append(
            types.Content(role="user", parts=[types.Part.from_text(text=user_message)])
        )
        return await self._call_raw(
            model=self._fast,
            system_prompt=system_prompt,
            contents=contents,
            response_mime_type=None,
            called_from="chat",
        )

    async def deep_dive(
        self,
        *,
        system_prompt: str,
        user_payload: str,
        enable_web: bool = False,
    ) -> LLMResponse:
        tools: list[Any] | None = None
        if enable_web:
            tools = [types.Tool(google_search=types.GoogleSearch())]
        return await self._call(
            model=self._deep,
            system_prompt=system_prompt,
            user_payload=user_payload,
            response_mime_type=None,
            tools=tools,
            called_from="deep_dive",
        )

    # ---- internals ----

    async def _call(
        self,
        *,
        model: str,
        system_prompt: str,
        user_payload: str,
        response_mime_type: str | None,
        tools: list[Any] | None = None,
        called_from: str,
    ) -> LLMResponse:
        contents = [
            types.Content(role="user", parts=[types.Part.from_text(text=user_payload)])
        ]
        return await self._call_raw(
            model=model,
            system_prompt=system_prompt,
            contents=contents,
            response_mime_type=response_mime_type,
            tools=tools,
            called_from=called_from,
        )

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _call_raw(
        self,
        *,
        model: str,
        system_prompt: str,
        contents: list[Any],
        response_mime_type: str | None,
        tools: list[Any] | None = None,
        called_from: str,
    ) -> LLMResponse:
        config_kwargs: dict[str, Any] = {
            "system_instruction": system_prompt,
            "temperature": 0.4,
        }
        if response_mime_type is not None:
            config_kwargs["response_mime_type"] = response_mime_type
        if tools:
            config_kwargs["tools"] = tools
        config = types.GenerateContentConfig(**config_kwargs)

        input_chars = sum(
            len(p.text or "") for c in contents for p in (c.parts or [])
        ) + len(system_prompt)

        start = time.monotonic()
        try:
            # google-genai is sync; offload to thread
            response = await asyncio.to_thread(
                self._client.models.generate_content,
                model=model,
                contents=contents,
                config=config,
            )
        except Exception as exc:  # pragma: no cover - depends on SDK
            if _is_quota_error(exc):
                log.error("gemini_quota_exceeded", model=model, called_from=called_from)
                raise GeminiQuotaExceeded(str(exc)) from exc
            log.error(
                "gemini_call_failed",
                model=model,
                called_from=called_from,
                error=str(exc),
            )
            raise
        latency_ms = int((time.monotonic() - start) * 1000)

        text = (response.text or "").strip()
        out_chars = len(text)

        log.info(
            "llm_call",
            provider="gemini",
            model=model,
            called_from=called_from,
            input_chars=input_chars,
            output_chars=out_chars,
            latency_ms=latency_ms,
        )
        _record_call(model=model, called_from=called_from, input_chars=input_chars, output_chars=out_chars)

        return LLMResponse(
            text=text,
            model=model,
            input_chars=input_chars,
            output_chars=out_chars,
            latency_ms=latency_ms,
            raw=response,
        )


def _record_call(*, model: str, called_from: str, input_chars: int, output_chars: int) -> None:
    """Append a rolling-window log entry to bot_state['llm_calls_log']."""
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
    """Best-effort JSON extraction from a Gemini response.

    Gemini sometimes wraps JSON in ```json ... ``` even with response_mime_type set.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)
