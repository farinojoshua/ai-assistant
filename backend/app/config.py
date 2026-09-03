import json
from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # App
    app_database_url: str = "postgresql+psycopg://app:app@localhost:5432/app"
    company_database_url: str = (
        "postgresql+psycopg://company:company@localhost:5433/company"
    )
    # narrowly-scoped write user (INSERT/UPDATE on stok_barang only); dev
    # reuses the same connection
    company_database_write_url: str = (
        "postgresql+psycopg://company:company@localhost:5433/company"
    )
    jwt_secret: str = "dev-secret-change-me"
    jwt_access_ttl_min: int = 30
    jwt_refresh_ttl_days: int = 14
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:3002",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_origins(cls, v):
        """Accept a real list, a JSON list, or a comma/space-separated string."""
        if isinstance(v, (list, tuple)):
            return list(v)
        v = str(v).strip()
        if v.startswith("["):
            return json.loads(v)
        return [o.strip() for o in v.replace(",", " ").split() if o.strip()]

    # LLM
    llm_provider: str = "ollama_cloud"
    llm_model: str = "gpt-oss:120b"
    llm_vision_model: str = "gemma4:31b"
    ollama_base_url: str = "https://ollama.com"
    ollama_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""

    # Agent
    agent_max_iterations: int = 8
    agent_tool_timeout_s: int = 15
    agent_max_tool_calls_per_turn: int = 8

    # WhatsApp Cloud API
    # outbound (web chat echo + inbound replies)
    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_to: str = ""  # default target for the web -> WA echo toggle
    whatsapp_api_version: str = "v25.0"
    # inbound webhook
    whatsapp_verify_token: str = ""  # you invent this; must match Meta config
    whatsapp_app_secret: str = ""  # Meta App → Settings → Basic → App Secret
    whatsapp_reply_unregistered: bool = True

    # Reimbursement
    upload_dir: str = "uploads"
    upload_max_bytes: int = 8 * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
