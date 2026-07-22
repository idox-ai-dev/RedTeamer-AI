from __future__ import annotations

import os

from .base import LLMProvider
from .anthropic_provider import AnthropicProvider
from .openai_provider import OpenAICompatibleProvider, AzureOpenAIProvider


def create_provider() -> LLMProvider:
    p = os.environ.get("EVALUATOR_PROVIDER", "azure_openai").lower()
    if p == "anthropic":
        return AnthropicProvider(
            api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        )
    if p == "openai":
        return OpenAICompatibleProvider(
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            model=os.environ.get("OPENAI_MODEL", "gpt-4o"),
            base_url=os.environ.get("OPENAI_BASE_URL", ""),
        )
    if p == "openai_compatible":
        return OpenAICompatibleProvider(
            api_key=os.environ.get("OPENAI_COMPATIBLE_API_KEY", "") or "none",
            model=os.environ.get("OPENAI_COMPATIBLE_MODEL", ""),
            base_url=os.environ.get("OPENAI_COMPATIBLE_BASE_URL", ""),
        )
    if p == "azure_openai":
        return AzureOpenAIProvider(
            endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT", "").rstrip("/"),
            api_key=os.environ.get("AZURE_OPENAI_API_KEY", ""),
            deployment=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
        )
    raise ValueError(
        f"Unknown EVALUATOR_PROVIDER: {p!r}. "
        "Use: anthropic | openai | azure_openai | openai_compatible"
    )


__all__ = [
    "LLMProvider",
    "AnthropicProvider",
    "OpenAICompatibleProvider",
    "AzureOpenAIProvider",
    "create_provider",
]
