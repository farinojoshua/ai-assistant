"""Ollama Cloud provider — OpenAI-compatible API at https://ollama.com/v1."""
from __future__ import annotations

import httpx

from app.config import Settings
from app.llm.openai_compatible import OpenAICompatibleProvider


class OllamaCloudProvider(OpenAICompatibleProvider):
    def __init__(
        self, settings: Settings, http_client: httpx.AsyncClient | None = None
    ) -> None:
        base = settings.ollama_base_url.rstrip("/")
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        super().__init__(
            base_url=base,
            api_key=settings.ollama_api_key,
            model=settings.llm_model,
            http_client=http_client,
        )
