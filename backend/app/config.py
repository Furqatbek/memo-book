"""Application configuration. Env-var driven; every variable is documented in .env.example."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "memo-book-backend"
    env: str = "dev"  # dev | staging | prod
    debug: bool = False

    database_url: str = "postgresql+asyncpg://memobook:memobook@localhost:5432/memobook"
    # Where this deployment answers, for links that leave the building. A
    # reminder whose link reads "/editor/abc" is not clickable in an email
    # and is useless in a Telegram message; with this set, both become
    # absolute.
    public_base_url: str = ""
    # A seasonal line appended to every draft reminder (Change 4), e.g.
    # "Order by 25 November for delivery before New Year." Empty for most
    # of the year: switching it on is a config change and a restart, no
    # code. It is appended rather than templated so that turning it off
    # can never leave a half-sentence behind.
    reminder_seasonal_note: str = ""
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint_url: str = "http://localhost:9000"
    # Public storage URL browsers use (presigned upload/display links).
    # Empty = same as s3_endpoint_url. Split them when the internal address
    # differs from the public one (compose networks, tunnels, VPS).
    s3_public_url: str = ""
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
    # The admin console: low, because the only legitimate caller is one
    # person clicking, and the only illegitimate one is guessing the token.
    rate_limit_admin_per_min: int = 60
    # The public order page (reference + phone). A wrong phone answers exactly
    # like an unknown reference, on purpose — which means guessing is the only
    # attack available, and volume is the only thing that makes it work. A
    # customer refreshing their own order does so a handful of times (A77).
    rate_limit_order_status_per_min: int = 20
    # Funnel events from the browser (Change 3). A real visitor sends a
    # handful in a session; the cap is here so that a page stuck in a loop,
    # or somebody with a script, cannot fill the table faster than anybody
    # notices. Generous, because dropping a real event silently skews a
    # metric and that is the failure this instrumentation exists to avoid.
    rate_limit_events_per_min: int = 120
    # Shared book pages (CR-003-1). Unauthenticated by design — the token
    # is the credential — so this is the limit that makes enumeration
    # pointless as well as hopeless. Generous because a family group chat
    # opening the same link is a burst of real traffic.
    rate_limit_share_per_min: int = 90

    # --- Admin console (A72) ---
    # The shared secret the console signs in with. EMPTY DISABLES THE ADMIN
    # API ENTIRELY, deliberately: a deploy that forgets to set it must fail
    # closed, not ship an open door. Generate with
    # `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
    admin_token: str = ""

    # --- Payments (Milestone 9) ---
    # Dev mode: the "dev" provider treats any correctly-signed webhook as a
    # completed payment. Disable and integrate a real acquirer for production.
    dev_payments_enabled: bool = True
    dev_payment_secret: str = "dev-secret-change-me"

    # A sheet of paper carries this many printed sides. 2 = ordinary
    # double-sided printing, so a 16-sheet book is 32 designed pages.
    # Set to 1 if the printer uses photo-mount lay-flat binding, where
    # sheets are printed on one side and glued back-to-back (A63).
    sides_per_sheet: int = 2

    # Card-transfer pilot: shown on the order page while payment is pending;
    # the operator confirms received transfers with scripts/confirm_payment.py.
    # Empty = the card block never appears.
    pay_card_number: str = ""
    pay_card_holder: str = ""
    # Card-transfer pilot, trust-first flow: checkout immediately confirms the
    # order (render + printer notification run right away) instead of waiting
    # for a payment callback. The operator verifies the bank transfer before
    # sending anything to print. Turn OFF when a real acquirer is integrated.
    auto_confirm_orders: bool = False

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

    # PLACEHOLDER prices per SHEET tier, UZS in tiyin (1 sum = 100 tiyin).
    # Set the real prices before going live.
    price_minor_16: int = 29_900_000   # 299,000 UZS
    price_minor_32: int = 39_900_000   # 399,000 UZS
    price_minor_48: int = 49_900_000   # 499,000 UZS
    price_minor_96: int = 79_900_000   # 799,000 UZS

    # The switch that says the numbers above are real. Off by default, and
    # deliberately separate from the numbers themselves: a placeholder price
    # is a perfectly valid integer, so nothing else can tell the difference
    # between "299,000 because that is the price" and "299,000 because
    # somebody had to write something". While it is off the API quotes prices
    # but refuses to create an order (A74).
    prices_confirmed: bool = False

    # How long an order may sit in `rendering` before the watchdog declares
    # the worker dead and moves it to render_failed, which alerts and is
    # retryable (A76). This is a "certainly dead" threshold, not a deadline:
    # a real render of the largest book takes a couple of minutes, and a job
    # that is merely slow rather than dead walks itself back when it
    # finishes. Err generous.
    render_stall_after_s: int = 1800

    telegram_bot_token: str = ""
    # The bot's @name, needed to build a customer deep link (Change 2).
    # Without it there is no link to offer, and the editor hides the option
    # rather than showing one that lands nowhere.
    telegram_bot_username: str = ""
    telegram_chat_id: str = ""

    # Inbound control (A96). Telegram is an UNAUTHENTICATED surface — A76 is
    # why the attention alert carries no customer PII — so letting it move
    # orders is off unless BOTH of these are set, and the webhook answers 404
    # until they are. A bot that can report without being able to act is the
    # safe default, and it is what every existing deployment keeps.
    #
    # The secret is the value given to Telegram's setWebhook as
    # `secret_token`; it comes back on every delivery in the
    # X-Telegram-Bot-Api-Secret-Token header and is what proves the request
    # is Telegram's rather than someone who guessed the URL.
    telegram_webhook_secret: str = ""
    # Comma-separated Telegram USER ids (not the chat id) allowed to press
    # the buttons. Being in the chat is not enough: the chat holds 7-day
    # signed links to every print file, so whoever is in it can already read
    # a great deal, and acting has to be a smaller circle than reading.
    telegram_control_user_ids: str = ""

    # --- Frontend editor ---
    # Comma-separated origins allowed to call the API from a browser
    # (e.g. "https://furqatbek.github.io"). Empty = no cross-origin access;
    # an editor served from this same origin (EDITOR_DIR) needs none.
    cors_origins: str = ""
    # Serve the static editor from this directory at /editor. Dev convenience —
    # in production the editor is a static site on its own host/CDN.
    editor_dir: str = ""
    # Serve the admin console from this directory at /admin. The page itself
    # is public static markup; everything it can DO is gated on ADMIN_TOKEN.
    admin_dir: str = ""
    # Serve the marketing site (all language versions + assets) from this
    # directory at /. Lets one VPS host the whole product on one origin;
    # API routes always win over the static mount.
    site_dir: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
