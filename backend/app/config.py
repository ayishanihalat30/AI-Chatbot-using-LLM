from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

LANGUAGES = {
    "en": "English",
    "ml": "Malayalam",
    "hi": "Hindi",
    "ta": "Tamil",
    "kn": "Kannada",
    "te": "Telugu",
    "ar": "Arabic",
    "fr": "French",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = "sqlite+aiosqlite:///./dev.db"
    redis_url: str | None = None
    jwt_secret: str = Field(default="dev-insecure-change-me", min_length=8)
    access_token_minutes: int = 30
    refresh_token_days: int = 30
    cors_origins: str = "http://localhost:3000"

    # Chat / vision: any OpenAI-compatible endpoint. Defaults target a local Ollama server.
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str | None = None
    chat_model: str = "llama3.2"
    fallback_chat_models: str = ""  # comma-separated, tried if the primary is unavailable
    vision_model: str = ""  # e.g. "qwen2.5vl" (Ollama) or a hosted vision model; empty = local RapidOCR only

    # Embeddings: "local" (fastembed, no server needed) or "api" (server /embeddings)
    embed_backend: str = "local"
    embed_model: str = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
    embed_dim: int = 768

    # Speech-to-text: "local" (faster-whisper) or "api" (server /audio/transcriptions)
    transcribe_backend: str = "local"
    transcribe_model: str = "small"
    model_cache_dir: str = "./model_cache"  # downloaded embedding / whisper weights

    blob_read_write_token: str | None = None
    upload_dir: str = "./uploads"
    max_upload_mb: int = 100

    rate_limit_auth: str = "10/minute"
    rate_limit_chat: str = "30/minute"
    rate_limit_default: str = "120/minute"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_prod(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.is_prod and s.jwt_secret.startswith("dev-insecure"):
        raise RuntimeError("JWT_SECRET must be set in production")
    return s
