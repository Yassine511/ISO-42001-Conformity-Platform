from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, overridable via environment variables (.env)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://int102:int102@localhost:5432/int102"
    qdrant_url: str = "http://localhost:6333"
    cors_origins: list[str] = ["http://localhost:5173"]

    # LLM providers (used from M3 onward)
    mistral_api_key: str = ""
    groq_api_key: str = ""


settings = Settings()
