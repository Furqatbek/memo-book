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

BOOK_TYPE_LABELS = {
    "love": "❤️ Love story",
    "travel": "✈️ Travel book",
    "birthday": "🎂 Birthday",
    "memory": "📸 Memory book",
}


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
    lines = [f"📖 New order {payload['human_ref']}"]
    book_type = BOOK_TYPE_LABELS.get(payload.get("book_type") or "")
    if book_type:
        lines.append(f"Type: {book_type}")
    lines.append(f"Pages: {payload['page_count']}")
    lines.append(f"Customer: {payload['customer_name']}, {payload['customer_phone']}")
    if payload.get("customer_address"):
        lines.append(f"Address: {payload['customer_address']}")
    if payload.get("customer_email"):
        lines.append(f"Email: {payload['customer_email']}")
    lines.append(f"Amount: {amount} {payload.get('currency', 'UZS')}")
    lines.append(f"Interior PDF (7-day link):\n{interior_url}")
    lines.append(f"Cover PDF (7-day link):\n{cover_url}")
    return "\n".join(lines)


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


def build_attention_message(payload: dict) -> str:
    """Short, and free of customer PII: the operator opens the console to see
    the rest, and unlike this chat the console is authenticated (A76)."""
    lines = [f"⚠️ Order {payload['human_ref']} needs you",
             f"Status: {payload.get('status', 'unknown')}",
             f"What happened: {payload.get('reason', 'unknown')}"]
    if payload.get("detail"):
        lines.append(f"Detail: {payload['detail']}")
    lines.append("Open the admin console → Orders to retry or cancel.")
    return "\n".join(lines)


def send_attention_alert(payload: dict) -> None:
    _post_telegram(build_attention_message(payload))
