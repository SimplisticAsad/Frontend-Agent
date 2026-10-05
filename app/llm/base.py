"""Provider-agnostic LLM interface. Pipeline stages depend only on this module."""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.domain.models.errors import LLMError


@dataclass
class LLMRequest:
    stage: str  # prompt/stage name, e.g. "page_planning"
    prompt: str  # fully rendered prompt (from prompts/<stage>.md)
    context: dict[str, Any] = field(default_factory=dict)  # structured context (also embedded in prompt)
    system: str = ""
    json_output: bool = True
    images: list[Path] = field(default_factory=list)  # for vision stages
    temperature: float = 0.2
    max_tokens: int | None = None
    unit: str | None = None  # e.g. screen ref the call is about (logging / mock dispatch)


@dataclass
class LLMResponse:
    text: str
    model: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    def json(self) -> Any:
        return extract_json(self.text)


class LLMProvider(ABC):
    name = "base"

    @abstractmethod
    def generate(self, request: LLMRequest) -> LLMResponse:
        """Return the model completion. Must raise LLMError on transport failures."""


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> Any:
    """Parse JSON from a completion, tolerating markdown fences and leading/trailing prose."""
    s = text.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    m = _FENCE.search(s)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    start = min((i for i in (s.find("{"), s.find("[")) if i >= 0), default=-1)
    if start >= 0:
        opener = s[start]
        closer = "}" if opener == "{" else "]"
        end = s.rfind(closer)
        if end > start:
            try:
                return json.loads(s[start : end + 1])
            except json.JSONDecodeError:
                pass
    raise LLMError(f"LLM output is not valid JSON: {s[:200]!r}")
