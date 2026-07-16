from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root derived from this file's location — never from the process CWD.
_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Application settings, overridable via environment variables (.env)."""

    # env_file is anchored to backend/ (not the process CWD): scripts run from
    # the repo root must load the same backend/.env as uvicorn run from backend/.
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[1] / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )
    database_url: str = "postgresql+psycopg://int102:int102@localhost:5433/int102"

    # Auth (M10). Opaque server-side session tokens in an httpOnly cookie —
    # no JWT, no signing secret (the DB stores sha256(token) only). Secure
    # flag stays off for local plain-HTTP; set SESSION_COOKIE_SECURE=true
    # behind TLS.
    session_ttl_hours: int = 168  # 7 days, absolute (no sliding refresh)
    session_cookie_secure: bool = False
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

    # Judge node (M3). Fallback model configurable: Groq announced (2026-06-17)
    # the retirement of llama-3.3-70b-versatile for free/dev tiers (~2026-08-16).
    # A replacement must be SELECTED AND VALIDATED (JSON mode + grounding on the
    # dev split) before the cutoff — do NOT swap the default blindly: Groq's own
    # suggestion openai/gpt-oss-120b has reported structured-output regressions
    # (json_schema ignored, free-form text), so the json_object path + Pydantic
    # gate must be re-checked; qwen3 is an alternative candidate.
    # temperature 0 for determinism (still not guaranteed).
    judge_model: str = "mistral-large-latest"
    judge_fallback_model: str = "llama-3.3-70b-versatile"
    judge_temperature: float = 0.0
    # 429 backoff (spec §12: batch runs throttled to provider rate limits):
    # retries on the SAME provider before falling back, exponential from
    # judge_429_base_delay seconds, Retry-After honoured, capped at 30 s.
    judge_429_retries: int = 3
    judge_429_base_delay: float = 2.0


settings = Settings()