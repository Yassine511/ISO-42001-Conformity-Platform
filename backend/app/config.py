from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root derived from this file's location — never from the process CWD.
_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Application settings, overridable via environment variables (.env)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    #utf-8 is a text encoder that converts text to bytes
    #it tells Pydantic how to read the .env file. This prevents characters in configuration values from being decoded incorrectly.
    #for example you have APP_NAME=Copilote de conformité without it conformité could appear corrupted as conformitÃ©
    database_url: str = "postgresql+psycopg://int102:int102@localhost:5433/int102"
    qdrant_url: str = "http://localhost:6333"
    cors_origins: list[str] = ["http://localhost:5173"]

    # Retrieval (M2). Collection name is versioned: model/chunker change => new name + reindex.
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    fastembed_cache_dir: str = ""  # empty = fastembed default; set FASTEMBED_CACHE_DIR in Docker
    qdrant_collection: str = "retrieval_minilm12_v1"
    corpus_path: str = str(_REPO_ROOT / "corpus")  # /app/corpus in Docker (read-only mount)

    # LLM providers (used from M3 onward)
    mistral_api_key: str = ""
    groq_api_key: str = ""


settings = Settings()


#read config from .env , decodes it as utf-8