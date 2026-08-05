"""Lifecycle jobs (spec R6 + R7), run nightly.

R6 — expiry: drafts whose `expires_at` has passed are marked expired and
their storage objects deleted. Books in `locked` or `ordered` status are
NEVER expired — the status filter is the guarantee, and the test for it is
the dangerous case the spec calls out.

R7 — reminders: if an email is present and the book is still a draft, remind
at day 3 and day 14 after the last modification, idempotent via the boolean
flags. Reminders flow through the outbox, inheriting at-least-once delivery
and backoff.
"""
import uuid
from datetime import UTC, datetime, timedelta

import anyio
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import storage
from app.domain.states import BookStatus, transition_book
from app.models.book import Book
from app.models.photo import Photo
from app.services import outbox

log = structlog.get_logger()

REMINDER_FIRST = timedelta(days=3)
REMINDER_SECOND = timedelta(days=14)


async def _storage_keys_for_book(session: AsyncSession, book: Book) -> list[str]:
    photos = (await session.execute(
        select(Photo).where(Photo.book_id == book.id)
    )).scalars().all()
    keys: list[str] = []
    for photo in photos:
        keys += [photo.original_key, photo.display_key, photo.thumb_key]
    keys += [f"books/{book.id}/preview/page-{i}.jpg"
             for i in range(book.page_count)]
    return [k for k in keys if k]


async def expire_drafts(session: AsyncSession,
                        now: datetime | None = None) -> int:
    """Mark expired drafts and delete their storage objects. Idempotent:
    already-expired books never match the draft filter again."""
    now = now or datetime.now(UTC)
    books = (await session.execute(
        select(Book).where(Book.status == BookStatus.DRAFT.value,
                           Book.expires_at <= now)
    )).scalars().all()

    for book in books:
        keys = await _storage_keys_for_book(session, book)
        transition_book(BookStatus(book.status), BookStatus.EXPIRED)
        book.status = BookStatus.EXPIRED.value
        await session.commit()
        # Objects go after the status commit: a crash between the two leaves
        # a re-runnable delete, never a live draft with missing photos.
        await anyio.to_thread.run_sync(storage.delete_keys, keys)
        log.info("lifecycle.expired", book_id=str(book.id),
                 deleted_objects=len(keys))
    return len(books)


def _edit_url(book_id: uuid.UUID) -> str:
    # The editor URL scheme belongs to the frontend; the path is a stable
    # contract the frontend serves.
    return f"/editor/{book_id}"


async def queue_reminders(session: AsyncSession,
                          now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    queued = 0

    for flag, delta in (("reminder_3d_sent", REMINDER_FIRST),
                        ("reminder_14d_sent", REMINDER_SECOND)):
        books = (await session.execute(
            select(Book).where(
                Book.status == BookStatus.DRAFT.value,
                Book.email.is_not(None),
                getattr(Book, flag).is_(False),
                Book.updated_at <= now - delta,
            )
        )).scalars().all()
        for book in books:
            outbox.enqueue(session, outbox.TOPIC_BOOK_REMINDER, {
                "book_id": str(book.id),
                "email": book.email,
                "days_since_edit": delta.days,
                "edit_url": _edit_url(book.id),
            })
            setattr(book, flag, True)  # flag + message commit atomically (R7)
            await session.commit()
            queued += 1
            log.info("lifecycle.reminder_queued", book_id=str(book.id),
                     days=delta.days)
    return queued


async def run_nightly(session: AsyncSession,
                      now: datetime | None = None) -> dict:
    expired = await expire_drafts(session, now=now)
    reminders = await queue_reminders(session, now=now)
    delivered = await outbox.deliver_pending(session)
    return {"expired": expired, "reminders_queued": reminders,
            "outbox_delivered": delivered}
