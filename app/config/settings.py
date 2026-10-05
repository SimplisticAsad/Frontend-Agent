"""Runtime configuration. Everything comes from the environment; secrets are never defaulted or logged."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class LLMSettings:
    provider: str = "ollama"
    model: str = ""
    vision_model: str = ""
    base_url: str = ""
    api_key: str = field(default="", repr=False)
    timeout_s: int = 300

    @classmethod
    def from_env(cls) -> "LLMSettings":
        provider = os.environ.get("LLM_PROVIDER", "ollama").lower()
        default_url = "http://localhost:11434" if provider == "ollama" else "https://api.openai.com/v1"
        model = os.environ.get("LLM_MODEL", "")
        return cls(
            provider=provider,
            model=model,
            vision_model=os.environ.get("LLM_VISION_MODEL", model),
            base_url=os.environ.get("LLM_BASE_URL", default_url),
            api_key=os.environ.get("LLM_API_KEY", ""),
            timeout_s=_int("LLM_TIMEOUT_S", 300),
        )


@dataclass(frozen=True)
class Limits:
    """Bounded retries - nothing in the pipeline loops without one of these."""

    max_build_correction_attempts: int = 3
    max_functional_correction_attempts: int = 3
    max_visual_correction_attempts: int = 3
    max_llm_output_retries: int = 2
    command_timeout_s: int = 900

    @classmethod
    def from_env(cls) -> "Limits":
        return cls(
            max_build_correction_attempts=_int("MAX_BUILD_CORRECTION_ATTEMPTS", 3),
            max_functional_correction_attempts=_int("MAX_FUNCTIONAL_CORRECTION_ATTEMPTS", 3),
            max_visual_correction_attempts=_int("MAX_VISUAL_CORRECTION_ATTEMPTS", 3),
            max_llm_output_retries=_int("MAX_LLM_OUTPUT_RETRIES", 2),
            command_timeout_s=_int("COMMAND_TIMEOUT_S", 900),
        )


@dataclass(frozen=True)
class Settings:
    llm: LLMSettings = field(default_factory=LLMSettings.from_env)
    limits: Limits = field(default_factory=Limits.from_env)
