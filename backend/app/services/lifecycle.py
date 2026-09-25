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
from app.domain.events import EventType
from app.services import funnel, outbox

log = structlog.get_logger()

REMINDER_FIRST = timedelta(days=3)
REMINDER_SECOND = timedelta(days=14)
# "Abandoned" is a funnel word, not a lifecycle one: the book is untouched
# and still perfectly editable for the rest of its 30 days. It is recorded
# so the drop-off between starting a book and finishing one can be measured
# against the campaign that paid for the visit (Change 3).
ABANDONED_AFTER = timedelta(hours=72)


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


def _reminder_url(book_id: uuid.UUID, day: int) -> str:
    """The same link, marked with which reminder it came from, so a click
    can be attributed to the day-3 or the day-14 message (Change 3)."""
    return f"{_edit_url(book_id)}?r={day}"


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
                "edit_url": _reminder_url(book.id, delta.days),
            })
            setattr(book, flag, True)  # flag + message commit atomically (R7)
            # Repeatable by design: day 3 and day 14 are two sends, and the
            # funnel wants both. The day is in the properties so a reminder
            # that works can be told from one that does not.
            await funnel.emit_for_book(session, EventType.REMINDER_SENT, book.id,
                                       properties={"channel": "email",
                                                   "day": delta.days})
            await session.commit()
            queued += 1
            log.info("lifecycle.reminder_queued", book_id=str(book.id),
                     days=delta.days)
    return queued


async def mark_abandoned(session: AsyncSession,
                         now: datetime | None = None) -> int:
    """Draft books with no activity for 72 hours.

    Only books that got far enough to be worth counting as a loss: one that
    never had a photo put in it is a bounce, and lumping the two together
    would make the abandonment rate read far worse than it is. Emission is
    once per book, so a book that sits untouched for a fortnight is counted
    once rather than on every nightly run.
    """
    now = now or datetime.now(UTC)
    books = (await session.execute(
        select(Book).where(Book.status == BookStatus.DRAFT.value,
                           Book.updated_at <= now - ABANDONED_AFTER)
    )).scalars().all()
    counted = 0
    for book in books:
        has_photo = (await session.execute(
            select(Photo.id).where(Photo.book_id == book.id).limit(1)
        )).scalar_one_or_none()
        if not has_photo:
            continue
        if await funnel.emit_for_book(session, EventType.BOOK_ABANDONED, book.id):
            counted += 1
        await session.commit()
    return counted


async def run_nightly(session: AsyncSession,
                      now: datetime | None = None) -> dict:
    # The watchdog also runs in the outbox worker, every few minutes, which
    # is where a stalled render is actually caught. It runs here too so a
    # deployment that only schedules this job by cron — no long-running
    # worker — still notices, a day late rather than never (A76).
    from app.services.fulfillment import reap_stalled_renders

    # Before expiry, so a book that crosses both lines on the same night is
    # counted as abandoned rather than vanishing uncounted.
    abandoned = await mark_abandoned(session, now=now)
    expired = await expire_drafts(session, now=now)
    reminders = await queue_reminders(session, now=now)
    stalled = await reap_stalled_renders(session, now=now)
    delivered = await outbox.deliver_pending(session)
    return {"expired": expired, "reminders_queued": reminders,
            "abandoned": abandoned,
            "stalled_renders_reaped": stalled, "outbox_delivered": delivered}
