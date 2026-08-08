"""Checkout and order lifecycle (spec Parts 3 & 5).

Checkout gauntlet, in order:
1. auth + the book must still be an editable draft
2. confirmed_preview must be literally true (the recorded timestamp is the
   defence against "I didn't know I couldn't edit it")
3. the preview must exist, be ready, and match the current layout version
4. R1 tier gating — never allow checkout with fewer photos than pages
5. every page must actually hold a placement (a blank page is a refund)
Then: lock the book, create/reuse the order, write audit events.

`paid` and beyond arrive via payment webhooks (M9); every transition goes
through apply_transition, which enforces the state machine and appends an
OrderEvent row.
"""
import re
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import DomainError, ErrorCode
from app.domain.states import (
    BookStatus,
    Effect,
    OrderStatus,
    transition_book,
    transition_order,
)
from app.models.book import Book
from app.models.order import Order, OrderEvent
from app.services.books import get_book_authed
from app.services.placement import _usable_photos
from app.services.preview import PREVIEW_READY
from app.services.pricing import price_minor_for_tier

# No 0/O/1/I — the ref is read over the phone.
REF_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def _now() -> datetime:
    return datetime.now(UTC)


def _new_human_ref() -> str:
    return "UB-" + "".join(secrets.choice(REF_ALPHABET) for _ in range(5))


def normalize_phone(phone: str) -> str:
    return re.sub(r"\D", "", phone)


def record_event(session: AsyncSession, order: Order, from_status: str | None,
                 to_status: str, note: str | None = None) -> None:
    session.add(OrderEvent(order_id=order.id, from_status=from_status,
                           to_status=to_status, note=note, created_at=_now()))


def apply_transition(session: AsyncSession, order: Order, target: OrderStatus,
                     note: str | None = None) -> tuple[Effect, ...]:
    """The only legal way to change order.status. Validates against the state
    machine, appends the audit event, stamps lifecycle timestamps, and returns
    the effects the caller must execute."""
    current = OrderStatus(order.status)
    effects = transition_order(current, target)
    record_event(session, order, current.value, target.value, note)
    order.status = target.value
    now = _now()
    if target is OrderStatus.PAID:
        order.paid_at = now
    elif target is OrderStatus.RENDERED:
        order.rendered_at = now
    elif target is OrderStatus.SHIPPED:
        order.shipped_at = now
    return effects


def _require_fresh_preview(book: Book) -> None:
    if (book.preview_status != PREVIEW_READY
            or book.preview_layout_version != book.layout_version):
        raise DomainError(
            ErrorCode.PREVIEW_STALE,
            "the preview is missing or does not match the current layout — "
            "regenerate it and confirm again",
            {"preview_status": book.preview_status or "none",
             "preview_layout_version": book.preview_layout_version,
             "layout_version": book.layout_version},
        )


def _require_complete_pages(book: Book, usable_photo_ids: set[str]) -> None:
    pages = book.layout.get("pages", [])
    empty = [p["index"] for p in pages if not p.get("placements")]
    broken = [p["index"] for p in pages
              for pl in p.get("placements", [])
              if pl["photo_id"] not in usable_photo_ids]
    if empty or broken:
        raise DomainError(
            ErrorCode.PAGES_INCOMPLETE,
            "every page must hold a photo before checkout — blank printed "
            "pages are a guaranteed refund",
            {"empty_pages": empty, "pages_with_unavailable_photos": broken},
        )


async def checkout(session: AsyncSession, book_id: uuid.UUID, edit_token: str, *,
                   name: str, phone: str, address: str, email: str | None,
                   confirmed_preview: bool) -> Order:
    book = await get_book_authed(session, book_id, edit_token)
    if book.status != BookStatus.DRAFT.value:
        raise DomainError(ErrorCode.BOOK_LOCKED,
                          "this book has already been checked out",
                          {"status": book.status})

    if confirmed_preview is not True:
        raise DomainError(ErrorCode.PREVIEW_NOT_CONFIRMED,
                          "you must confirm the preview — after payment the "
                          "book cannot be edited")
    _require_fresh_preview(book)

    photos = await _usable_photos(session, book_id)
    if len(photos) < book.page_count:
        raise DomainError(
            ErrorCode.PHOTOS_INSUFFICIENT,
            f"you have {len(photos)} photos but the {book.page_count}-page "
            f"book needs {book.page_count}",
            {"have": len(photos), "need": book.page_count},
        )
    _require_complete_pages(book, {str(p.id) for p in photos})

    amount_minor = price_minor_for_tier(book.page_count)
    now = _now()

    existing = (await session.execute(
        select(Order).where(Order.book_id == book_id)
    )).scalar_one_or_none()

    if existing is None:
        order = Order(
            book_id=book_id, human_ref=await _unique_ref(session),
            customer_name=name, customer_phone=phone, customer_address=address,
            customer_email=email, amount_minor=amount_minor,
            status=OrderStatus.DRAFT_ORDER.value,
            preview_confirmed_at=now, created_at=now,
        )
        session.add(order)
        await session.flush()
        record_event(session, order, None, OrderStatus.DRAFT_ORDER.value, "created")
        apply_transition(session, order, OrderStatus.PENDING_PAYMENT,
                         "checkout submitted")
    elif existing.status == OrderStatus.CANCELLED.value:
        # Re-checkout after a cancelled payment: one order row per book,
        # refreshed details, full audit trail (A33).
        existing.customer_name = name
        existing.customer_phone = phone
        existing.customer_address = address
        existing.customer_email = email
        existing.amount_minor = amount_minor
        existing.preview_confirmed_at = now
        apply_transition(session, existing, OrderStatus.PENDING_PAYMENT,
                         "re-checkout after cancellation")
        order = existing
    else:
        raise DomainError(ErrorCode.BOOK_LOCKED,
                          "an active order already exists for this book",
                          {"order_status": existing.status})

    transition_book(BookStatus(book.status), BookStatus.LOCKED)
    book.status = BookStatus.LOCKED.value
    await session.commit()
    await session.refresh(order)
    return order


async def _unique_ref(session: AsyncSession) -> str:
    for _ in range(20):
        ref = _new_human_ref()
        exists = (await session.execute(
            select(Order.id).where(Order.human_ref == ref)
        )).scalar_one_or_none()
        if exists is None:
            return ref
    raise RuntimeError("could not allocate a unique order reference")


async def cancel_order(session: AsyncSession, order_id: uuid.UUID,
                       note: str = "cancelled") -> Order:
    """Provider cancel / timeout: order -> cancelled, book unlocks to draft."""
    order = (await session.execute(
        select(Order).where(Order.id == order_id)
    )).scalar_one()
    apply_transition(session, order, OrderStatus.CANCELLED, note)
    book = (await session.execute(
        select(Book).where(Book.id == order.book_id)
    )).scalar_one()
    transition_book(BookStatus(book.status), BookStatus.DRAFT)
    book.status = BookStatus.DRAFT.value
    await session.commit()
    return order


async def public_status(session: AsyncSession, human_ref: str, phone: str) -> dict:
    """Public lookup by reference + phone. A wrong phone is indistinguishable
    from an unknown reference."""
    order = (await session.execute(
        select(Order).where(Order.human_ref == human_ref.strip().upper())
    )).scalar_one_or_none()
    if order is None or normalize_phone(order.customer_phone) != normalize_phone(phone):
        raise DomainError(ErrorCode.ORDER_NOT_FOUND, "order not found")
    book = (await session.execute(
        select(Book).where(Book.id == order.book_id)
    )).scalar_one()
    payload = {
        "human_ref": order.human_ref,
        "status": order.status,
        "page_count": book.page_count,
        "amount_minor": order.amount_minor,
        "currency": order.currency,
        "created_at": order.created_at,
        "paid_at": order.paid_at,
    }
    # Card-transfer pilot: show where to send the money while the order is
    # unpaid. Nothing secret here — it's the number customers must see.
    from app.config import get_settings

    settings = get_settings()
    if (order.status == OrderStatus.PENDING_PAYMENT.value
            and settings.pay_card_number):
        payload["pay_card"] = {
            "number": settings.pay_card_number,
            "holder": settings.pay_card_holder,
        }
    # DEV ENVIRONMENTS ONLY: hand the print PDFs to the order screen so
    # local testing needs no scripts. In production (ENV=prod) the files
    # reach the operator via Telegram, never the public status page.
    if settings.env == "dev":
        from app import storage
        from app.models.payment import PdfArtifact

        artifacts = (await session.execute(
            select(PdfArtifact).where(PdfArtifact.order_id == order.id)
        )).scalars()
        urls = {a.kind: storage.presign_get(a.storage_key) for a in artifacts}
        if urls:
            payload["artifact_urls"] = urls
    return payload
