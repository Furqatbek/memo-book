"""Telling the customer what is happening to their book — CR-003-2.

Thirty days of silence is what generates support messages, anxiety and
cancellation requests. Three messages with real photographs turn the wait
into anticipation — and customers screenshot and post them, which produces
free content out of a process that was happening anyway.

THREE TOUCHES, NOT SIX. The operator moves the order through as many
stages as they like; the customer hears about printing, binding and
shipping and nothing else. A bot that narrates every internal step gets
muted, and then the one message that mattered is muted too.

IDEMPOTENT PER (order, status). An operator fat-fingering the same
transition twice must not send the customer the same message twice — and
at this volume the operator is one person on a phone, so it will happen.
"""
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.states import OrderStatus
from app.models.book import Book
from app.models.order import Order, OrderEvent
from app.services import outbox

log = structlog.get_logger()

# Only these three reach the customer.
CUSTOMER_STAGES = {
    OrderStatus.PRINTING.value: (
        "Your book is on the press. Here's the first page coming off."),
    OrderStatus.BINDING.value: (
        "Being bound now — this is the lay-flat spine that lets every "
        "spread open completely."),
    OrderStatus.SHIPPED.value: "Packed and on its way.",
}

# On the last message only. An invitation, not a demand, and the single
# place we ask a customer for anything.
TAG_US = "When it arrives, we'd love to see it — tag us."

# Marks an already-sent customer message in the order's own audit trail,
# which is where idempotency is decided: no new table for a fact the audit
# log already holds.
SENT_NOTE = "customer notified"


async def already_notified(session: AsyncSession, order_id: uuid.UUID,
                           status: str) -> bool:
    return (await session.execute(
        select(OrderEvent.id).where(
            OrderEvent.order_id == order_id,
            OrderEvent.to_status == status,
            OrderEvent.note.like(f"{SENT_NOTE}%"),
        ).limit(1)
    )).scalar_one_or_none() is not None


def compose(status: str, note: str | None, eta: str | None) -> str:
    parts = [CUSTOMER_STAGES[status]]
    if status == OrderStatus.SHIPPED.value and eta:
        parts[0] = f"{parts[0]} Expected {eta}."
    if note:
        parts.append(note.strip())
    if status == OrderStatus.SHIPPED.value:
        parts.append(TAG_US)
    return "\n\n".join(p for p in parts if p)


async def notify(session: AsyncSession, order: Order, status: str, *,
                 photo_url: str | None = None, note: str | None = None,
                 eta: str | None = None) -> bool:
    """Queue the customer's message for this stage. Returns whether one was
    queued — False is the ordinary answer for a stage nobody hears about,
    or a repeat.

    Never sends inline: this is the outbox, with the same at-least-once
    delivery and backoff every other notification gets, so a Telegram
    outage cannot make an operator's status update fail.
    """
    if status not in CUSTOMER_STAGES:
        return False
    if await already_notified(session, order.id, status):
        log.info("production.notify_skipped_duplicate",
                 order=order.human_ref, status=status)
        return False

    book = (await session.execute(
        select(Book).where(Book.id == order.book_id))).scalar_one()

    # A GIFT goes to the buyer, never the recipient (CR-003-3). The whole
    # point of a gift is that the person receiving it does not know, and a
    # production update is exactly the message that would spoil it.
    text = compose(status, note, eta)
    if book.telegram_chat_id is not None:
        outbox.enqueue(session, outbox.TOPIC_BOOK_REMINDER_TG, {
            "book_id": str(book.id),
            "chat_id": book.telegram_chat_id,
            "text": text,
            "photo_key": photo_url,
        })
        channel = "telegram"
    elif order.customer_email:
        outbox.enqueue(session, outbox.TOPIC_ORDER_PROGRESS, {
            "order_id": str(order.id),
            "email": order.customer_email,
            "human_ref": order.human_ref,
            "status": status,
            "text": text,
        })
        channel = "email"
    else:
        # Nowhere to send it. Not an error: plenty of customers give a
        # phone number and nothing else, and the operator's own Telegram
        # notification already told them the order moved.
        log.info("production.no_channel", order=order.human_ref, status=status)
        return False

    session.add(OrderEvent(
        id=uuid.uuid4(), order_id=order.id,
        from_status=order.status, to_status=status,
        note=f"{SENT_NOTE} via {channel}", created_at=datetime.now(UTC)))
    log.info("production.notified", order=order.human_ref, status=status,
             channel=channel, with_photo=bool(photo_url))
    return True
