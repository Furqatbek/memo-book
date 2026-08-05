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
from app.services.telegram import send_production_notification

log = structlog.get_logger()

TOPIC_ORDER_RENDERED = "order.rendered"
TOPIC_BOOK_REMINDER = "book.reminder"


def _send_reminder(payload: dict) -> None:
    from app.services.email import build_reminder, send_email

    subject, text = build_reminder(payload)
    send_email(payload["email"], subject, text)


BACKOFF_BASE_S = 30
BACKOFF_CAP_S = 3600
MAX_ATTEMPTS = 8

# topic -> synchronous handler(payload). Handlers raise to signal failure.
HANDLERS: dict[str, Callable[[dict], None]] = {
    TOPIC_ORDER_RENDERED: send_production_notification,
    TOPIC_BOOK_REMINDER: _send_reminder,
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


def rendered_payload(order, book, interior_key: str, cover_key: str) -> dict:
    return {
        "order_id": str(order.id),
        "human_ref": order.human_ref,
        "customer_name": order.customer_name,
        "customer_phone": order.customer_phone,
        "page_count": book.page_count,
        "amount_minor": order.amount_minor,
        "currency": order.currency,
        "interior_key": interior_key,
        "cover_key": cover_key,
    }
