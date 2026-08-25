"""Book service: creation, retrieval, layout mutation.

All layout mutations enforce, in order:
1. edit-token auth (constant-time; wrong token is indistinguishable from
   a missing book)
2. 423 when the book is not mutable (locked/ordered/expired)
3. optimistic concurrency via the If-Match layout version (409 + current
   layout on mismatch)
Every successful mutation extends expires_at to now + 30 days (R6).
"""
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import DomainError, ErrorCode
from app.domain.states import BookStatus, layout_mutable
from app.domain.tiers import validate_tier
from app.models.book import Book
from app.schemas.layout import LayoutDoc, empty_layout, reflow_layout

DRAFT_RETENTION = timedelta(days=30)
EDIT_TOKEN_BYTES = 32


def _now() -> datetime:
    return datetime.now(UTC)


def _not_found() -> DomainError:
    return DomainError(ErrorCode.NOT_FOUND, "book not found")


async def create_book(session: AsyncSession, page_count: int,
                      book_type: str | None = None) -> Book:
    validate_tier(page_count)
    now = _now()
    book = Book(
        edit_token=secrets.token_urlsafe(EDIT_TOKEN_BYTES),
        page_count=page_count,
        book_type=book_type,
        status=BookStatus.DRAFT.value,
        layout=empty_layout(page_count),
        layout_version=1,
        created_at=now,
        updated_at=now,
        expires_at=now + DRAFT_RETENTION,
    )
    session.add(book)
    await session.commit()
    await session.refresh(book)
    return book


async def get_book_authed(session: AsyncSession, book_id: uuid.UUID, edit_token: str) -> Book:
    result = await session.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    # Constant-time comparison; a wrong token looks exactly like a missing book.
    if book is None or not hmac.compare_digest(book.edit_token, edit_token or ""):
        raise _not_found()
    # An expired draft is not a book any more: R6 deleted its photos from
    # storage half an hour after this status was set. Serving it would hand
    # the customer an editor full of broken images and refuse every change
    # with "locked", which is what a checked-out book says — so they would
    # think they had bought it. Say what actually happened (A78).
    if book.status == BookStatus.EXPIRED.value:
        raise _expired(book)
    return book


def _expired(book: Book) -> DomainError:
    return DomainError(
        ErrorCode.BOOK_EXPIRED,
        "this book expired and its photos have been deleted — "
        "start a new one",
        {"status": book.status,
         "expired_at": book.expires_at.isoformat() if book.expires_at else None},
    )


def _require_mutable(book: Book) -> None:
    if book.status == BookStatus.EXPIRED.value:
        raise _expired(book)
    if not layout_mutable(BookStatus(book.status)):
        raise DomainError(ErrorCode.BOOK_LOCKED,
                          "book is locked and can no longer be edited",
                          {"status": book.status})


def _require_version(book: Book, if_match: int | None) -> None:
    if if_match is None:
        raise DomainError(ErrorCode.VERSION_REQUIRED,
                          "If-Match header with the current layout version is required")
    if if_match != book.layout_version:
        raise DomainError(ErrorCode.VERSION_CONFLICT,
                          "layout was modified by another session",
                          {"current_version": book.layout_version,
                           "layout": book.layout})


def _touch(book: Book) -> None:
    now = _now()
    book.updated_at = now
    book.expires_at = now + DRAFT_RETENTION  # R6: every mutation extends retention


async def patch_layout(session: AsyncSession, book_id: uuid.UUID, edit_token: str,
                       if_match: int | None, layout: LayoutDoc) -> Book:
    book = await get_book_authed(session, book_id, edit_token)
    _require_mutable(book)
    _require_version(book, if_match)

    if len(layout.pages) != book.page_count:
        raise DomainError(
            ErrorCode.VALIDATION_ERROR,
            f"layout must contain exactly {book.page_count} pages",
            {"have": len(layout.pages), "need": book.page_count},
        )

    book.layout = layout.model_dump()
    book.layout_version += 1
    _touch(book)
    await session.commit()
    await session.refresh(book)
    return book


async def change_page_count(session: AsyncSession, book_id: uuid.UUID, edit_token: str,
                            if_match: int | None, page_count: int) -> tuple[Book, list[str]]:
    validate_tier(page_count)
    book = await get_book_authed(session, book_id, edit_token)
    _require_mutable(book)
    _require_version(book, if_match)

    warnings: list[str] = []
    if page_count != book.page_count:
        book.layout, warnings = reflow_layout(book.layout, page_count)
        book.page_count = page_count
        book.layout_version += 1
        _touch(book)
        await session.commit()
        await session.refresh(book)
    return book, warnings


async def set_email(session: AsyncSession, book_id: uuid.UUID, edit_token: str,
                    email: str) -> Book:
    book = await get_book_authed(session, book_id, edit_token)
    _require_mutable(book)
    book.email = email
    book.updated_at = _now()  # email is not a layout mutation; retention unchanged
    await session.commit()
    await session.refresh(book)
    return book
