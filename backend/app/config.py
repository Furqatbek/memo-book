"""Application configuration. Env-var driven; every variable is documented in .env.example."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "memo-book-backend"
    env: str = "dev"  # dev | staging | prod
    debug: bool = False

    database_url: str = "postgresql+asyncpg://memobook:memobook@localhost:5432/memobook"
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "memobook"
    s3_region: str = "us-east-1"

    # Readiness probes must fail fast, not hang the endpoint.
    ready_check_timeout_s: float = 2.0

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
