from __future__ import annotations

import asyncio
import logging

from .base import LLMProvider

log = logging.getLogger(__name__)


class OpenAICompatibleProvider(LLMProvider):
    """Covers OpenAI, self-hosted (Ollama/vLLM/LM Studio), and any OpenAI-compatible endpoint."""

    def __init__(self, api_key: str, model: str, base_url: str = "") -> None:
        from openai import OpenAI
        kwargs: dict = {"api_key": api_key or "none"}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)
        self._model = model

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        loop = asyncio.get_event_loop()

        def _call() -> str:
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_completion_tokens=1024,
                )
                return resp.choices[0].message.content or "{}"
            except Exception as exc:
                _log_api_error("openai_compatible", self._model, exc)
                raise

        return await loop.run_in_executor(None, _call)


class AzureOpenAIProvider(LLMProvider):
    def __init__(self, endpoint: str, api_key: str, deployment: str, api_version: str) -> None:
        from openai import AzureOpenAI
        self._client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )
        self._endpoint = endpoint
        self._deployment = deployment

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        loop = asyncio.get_event_loop()

        def _call() -> str:
            try:
                resp = self._client.chat.completions.create(
                    model=self._deployment,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_completion_tokens=4096,
                )
                return resp.choices[0].message.content or "{}"
            except Exception as exc:
                _log_api_error(f"azure_openai endpoint={self._endpoint}", self._deployment, exc)
                raise

        return await loop.run_in_executor(None, _call)


def _log_api_error(provider: str, model: str, exc: Exception) -> None:
    status = getattr(exc, "status_code", None)
    body = getattr(exc, "body", None) or getattr(exc, "response", None)
    if status:
        log.error(
            "LLM API call failed: provider=%s model=%s status=%s error=%s body=%s",
            provider, model, status, type(exc).__name__, str(body)[:300],
        )
    else:
        log.error(
            "LLM API call failed: provider=%s model=%s error=%s detail=%s",
            provider, model, type(exc).__name__, str(exc)[:300],
        )
