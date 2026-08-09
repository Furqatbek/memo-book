"""Webhook handling (spec Part 8 + R10).

Order of operations is the security model:
1. signature verification BEFORE any parsing — an unsigned callback changes
   nothing, not even the audit table
2. parse into a provider-neutral event
3. idempotency: the (provider, event_id, method) tuple is recorded exactly
   once; a duplicate replays the response without re-executing side effects
4. the amount in the callback is never trusted — it must equal the stored
   order amount
5. only then may the order transition; entering `paid` is the one and only
   render trigger (R8)
"""
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import queue
from app.domain.errors import DomainError, ErrorCode
from app.domain.money import assert_amount_matches
from app.domain.states import BookStatus, Effect, OrderStatus, transition_book
from app.models.book import Book
from app.models.order import Order
from app.models.payment import PaymentEvent
from app.payments.base import ParsedEvent
from app.payments.registry import get_provider
from app.services.fulfillment import run_order_render
from app.services.orders import apply_transition

log = structlog.get_logger()

# Pay events on an order in any of these states are acknowledged without
# action: the payment has already been accepted and processed.
ALREADY_PAID_STATES = {
    OrderStatus.PAID.value, OrderStatus.RENDERING.value,
    OrderStatus.RENDER_FAILED.value, OrderStatus.RENDERED.value,
    OrderStatus.SENT_TO_PRODUCTION.value, OrderStatus.SHIPPED.value,
    OrderStatus.DELIVERED.value,
}


async def handle_webhook(session: AsyncSession, provider_name: str,
                         headers: dict[str, str], body: dict) -> dict:
    provider = get_provider(provider_name)

    if not provider.verify_webhook(headers, body):
        raise DomainError(ErrorCode.SIGNATURE_INVALID,
                          "webhook signature verification failed")

    event = provider.parse_event(body)

    order = await _find_order(session, event.human_ref)
    duplicate = not await _record_event(session, provider.name, event, order)
    if duplicate:
        # The unique-constraint rollback expired every loaded instance.
        order = await _find_order(session, event.human_ref)
    if order is None:
        raise DomainError(ErrorCode.ORDER_NOT_FOUND,
                          f"no order with reference {event.human_ref}")

    if event.method == "pay":
        return await _handle_pay(session, order, event, duplicate)
    return await _handle_cancel(session, order, duplicate)


async def _find_order(session: AsyncSession, human_ref: str) -> Order | None:
    return (await session.execute(
        select(Order).where(Order.human_ref == human_ref)
    )).scalar_one_or_none()


async def _record_event(session: AsyncSession, provider: str,
                        event: ParsedEvent, order: Order | None) -> bool:
    """Insert the idempotency row; False means this exact event was already
    processed (unique constraint), including races between concurrent
    deliveries."""
    session.add(PaymentEvent(
        provider=provider, provider_event_id=event.event_id,
        order_id=order.id if order else None, method=event.method,
        raw_payload=event.raw, received_at=datetime.now(UTC),
    ))
    try:
        await session.commit()
        return True
    except IntegrityError:
        await session.rollback()
        return False


async def _handle_pay(session: AsyncSession, order: Order,
                      event: ParsedEvent, duplicate: bool) -> dict:
    # Never trust the callback amount — R10's companion check. Applies to
    # duplicates too, so a replayed mismatch gets the same rejection.
    assert_amount_matches(order.amount_minor, event.amount_minor)

    if order.status in ALREADY_PAID_STATES:
        return _ok(order, duplicate=True)
    if order.status != OrderStatus.PENDING_PAYMENT.value:
        raise DomainError(ErrorCode.ILLEGAL_TRANSITION,
                          f"cannot mark a {order.status} order as paid",
                          {"order_status": order.status})

    effects = apply_transition(session, order, OrderStatus.PAID,
                               note=f"webhook {event.event_id}")
    order.provider = event.raw.get("provider") or "dev"
    order.provider_txn_id = event.event_id
    book = (await session.execute(
        select(Book).where(Book.id == order.book_id)
    )).scalar_one()
    transition_book(BookStatus(book.status), BookStatus.ORDERED)
    book.status = BookStatus.ORDERED.value
    await session.commit()
    log.info("payment.paid", order=order.human_ref, event_id=event.event_id)

    if Effect.ENQUEUE_RENDER in effects:  # exactly once per paid transition
        if queue.eager():
            await run_order_render(session, order.id)
        else:
            queue.enqueue_order_render(order.id)

    await session.refresh(order)
    return _ok(order, duplicate=duplicate)


async def _handle_cancel(session: AsyncSession, order: Order,
                         duplicate: bool) -> dict:
    if order.status == OrderStatus.CANCELLED.value:
        return _ok(order, duplicate=True)
    # A provider cancel applies only to unpaid orders — once money moved,
    # the path is a refund, never a webhook cancel. (The state machine also
    # allows operator cancels from later states; that power is the operator
    # CLI's, not the webhook's.)
    if order.status != OrderStatus.PENDING_PAYMENT.value:
        raise DomainError(ErrorCode.ILLEGAL_TRANSITION,
                          f"cannot cancel a {order.status} order via webhook",
                          {"order_status": order.status})
    apply_transition(session, order, OrderStatus.CANCELLED, "provider cancel")
    book = (await session.execute(
        select(Book).where(Book.id == order.book_id)
    )).scalar_one()
    transition_book(BookStatus(book.status), BookStatus.DRAFT)
    book.status = BookStatus.DRAFT.value
    await session.commit()
    log.info("payment.cancelled", order=order.human_ref)
    return _ok(order, duplicate=duplicate)


def _ok(order: Order, duplicate: bool) -> dict:
    return {"status": "ok", "order_status": order.status, "duplicate": duplicate}
