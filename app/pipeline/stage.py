"""LLM stage runner: one prompt file per stage, structured output, validated, bounded retries."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from app.domain.models.errors import LLMError
from app.llm.base import LLMProvider, LLMRequest
from app.observability import EventLog

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

Validator = Callable[[Any], list[str]]


class PromptLibrary:
    def __init__(self, directory: Path = PROMPTS_DIR):
        self.dir = directory

    def names(self) -> list[str]:
        return sorted(p.stem for p in self.dir.glob("*.md"))

    def load(self, name: str) -> str:
        p = self.dir / f"{name}.md"
        if not p.exists():
            raise LLMError(f"Prompt file missing: prompts/{name}.md")
        return p.read_text(encoding="utf-8")

    def render(self, name: str, context: dict, feedback: list[str] | None = None) -> str:
        text = self.load(name)
        text = text.replace("{{CONTEXT}}", json.dumps(context, indent=1, default=str))
        fb = ""
        if feedback:
            fb = "\n\n## Problems with your previous answer (fix all of them)\n" + "\n".join(f"- {f}" for f in feedback)
        return text + fb


class StageRunner:
    def __init__(self, llm: LLMProvider, events: EventLog, prompts: PromptLibrary | None = None, max_retries: int = 2):
        self.llm = llm
        self.events = events
        self.prompts = prompts or PromptLibrary()
        self.max_retries = max_retries
        self.calls = 0

    def call(
        self,
        stage: str,
        context: dict[str, Any],
        validate: Validator | None = None,
        *,
        unit: str | None = None,
        images: list[Path] | None = None,
    ) -> Any:
        """Call the LLM for `stage`; re-ask (up to max_retries) when output is unparsable or fails `validate`."""
        feedback: list[str] = []
        last_problem = ""
        for attempt in range(self.max_retries + 1):
            prompt = self.prompts.render(stage, context, feedback)
            req = LLMRequest(stage=stage, prompt=prompt, context={**context, "_feedback": feedback}, images=images or [], unit=unit)
            t0 = time.monotonic()
            self.calls += 1
            try:
                resp = self.llm.generate(req)
                data = resp.json()
                problems = validate(data) if validate else []
            except LLMError as e:
                problems = [str(e)]
                resp = None
                data = None
            self.events.emit(
                "llm_call", stage=stage, unit=unit, attempt=attempt, duration_s=round(time.monotonic() - t0, 3),
                model=getattr(resp, "model", None), prompt_tokens=getattr(resp, "prompt_tokens", None),
                completion_tokens=getattr(resp, "completion_tokens", None), problems=problems[:5],
            )
            if not problems:
                return data
            feedback = problems
            last_problem = "; ".join(problems[:5])
        raise LLMError(f"Stage '{stage}'{f' ({unit})' if unit else ''} failed validation after {self.max_retries + 1} attempts: {last_problem}")
