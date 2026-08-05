"""Telegram delivery (R9): the production notification carries the order
reference, customer contact, page count, amount, and TIME-LIMITED SIGNED
DOWNLOAD URLS for the interior and cover PDFs — never the file itself
(the bot upload cap is ~50MB; a 96-page book exceeds it).

The payload contains PII (name, phone): it is never logged (spec Part 11);
only the order reference appears in log events.
"""
import httpx

from app import storage
from app.config import get_settings
from app.domain.money import from_minor

ARTIFACT_URL_EXPIRY_S = 7 * 24 * 3600  # spec Part 11: 7 days for artifacts


class TelegramError(Exception):
    pass


def build_production_message(payload: dict) -> str:
    """Presigning happens at DELIVERY time, so retried messages carry fresh
    links rather than expired ones."""
    interior_url = storage.presign_get(payload["interior_key"],
                                       expires_in=ARTIFACT_URL_EXPIRY_S)
    cover_url = storage.presign_get(payload["cover_key"],
                                    expires_in=ARTIFACT_URL_EXPIRY_S)
    major, minor_part = from_minor(int(payload["amount_minor"]))
    amount = f"{major:,}".replace(",", " ") + (f".{minor_part:02d}" if minor_part else "")
    return (
        f"📖 New order {payload['human_ref']}\n"
        f"Customer: {payload['customer_name']}, {payload['customer_phone']}\n"
        f"Pages: {payload['page_count']}\n"
        f"Amount: {amount} {payload.get('currency', 'UZS')}\n"
        f"Interior PDF (7-day link):\n{interior_url}\n"
        f"Cover PDF (7-day link):\n{cover_url}"
    )


def _post_telegram(text: str) -> None:
    """Synchronous send; runs inside the outbox worker. Raising here is how a
    delivery attempt fails and gets retried with backoff."""
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        raise TelegramError("telegram credentials are not configured")
    resp = httpx.post(
        f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
        json={"chat_id": settings.telegram_chat_id, "text": text,
              "disable_web_page_preview": True},
        timeout=15,
    )
    if resp.status_code != 200:
        raise TelegramError(f"telegram sendMessage failed: {resp.status_code} "
                            f"{resp.text[:200]}")


def send_production_notification(payload: dict) -> None:
    _post_telegram(build_production_message(payload))
