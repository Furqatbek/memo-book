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

    # --- Rate limiting (Milestone 13; per IP, per minute) ---
    rate_limit_enabled: bool = True
    rate_limit_book_create_per_min: int = 30
    rate_limit_upload_url_per_min: int = 240
    rate_limit_webhook_per_min: int = 120

    # --- Payments (Milestone 9) ---
    # Dev mode: the "dev" provider treats any correctly-signed webhook as a
    # completed payment. Disable and integrate a real acquirer for production.
    dev_payments_enabled: bool = True
    dev_payment_secret: str = "dev-secret-change-me"

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

    # PLACEHOLDER prices per tier, UZS in tiyin (1 sum = 100 tiyin).
    # Set the real prices before going live.
    price_minor_16: int = 29_900_000   # 299,000 UZS
    price_minor_32: int = 39_900_000   # 399,000 UZS
    price_minor_48: int = 49_900_000   # 499,000 UZS
    price_minor_96: int = 79_900_000   # 799,000 UZS

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # --- Frontend editor ---
    # Comma-separated origins allowed to call the API from a browser
    # (e.g. "https://furqatbek.github.io"). Empty = no cross-origin access;
    # an editor served from this same origin (EDITOR_DIR) needs none.
    cors_origins: str = ""
    # Serve the static editor from this directory at /editor. Dev convenience —
    # in production the editor is a static site on its own host/CDN.
    editor_dir: str = ""
    # Serve the marketing site (all language versions + assets) from this
    # directory at /. Lets one VPS host the whole product on one origin;
    # API routes always win over the static mount.
    site_dir: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
