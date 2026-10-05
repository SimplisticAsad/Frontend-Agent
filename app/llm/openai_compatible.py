from __future__ import annotations

import base64

import httpx

from app.config.settings import LLMSettings
from app.domain.models.errors import LLMError
from app.llm.base import LLMProvider, LLMRequest, LLMResponse


class OpenAICompatibleProvider(LLMProvider):
    """Any server speaking POST {base_url}/chat/completions (OpenAI, vLLM, LM Studio, llama.cpp, ...)."""

    name = "openai"

    def __init__(self, settings: LLMSettings, client: httpx.Client | None = None):
        if not settings.model:
            raise LLMError("LLM_MODEL must be set for the openai-compatible provider")
        self.settings = settings
        self._client = client or httpx.Client(timeout=settings.timeout_s)

    def generate(self, request: LLMRequest) -> LLMResponse:
        model = self.settings.vision_model if request.images else self.settings.model
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        if request.images:
            content: list[dict] = [{"type": "text", "text": request.prompt}]
            for p in request.images:
                b64 = base64.b64encode(p.read_bytes()).decode()
                content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": request.prompt})
        body: dict = {"model": model, "messages": messages, "temperature": request.temperature}
        if request.json_output:
            body["response_format"] = {"type": "json_object"}
        if request.max_tokens:
            body["max_tokens"] = request.max_tokens
        headers = {"Authorization": f"Bearer {self.settings.api_key}"} if self.settings.api_key else {}
        try:
            r = self._client.post(f"{self.settings.base_url.rstrip('/')}/chat/completions", json=body, headers=headers)
            r.raise_for_status()
            data = r.json()
            text = data["choices"][0]["message"]["content"] or ""
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
            raise LLMError(f"OpenAI-compatible request failed: {type(e).__name__}") from e  # never echo headers/keys
        usage = data.get("usage", {})
        return LLMResponse(text=text, model=model, prompt_tokens=usage.get("prompt_tokens"), completion_tokens=usage.get("completion_tokens"))
