from __future__ import annotations

import asyncio
import logging

from .base import LLMProvider

log = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6") -> None:
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        loop = asyncio.get_event_loop()

        def _call() -> str:
            try:
                msg = self._client.messages.create(
                    model=self._model,
                    max_tokens=1024,
                    system=system_prompt + "\n\nIMPORTANT: Return ONLY valid JSON, no markdown fences.",
                    messages=[{"role": "user", "content": user_prompt}],
                )
                return msg.content[0].text if msg.content else "{}"
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                body = getattr(exc, "body", None)
                if status:
                    log.error(
                        "LLM API call failed: provider=anthropic model=%s status=%s error=%s body=%s",
                        self._model, status, type(exc).__name__, str(body)[:300],
                    )
                else:
                    log.error(
                        "LLM API call failed: provider=anthropic model=%s error=%s detail=%s",
                        self._model, type(exc).__name__, str(exc)[:300],
                    )
                raise

        return await loop.run_in_executor(None, _call)
