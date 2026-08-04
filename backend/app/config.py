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

    # Run queue jobs inline instead of enqueueing to RQ (tests, simple dev).
    task_eager: bool = False

    # --- Render (Milestone 6) ---
    # "rgb" (canonical, deterministic) or "cmyk" (Ghostscript + printer ICC).
    # Both paths are supported so losing either printer capability is survivable.
    render_color_mode: str = "rgb"
    icc_profile_path: str = ""

    # PLACEHOLDER spine widths (mm) per page tier — replace with the printer's
    # real numbers before ANY cover goes to production (spec Part 7: a wrong
    # spine wraps the cover art onto the wrong face and wastes the print run).
    spine_mm_16: float = 4.0
    spine_mm_32: float = 6.0
    spine_mm_48: float = 8.0
    spine_mm_96: float = 14.0

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
