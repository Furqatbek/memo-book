"""Asking for a review, once — CR-003-9.

Seven days after the book was delivered, one message. No follow-up, ever.
A second ask converts almost nobody and costs the goodwill of somebody who
has just spent real money and been pleased about it.

What comes back is stored and shown to the operator. Nothing is published
by this module, and nothing should be: the site's review list is
hand-curated in `assets/reviews.js`, and a person copies an approved review
into it. The honesty rules the whole product is built on apply here with no
exceptions —

    never publish without the permission box;
    never edit a review's wording;
    never invent one.

— and the shortest way to keep all three true is for the publishing step to
require a human who has read the row.
"""
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domain.states import OrderStatus
from app.models.book import Book
from app.models.order import Order, OrderEvent
from app.models.review import ReviewRequest

log = structlog.get_logger()

TOKEN_BYTES = 24
# Long enough that the book has been looked through and shown to somebody,
# short enough that it still feels like the same event.
ASK_AFTER_DAYS = 7
TEXT_MAX = 2000
NAME_MAX = 80

# Said once, plainly, and it asks for a photo without requiring one. The
# word "honest" is load-bearing: it is an invitation to say what they
# actually thought, and a review section that only ever contains praise is
# one nobody believes.
ASK_TEXT = (
    "How is your book?\n\n"
    "We'd love an honest review — and a photo of it, if you're willing.")


def review_url(token: str) -> str:
    base = (get_settings().public_base_url or "").rstrip("/")
    return f"{base}/r/{token}" if base else f"/r/{token}"


async def delivered_at(session: AsyncSession,
                       order_id: uuid.UUID) -> datetime | None:
    """When this order was marked delivered, from its own audit trail.

    The order row carries a status, not a history; the event rows are
    where "when" lives, and using them means a status set by hand in the
    console counts exactly as one set by any other path.
    """
    return (await session.execute(
        select(OrderEvent.created_at).where(
            OrderEvent.order_id == order_id,
            OrderEvent.to_status == OrderStatus.DELIVERED.value)
        .order_by(OrderEvent.created_at.asc()).limit(1)
    )).scalar_one_or_none()


async def due(session: AsyncSession, now: datetime | None = None,
              limit: int = 50) -> list[Order]:
    """Delivered orders that have waited long enough and have never been
    asked. The `outerjoin ... is None` is what makes the ask once-only."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=ASK_AFTER_DAYS)
    rows = (await session.execute(
        select(Order, OrderEvent.created_at)
        .join(OrderEvent, OrderEvent.order_id == Order.id)
        .outerjoin(ReviewRequest, ReviewRequest.order_id == Order.id)
        .where(Order.status == OrderStatus.DELIVERED.value,
               OrderEvent.to_status == OrderStatus.DELIVERED.value,
               OrderEvent.created_at <= cutoff,
               ReviewRequest.order_id.is_(None))
        .limit(limit)
    )).all()
    # One row per order even if an order somehow has two delivered events.
    seen: dict[uuid.UUID, Order] = {}
    for order, _ in rows:
        seen.setdefault(order.id, order)
    return list(seen.values())


async def ask(session: AsyncSession, order: Order,
              now: datetime | None = None) -> bool:
    """Queue the one request for this order. Returns whether one was sent.

    The row is written in the SAME transaction as the outbox message, so a
    crash between them cannot produce either a customer who is asked twice
    or a row claiming we asked when we did not.
    """
    from app.domain.events import EventType
    from app.services import funnel, outbox

    if await existing_for_order(session, order.id) is not None:
        return False

    book = (await session.execute(
        select(Book).where(Book.id == order.book_id))).scalar_one()
    token = secrets.token_urlsafe(TOKEN_BYTES)
    text = f"{ASK_TEXT}\n\n{review_url(token)}"

    if book.telegram_chat_id is not None:
        outbox.enqueue(session, outbox.TOPIC_BOOK_REMINDER_TG, {
            "book_id": str(book.id), "chat_id": book.telegram_chat_id,
            "text": text, "photo_key": None})
        channel = "telegram"
    elif order.customer_email:
        outbox.enqueue(session, outbox.TOPIC_ORDER_PROGRESS, {
            "order_id": str(order.id), "email": order.customer_email,
            "human_ref": order.human_ref, "status": "review_request",
            "text": text})
        channel = "email"
    else:
        # Nowhere to send it, and nothing to record: leaving the row out
        # means this order is asked properly if a contact detail ever
        # arrives, instead of being permanently marked as asked.
        log.info("review.no_channel", order=order.human_ref)
        return False

    session.add(ReviewRequest(order_id=order.id, token=token,
                              requested_at=now or datetime.now(UTC)))
    await funnel.emit_for_book(session, EventType.REVIEW_REQUESTED,
                               order.book_id, properties={"channel": channel})
    await session.commit()
    log.info("review.requested", order=order.human_ref, channel=channel)
    return True


async def run_requests(session: AsyncSession,
                       now: datetime | None = None) -> int:
    sent = 0
    for order in await due(session, now):
        sent += bool(await ask(session, order, now))
    return sent


async def existing_for_order(session: AsyncSession,
                             order_id: uuid.UUID) -> ReviewRequest | None:
    return (await session.execute(
        select(ReviewRequest).where(ReviewRequest.order_id == order_id)
    )).scalar_one_or_none()


async def find(session: AsyncSession, token: str) -> ReviewRequest | None:
    if not token or len(token) > 64:
        return None
    return (await session.execute(
        select(ReviewRequest).where(ReviewRequest.token == token)
    )).scalar_one_or_none()


def _clean(raw: str | None, limit: int) -> str | None:
    if not raw:
        return None
    text = "".join(c for c in raw if c.isprintable() or c in "\n\r\t").strip()
    return text[:limit] or None


async def submit(session: AsyncSession, review: ReviewRequest, *,
                 text: str, display_name: str | None, city: str | None,
                 lang: str | None, may_publish: bool,
                 photo_key: str | None = None) -> ReviewRequest:
    """Store what they wrote, exactly as they wrote it.

    Re-submitting overwrites: somebody who presses back and corrects a typo
    should end up with the corrected version, not two rows for a person who
    thinks they left one review.
    """
    from app.domain.events import EventType
    from app.services import funnel

    first = review.submitted_at is None
    review.text = _clean(text, TEXT_MAX)
    review.display_name = _clean(display_name, NAME_MAX)
    review.city = _clean(city, NAME_MAX)
    review.lang = (lang or "")[:8] or None
    review.may_publish = bool(may_publish)
    if photo_key:
        review.photo_key = photo_key
    review.submitted_at = datetime.now(UTC)

    if first:
        order = (await session.execute(
            select(Order).where(Order.id == review.order_id))).scalar_one()
        await funnel.emit_for_book(
            session, EventType.REVIEW_SUBMITTED, order.book_id,
            properties={"may_publish": review.may_publish})
    await session.commit()
    log.info("review.submitted", order_id=str(review.order_id),
             may_publish=review.may_publish, with_photo=bool(review.photo_key))
    return review
