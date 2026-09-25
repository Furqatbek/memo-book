"""Transactional outbox (spec Part 8).

`enqueue` only ADDS the row — the caller commits it together with the state
change it announces. Without that, a Telegram outage would roll back a
successful payment, or a payment would succeed and the notification silently
vanish. Delivery is at-least-once with exponential backoff; handlers must
tolerate duplicates.
"""
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import anyio
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbox import OutboxMessage, OutboxStatus
from app.services.telegram import (
    send_attention_alert,
    send_production_notification,
    send_receipt_notification,
)

log = structlog.get_logger()

TOPIC_ORDER_RENDERED = "order.rendered"
TOPIC_BOOK_REMINDER = "book.reminder"
TOPIC_ORDER_ATTENTION = "order.attention"
TOPIC_ORDER_RECEIPT = "order.receipt"
# The same reminder, down the channel people in this market actually read
# (Change 2). A separate topic rather than a flag in the payload so the
# dispatch table stays the place you look to see what can be sent.
TOPIC_BOOK_REMINDER_TG = "book.reminder.telegram"
# Anything the bot says to a CUSTOMER — the confirmation after linking, the
# acknowledgement of /stop. Through the outbox like everything else: a
# Telegram outage must not make the webhook throw, and a confirmation that
# was not delivered has to be retried rather than lost.
TOPIC_TELEGRAM_REPLY = "telegram.reply"
# A production update by email, for customers who never linked Telegram
# (CR-003-2). The Telegram ones reuse the reminder topic — it is the same
# act: a message with a picture to one chat.
TOPIC_ORDER_PROGRESS = "order.progress"


def _send_telegram_message(payload: dict) -> None:
    """Never called inline from a request handler — this is the outbox
    worker, with the same at-least-once delivery and backoff every other
    notification gets. A customer who blocked the bot makes Telegram answer
    403, `send_to` raises, and the message retries and then gives up like
    any other failure."""
    from app import storage
    from app.services import telegram

    # Presigned HERE rather than when the reminder was queued: this message
    # may have waited out an outage and several backoffs, and a link minted
    # an hour ago would arrive expired.
    key = payload.get("photo_key")
    if key:
        url = storage.presign_get(key, expires_in=REMINDER_PHOTO_EXPIRY_S)
        telegram.send_photo_to(payload["chat_id"], url, payload["text"])
        return
    telegram.send_to(payload["chat_id"], payload["text"])


def _send_progress_email(payload: dict) -> None:
    from app.services.email import send_email

    send_email(payload["email"],
               f"Your photo book {payload['human_ref']}",
               payload["text"])


def _send_reminder(payload: dict) -> None:
    from app.services.email import build_reminder, send_email

    subject, text = build_reminder(payload)
    send_email(payload["email"], subject, text)


# Long enough that Telegram can fetch the picture even if it is slow, and
# that a reader opening the message tomorrow still sees it.
REMINDER_PHOTO_EXPIRY_S = 7 * 24 * 3600

BACKOFF_BASE_S = 30
BACKOFF_CAP_S = 3600
MAX_ATTEMPTS = 8

# topic -> synchronous handler(payload). Handlers raise to signal failure.
HANDLERS: dict[str, Callable[[dict], None]] = {
    TOPIC_ORDER_RENDERED: send_production_notification,
    TOPIC_BOOK_REMINDER: _send_reminder,
    TOPIC_BOOK_REMINDER_TG: _send_telegram_message,
    TOPIC_TELEGRAM_REPLY: _send_telegram_message,
    TOPIC_ORDER_PROGRESS: _send_progress_email,
    TOPIC_ORDER_ATTENTION: send_attention_alert,
    TOPIC_ORDER_RECEIPT: send_receipt_notification,
}


def enqueue(session: AsyncSession, topic: str, payload: dict) -> None:
    """Add an outbox row to the CURRENT transaction. The caller's commit makes
    the state change and the message atomic."""
    now = datetime.now(UTC)
    session.add(OutboxMessage(topic=topic, payload=payload,
                              status=OutboxStatus.PENDING.value,
                              attempts=0, next_attempt_at=now, created_at=now))


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(BACKOFF_CAP_S, BACKOFF_BASE_S * (2 ** attempts)))


async def deliver_pending(session: AsyncSession, limit: int = 20) -> int:
    """One worker pass: deliver due pending messages. Returns delivered count."""
    now = datetime.now(UTC)
    messages = (await session.execute(
        select(OutboxMessage)
        .where(OutboxMessage.status == OutboxStatus.PENDING.value,
               OutboxMessage.next_attempt_at <= now)
        .order_by(OutboxMessage.created_at)
        .limit(limit)
    )).scalars().all()

    delivered = 0
    for message in messages:
        handler = HANDLERS.get(message.topic)
        if handler is None:
            message.status = OutboxStatus.FAILED.value
            message.last_error = f"no handler for topic {message.topic}"
            await session.commit()
            continue
        try:
            await anyio.to_thread.run_sync(handler, message.payload)
        except Exception as exc:  # noqa: BLE001 — delivery boundary
            message.attempts += 1
            message.last_error = str(exc)[:500]
            if message.attempts >= MAX_ATTEMPTS:
                message.status = OutboxStatus.FAILED.value
                log.error("outbox.gave_up", message_id=str(message.id),
                          topic=message.topic, attempts=message.attempts)
            else:
                message.next_attempt_at = datetime.now(UTC) + _backoff(message.attempts)
                log.warning("outbox.retry_scheduled", message_id=str(message.id),
                            topic=message.topic, attempts=message.attempts)
            await session.commit()
            continue
        message.status = OutboxStatus.SENT.value
        await session.commit()
        delivered += 1
        log.info("outbox.sent", message_id=str(message.id), topic=message.topic)
    return delivered


def attention_payload(order, reason: str, detail: str | None = None) -> dict:
    """Deliberately thin. This message says an order needs a person and which
    one; the details live in the admin console, which is authenticated. A
    Telegram chat is not, particularly, so it carries no customer PII beyond
    the reference the operator needs to look the order up."""
    return {
        "human_ref": order.human_ref,
        "status": order.status,
        "reason": reason,
        "detail": (detail or "")[:500] or None,
    }


def receipt_payload(order) -> dict:
    """Thin like the attention alert, for the same reason (A76): this chat is
    not authenticated, so it gets the reference, the money and the receipt —
    not the customer.

    The KEY, not a URL. Presigning here would put a deadline on a message
    that has not been sent yet, so a delivery that waited out a Telegram
    outage would arrive with a link that no longer opens. The link is built
    at delivery time, on every attempt.
    """
    return {
        "human_ref": order.human_ref,
        # As it was when the receipt landed. Nothing is pressed from this
        # message, so it is a fact for reading, not a keyboard to trust.
        "status": order.status,
        "amount_minor": order.amount_minor,
        "currency": order.currency,
        "receipt_key": order.receipt_key,
        "receipt_content_type": order.receipt_content_type,
        "receipt_bytes": order.receipt_bytes,
    }


def rendered_payload(order, book, interior_key: str, cover_key: str,
                     soft: list[dict] | None = None,
                     gift=None) -> dict:
    return {
        # Everything the person packing the box needs to do it differently
        # (CR-003-3). Flattened into the payload rather than looked up at
        # delivery, so a message that waited out an outage still carries it.
        "gift": None if gift is None else {
            "recipient_name": gift.recipient_name,
            "recipient_phone": gift.recipient_phone,
            "recipient_address": gift.recipient_address,
            "gift_message": gift.gift_message,
            "deliver_after": (gift.deliver_after.isoformat()
                              if gift.deliver_after else None),
            "hide_price": gift.hide_price,
        },
        # Pages that will print soft (A79). The printer sees this before the
        # ink goes on, which is the last cheap moment to stop a reprint.
        "soft_pages": soft or [],
        "order_id": str(order.id),
        "human_ref": order.human_ref,
        # Carried so the Telegram message can offer the right buttons without
        # a second query at delivery time (A96). It is the status when the
        # message was enqueued; a press is re-checked against the live order.
        "status": order.status,
        "customer_name": order.customer_name,
        "customer_phone": order.customer_phone,
        "customer_address": order.customer_address,
        "customer_email": order.customer_email,
        "page_count": book.page_count,
        "book_type": book.book_type,
        "amount_minor": order.amount_minor,
        "currency": order.currency,
        "interior_key": interior_key,
        "cover_key": cover_key,
    }
