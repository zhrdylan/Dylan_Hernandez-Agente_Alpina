from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
REPORTS_DIR = DATA_DIR / "reports"
CACHE_DIR = BASE_DIR / ".cache"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    database_url: str = ""
    migration_database_url: str = ""

    chat_encryption_key: str = ""

    groq_api_key: str = ""
    groq_model_answer: str = "openai/gpt-oss-120b"
    groq_model_router: str = "openai/gpt-oss-20b"
    groq_model_fallback: str = "qwen/qwen3.8-27b"

    cohere_api_key: str = ""
    cohere_embed_model: str = "embed-multilingual-v3.0"
    cohere_embed_dim: int = 1024
    cohere_batch_size: int = 64
    cohere_timeout_seconds: float = 60.0
    cohere_max_retries: int = 5

    chunk_max_chars: int = 1200
    chunk_overlap_chars: int = 150
    chunk_min_chars: int = 20

    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = ""
    r2_endpoint: str = ""


    cors_allow_all: bool = False
    cors_allowed_origins: list[str] = Field(default_factory=list)
    trusted_hosts: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1", "[::1]"])
    rate_limit_ip: str = "300/minute"
    rate_limit_session: str = "120/minute"
    rate_limit_storage_uri: str = "memory://"

    @field_validator("cors_allowed_origins")
    @classmethod
    def validate_origins(cls, origins: list[str]) -> list[str]:
        for origin in origins:
            url = urlsplit(origin)
            if (
                url.scheme not in {"http", "https"} or not url.hostname
                or url.username is not None or "*" in origin
                or origin != f"{url.scheme}://{url.netloc}"
            ):
                raise ValueError("CORS_ALLOWED_ORIGINS debe contener orígenes HTTP(S) completos.")
        return origins

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() == "production"

    def __repr__(self) -> str:
        masked = {}
        for k, v in self.__dict__.items():
            if any(token in k.lower() for token in ("key", "url", "secret", "password", "uri")):
                masked[k] = "***" if v else ""
            else:
                masked[k] = v
        return f"Settings({masked})"


settings = Settings()


def ensure_project_dirs() -> None:
    for directory in (DATA_DIR, RAW_DIR, PROCESSED_DIR, REPORTS_DIR, CACHE_DIR):
        directory.mkdir(parents=True, exist_ok=True)
