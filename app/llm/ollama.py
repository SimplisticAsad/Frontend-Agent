from __future__ import annotations

import base64

import httpx

from app.config.settings import LLMSettings
from app.domain.models.errors import LLMError
from app.llm.base import LLMProvider, LLMRequest, LLMResponse


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, settings: LLMSettings, client: httpx.Client | None = None):
        if not settings.model:
            raise LLMError("LLM_MODEL must be set for the ollama provider")
        self.settings = settings
        self._client = client or httpx.Client(timeout=settings.timeout_s)

    def generate(self, request: LLMRequest) -> LLMResponse:
        model = self.settings.vision_model if request.images else self.settings.model
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        user: dict = {"role": "user", "content": request.prompt}
        if request.images:
            user["images"] = [base64.b64encode(p.read_bytes()).decode() for p in request.images]
        messages.append(user)
        body: dict = {"model": model, "messages": messages, "stream": False, "options": {"temperature": request.temperature}}
        if request.json_output:
            body["format"] = "json"
        if request.max_tokens:
            body["options"]["num_predict"] = request.max_tokens
        try:
            r = self._client.post(f"{self.settings.base_url.rstrip('/')}/api/chat", json=body)
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise LLMError(f"Ollama request failed: {type(e).__name__}: {e}") from e
        return LLMResponse(
            text=data.get("message", {}).get("content", ""),
            model=model,
            prompt_tokens=data.get("prompt_eval_count"),
            completion_tokens=data.get("eval_count"),
        )
