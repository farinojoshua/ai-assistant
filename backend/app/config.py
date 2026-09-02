from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # App
    app_database_url: str = "postgresql+psycopg://app:app@localhost:5432/app"
    company_database_url: str = (
        "postgresql+psycopg://company:company@localhost:5433/company"
    )
    jwt_secret: str = "dev-secret-change-me"
    jwt_access_ttl_min: int = 30
    jwt_refresh_ttl_days: int = 14
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:3002",
    ]

    # LLM
    llm_provider: str = "ollama_cloud"
    llm_model: str = "qwen2.5:72b"
    ollama_base_url: str = "https://ollama.com"
    ollama_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""

    # Agent
    agent_max_iterations: int = 5
    agent_tool_timeout_s: int = 15
    agent_max_tool_calls_per_turn: int = 8


@lru_cache
def get_settings() -> Settings:
    return Settings()
