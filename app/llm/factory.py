from __future__ import annotations

from app.config.settings import LLMSettings
from app.domain.models.errors import LLMError
from app.llm.base import LLMProvider


def create_provider(settings: LLMSettings, mock: bool = False, **mock_kwargs) -> LLMProvider:
    if mock or settings.provider == "mock":
        from app.llm.mock import MockLLMProvider

        return MockLLMProvider(**mock_kwargs)
    if settings.provider == "ollama":
        from app.llm.ollama import OllamaProvider

        return OllamaProvider(settings)
    if settings.provider in ("openai", "openai_compatible", "openai-compatible"):
        from app.llm.openai_compatible import OpenAICompatibleProvider

        return OpenAICompatibleProvider(settings)
    raise LLMError(f"Unknown LLM_PROVIDER '{settings.provider}' (use ollama, openai, mock)")
