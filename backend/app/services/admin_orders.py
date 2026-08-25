"""What the admin console does to orders (A73).

This is the daily job the operator used to do over SSH with
`confirm_payment.py`, `order_status.py` and `artifacts.py`. Same machinery,
same guarantees — every status change goes through `apply_transition`, so
the state machine and the append-only audit trail apply exactly as they do
to an acquirer's webhook. Nothing here assigns `order.status` directly.

Two things are deliberately NOT here:

* **Deleting an order.** There is no such operation anywhere in the system;
  the audit trail is the record of what happened to someone's money.
* **A "mark it whatever I say" endpoint.** The console offers the
  transitions the state machine allows from where the order actually is, and
  the server decides that, not the page.
"""
import uuid
from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import queue, storage
from app.domain.errors import DomainError, ErrorCode
from app.domain.states import EFFECTS_ON_ENTER, ORDER_TRANSITIONS, Effect, OrderStatus
from app.models.book import Book
from app.models.order import Order, OrderEvent
from app.models.payment import PdfArtifact
from app.services.orders import apply_transition, cancel_order, normalize_phone
from app.services.payments import mark_paid

# How long a print-file link the operator opens stays good. Long enough to
# forward to the printer and for them to come back to it.
ARTIFACT_URL_EXPIRY_S = 7 * 24 * 3600

# Orders whose bank transfer may still need matching against the account —
# everything before the operator's own "sent to production" step. The same
# definition scripts/confirm_payment.py uses for its --list.
UNVERIFIED_STATUSES = (
    OrderStatus.PENDING_PAYMENT.value, OrderStatus.PAID.value,
    OrderStatus.RENDERING.value, OrderStatus.RENDER_FAILED.value,
    OrderStatus.RENDERED.value,
)

# The transitions a person is allowed to drive from the console. Rendering
# states are the worker's business, and `paid` has its own action because
# becoming paid does more than change a status.
OPERATOR_TARGETS = frozenset({
    OrderStatus.SENT_TO_PRODUCTION.value,
    OrderStatus.SHIPPED.value,
    OrderStatus.DELIVERED.value,
    OrderStatus.CANCELLED.value,
    OrderStatus.REFUNDED.value,
    OrderStatus.RENDERING.value,      # the retry path out of render_failed (A5)
})


# Separators people put in a phone number. Both the stored value and the
# search term are reduced to digits before comparing, because the stored
# value is whatever the customer typed — "+998 90 123-45-67" — and the
# operator searching for it will type it a different way.
_PHONE_SEPARATORS = (" ", "+", "-", "(", ")", ".", "\u00a0")


def _phone_digits(column):
    expr = column
    for ch in _PHONE_SEPARATORS:
        expr = func.replace(expr, ch, "")
    return expr


@dataclass(frozen=True)
class OrderRow:
    order: Order
    book: Book | None


def _next_statuses(order: Order) -> list[str]:
    """What this order can become next, from the state machine itself rather
    than a list in the page that would drift away from it."""
    allowed = ORDER_TRANSITIONS.get(OrderStatus(order.status), frozenset())
    return sorted(s.value for s in allowed if s.value in OPERATOR_TARGETS)


def serialize_row(row: OrderRow) -> dict:
    order, book = row.order, row.book
    return {
        "human_ref": order.human_ref,
        "status": order.status,
        "customer_name": order.customer_name,
        "customer_phone": order.customer_phone,
        "amount_minor": order.amount_minor,
        "currency": order.currency,
        "page_count": book.page_count if book else None,
        "book_type": book.book_type if book else None,
        "created_at": order.created_at,
        "paid_at": order.paid_at,
        "next_statuses": _next_statuses(order),
        "awaiting_payment_check": order.status in UNVERIFIED_STATUSES,
    }


async def list_orders(session: AsyncSession, *, status: str | None = None,
                      query: str | None = None, limit: int = 100) -> list[dict]:
    stmt = (select(Order, Book)
            .join(Book, Book.id == Order.book_id, isouter=True)
            .order_by(Order.created_at.desc())
            .limit(max(1, min(limit, 500))))
    if status == "open":
        # The working set: everything that still needs something doing.
        stmt = stmt.where(Order.status.notin_((
            OrderStatus.DELIVERED.value, OrderStatus.CANCELLED.value,
            OrderStatus.REFUNDED.value)))
    elif status:
        stmt = stmt.where(Order.status == status)
    if query:
        term = query.strip()
        digits = normalize_phone(term)
        clauses = [Order.human_ref.ilike(f"%{term.upper()}%"),
                   Order.customer_name.ilike(f"%{term}%")]
        if digits:
            clauses.append(_phone_digits(Order.customer_phone)
                           .like(f"%{digits}%"))
        stmt = stmt.where(or_(*clauses))
    rows = (await session.execute(stmt)).all()
    return [serialize_row(OrderRow(order=o, book=b)) for o, b in rows]


async def _load(session: AsyncSession, human_ref: str) -> OrderRow:
    ref = human_ref.strip().upper()
    row = (await session.execute(
        select(Order, Book).join(Book, Book.id == Order.book_id, isouter=True)
        .where(Order.human_ref == ref)
    )).first()
    if row is None:
        raise DomainError(ErrorCode.ORDER_NOT_FOUND, f"no order {ref}")
    return OrderRow(order=row[0], book=row[1])


async def order_detail(session: AsyncSession, human_ref: str) -> dict:
    """Everything the operator needs on one screen: who, what, where it is,
    what happened to it, and the print files."""
    row = await _load(session, human_ref)
    order = row.order

    events = (await session.execute(
        select(OrderEvent).where(OrderEvent.order_id == order.id)
        .order_by(OrderEvent.created_at)
    )).scalars()

    artifacts = (await session.execute(
        select(PdfArtifact).where(PdfArtifact.order_id == order.id)
    )).scalars()

    return {
        **serialize_row(row),
        "customer_address": order.customer_address,
        "customer_email": order.customer_email,
        "provider": order.provider,
        "provider_txn_id": order.provider_txn_id,
        "preview_confirmed_at": order.preview_confirmed_at,
        "rendered_at": order.rendered_at,
        "shipped_at": order.shipped_at,
        "book_status": row.book.status if row.book else None,
        "events": [{"from": e.from_status, "to": e.to_status,
                    "note": e.note, "at": e.created_at} for e in events],
        # The print files, for the operator only. Customers never see these
        # (public_status exposes them in dev environments alone).
        "artifacts": [{"kind": a.kind, "bytes": a.size_bytes,
                       "sha256": a.sha256,
                       "url": storage.presign_get(a.storage_key,
                                                  ARTIFACT_URL_EXPIRY_S)}
                      for a in artifacts],
    }


async def confirm_payment(session: AsyncSession, human_ref: str,
                          note: str | None = None) -> dict:
    """"The transfer arrived." Goes through the same `mark_paid` an acquirer
    callback would, so the book locks to `ordered` and the render is enqueued
    exactly once. Confirming twice is a no-op rather than a second render."""
    row = await _load(session, human_ref)
    order = row.order
    if order.status != OrderStatus.PENDING_PAYMENT.value:
        if order.status in UNVERIFIED_STATUSES:
            return {**await order_detail(session, human_ref), "already": True}
        raise DomainError(ErrorCode.ILLEGAL_TRANSITION,
                          f"cannot confirm payment on a {order.status} order",
                          {"order_status": order.status})
    await mark_paid(session, order,
                    note=note or "card transfer confirmed in the admin console",
                    provider="card-transfer", txn_id=None)
    return {**await order_detail(session, human_ref), "already": False}


async def set_status(session: AsyncSession, human_ref: str, target: str,
                     note: str | None = None) -> dict:
    """Advance an order. Refuses anything the state machine forbids, and
    anything whose side effects this path cannot honour — a status that
    should enqueue a render or alert somebody must not be reachable by
    someone clicking a button that only writes a row."""
    if target not in OPERATOR_TARGETS:
        raise DomainError(ErrorCode.ILLEGAL_TRANSITION,
                          f"{target} is not an operator action",
                          {"allowed": sorted(OPERATOR_TARGETS)})
    row = await _load(session, human_ref)
    order = row.order

    if target == OrderStatus.CANCELLED.value:
        # Cancels the order AND unlocks the book, so the customer can edit or
        # re-order rather than being stranded.
        await cancel_order(session, order.id,
                           note=note or "cancelled in the admin console")
        return await order_detail(session, human_ref)

    effects = tuple(EFFECTS_ON_ENTER.get(OrderStatus(target), ()))
    unhandled = [e for e in effects if e is not Effect.NOTIFY_PRODUCTION]
    if unhandled:
        raise DomainError(
            ErrorCode.ILLEGAL_TRANSITION,
            f"entering {target} needs effects the console cannot run",
            {"effects": [e.value for e in unhandled]})

    apply_transition(session, order, OrderStatus(target),
                     note=note or "admin console")
    await session.commit()
    return await order_detail(session, human_ref)


async def resend_to_printer(session: AsyncSession, human_ref: str) -> dict:
    """Put the production message back on the Telegram outbox — for when the
    printer says they never got it, which is the one recovery the operator
    otherwise has no button for.

    Goes through the outbox rather than calling Telegram directly, so a
    Telegram outage retries on its own schedule instead of failing a click.
    """
    from app.services import outbox

    row = await _load(session, human_ref)
    order, book = row.order, row.book
    if order.status not in (OrderStatus.RENDERED.value,
                            OrderStatus.SENT_TO_PRODUCTION.value):
        raise DomainError(
            ErrorCode.ILLEGAL_TRANSITION,
            "there is nothing to send until the print files exist",
            {"order_status": order.status})
    keys = {a.kind: a.storage_key for a in (await session.execute(
        select(PdfArtifact).where(PdfArtifact.order_id == order.id)
    )).scalars()}
    if "interior" not in keys or "cover" not in keys:
        raise DomainError(ErrorCode.ILLEGAL_TRANSITION,
                          "the print files for this order are missing",
                          {"have": sorted(keys)})
    outbox.enqueue(session, outbox.TOPIC_ORDER_RENDERED,
                   outbox.rendered_payload(order, book, keys["interior"],
                                           keys["cover"]))
    await session.commit()
    if queue.eager():
        await outbox.deliver_pending(session)
    return await order_detail(session, human_ref)


async def order_id_for(session: AsyncSession, human_ref: str) -> uuid.UUID:
    return (await _load(session, human_ref)).order.id
