from __future__ import annotations

from app.config import Settings, get_settings
from app.llm.base import LLMProvider


def get_provider(settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings()
    provider = settings.llm_provider.lower()

    if provider in ("ollama_cloud", "ollama"):
        from app.llm.ollama import OllamaCloudProvider

        return OllamaCloudProvider(settings)

    if provider == "openai":
        from app.llm.openai_compatible import OpenAICompatibleProvider

        return OpenAICompatibleProvider(
            base_url="https://api.openai.com/v1",
            api_key=settings.openai_api_key,
            model=settings.llm_model,
        )

    # claude, gemini — added in Phase 8
    raise NotImplementedError(
        f"LLM provider {settings.llm_provider!r} not implemented yet"
    )


def get_vision_provider(settings: Settings | None = None) -> LLMProvider:
    """Provider pinned to the vision model (used for receipt OCR)."""
    settings = settings or get_settings()
    vision = settings.model_copy(update={"llm_model": settings.llm_vision_model})
    return get_provider(vision)
