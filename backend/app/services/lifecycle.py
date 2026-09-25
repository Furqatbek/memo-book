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
import sqlalchemy as sa
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import storage
from app.config import get_settings
from app.domain.states import BookStatus, transition_book
from app.models.book import Book
from app.models.photo import Photo
from app.domain.events import EventType
from app.services import funnel, outbox, telegram_recovery

log = structlog.get_logger()

REMINDER_FIRST = timedelta(days=3)
REMINDER_SECOND = timedelta(days=14)
REMINDER_LAST = timedelta(days=25)

# (flag, age, what it says). Day 25 is the last one that can still be acted
# on: a draft expires 30 days after its last edit, so a reminder any later
# would arrive after the photographs were gone. The urgency climbs because
# the deadline is real, not because louder is better.
REMINDER_SCHEDULE = (
    ("reminder_3d_sent", REMINDER_FIRST, "waiting"),
    ("reminder_14d_sent", REMINDER_SECOND, "still_saved"),
    ("reminder_25d_sent", REMINDER_LAST, "expiring"),
)
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


async def _first_thumb(session: AsyncSession, book_id: uuid.UUID) -> str | None:
    """The key of one of this book's photo thumbnails, or None if it has no
    photographs at all — which is also the "is this worth reminding about?"
    test, so the two questions are answered by one query."""
    return (await session.execute(
        select(Photo.thumb_key)
        .where(Photo.book_id == book_id, Photo.thumb_key.is_not(None))
        .order_by(Photo.uploaded_at.asc())
        .limit(1)
    )).scalar_one_or_none()


def _days_left(book: Book, now: datetime) -> int:
    """Read off the book's own expiry rather than counted from the reminder
    day, because every edit pushes `expires_at` out again — a book edited
    since the day-3 reminder has more than 27 days left, and telling it
    otherwise is the kind of small lie a customer can check."""
    expires = book.expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return max(0, (expires - now).days) if expires else 0


def _reminder_body(kind: str, days_left: int) -> str:
    if kind == "waiting":
        return (f"Your book is waiting — {days_left} "
                f"{'day' if days_left == 1 else 'days'} left to finish it.")
    if kind == "still_saved":
        return "Still saved. Want to finish it?"
    return (f"Your book expires in {days_left} "
            f"{'day' if days_left == 1 else 'days'} — after that the "
            f"photographs are deleted.")


def _reminder_text(url: str, kind: str = "waiting", days_left: int = 0,
                   seasonal: str = "") -> str:
    """Short, because it arrives in a chat rather than an inbox.

    The seasonal note is APPENDED rather than woven in, so that turning it
    off at the end of a campaign cannot leave half a sentence behind.

    `seasonal` is passed in rather than read here so that the COMPUTED
    campaign line can take precedence over the hand-written one (CR-003-7).
    A hand-written note cannot count down, and on the 26th it will still be
    saying "order by 25 November".
    """
    parts = [_reminder_body(kind, days_left)]
    note = (seasonal or get_settings().reminder_seasonal_note or "").strip()
    if note:
        parts.append(note)
    if url:
        parts.append(url)
    return "\n\n".join(parts)


def _reminder_url(book_id: uuid.UUID, day: int) -> str:
    """The same link, marked with which reminder it came from, so a click
    can be attributed to the day-3 or the day-14 message (Change 3)."""
    return _edit_url(book_id) + telegram_recovery.reminder_query(day)


async def queue_reminders(session: AsyncSession,
                          now: datetime | None = None) -> int:
    from app.services import campaign

    now = now or datetime.now(UTC)
    queued = 0
    # Computed once for the whole pass: every reminder sent tonight is
    # sent on the same day, so the countdown is the same for all of them
    # (CR-003-7). An empty string falls back to the hand-written note.
    seasonal = await campaign.seasonal_note(session, now)

    for flag, delta, kind in REMINDER_SCHEDULE:
        # Either channel will do. Telegram is preferred where we have it
        # (Change 2): in this market a message there gets read and an email
        # may not, and the whole reason to offer it is that a reminder
        # nobody sees is a reminder that was not sent.
        books = (await session.execute(
            select(Book).where(
                Book.status == BookStatus.DRAFT.value,
                sa.or_(Book.email.is_not(None),
                       Book.telegram_chat_id.is_not(None)),
                getattr(Book, flag).is_(False),
                Book.updated_at <= now - delta,
            )
        )).scalars().all()
        for book in books:
            # An empty draft gets nothing. There is no book to come back
            # to, and a reminder about one is the definition of spam — and
            # the fastest way to have this bot reported.
            thumb = await _first_thumb(session, book.id)
            if thumb is None:
                continue
            # Absolute where we can build one. Telegram gets nothing rather
            # than a relative path, which is not a link in a chat window;
            # email keeps the relative fallback, which at least names the
            # book, and becomes clickable the moment PUBLIC_BASE_URL is set.
            absolute = telegram_recovery.editor_url(book.id, delta.days)
            days_left = _days_left(book, now)
            if book.telegram_chat_id is not None:
                channel = "telegram"
                outbox.enqueue(session, outbox.TOPIC_BOOK_REMINDER_TG, {
                    "book_id": str(book.id),
                    "chat_id": book.telegram_chat_id,
                    "days_since_edit": delta.days,
                    "text": _reminder_text(absolute, kind, days_left,
                                           seasonal),
                    # Their own photograph, presigned AT DELIVERY so a
                    # message that waited out an outage still opens.
                    "photo_key": thumb,
                })
            else:
                channel = "email"
                outbox.enqueue(session, outbox.TOPIC_BOOK_REMINDER, {
                    "book_id": str(book.id),
                    "email": book.email,
                    "days_since_edit": delta.days,
                    "days_left": days_left,
                    "text": _reminder_text(
                        absolute or _reminder_url(book.id, delta.days),
                        kind, days_left, seasonal),
                    "photo_key": thumb,
                    "edit_url": absolute or _reminder_url(book.id, delta.days),
                })
            setattr(book, flag, True)  # flag + message commit atomically (R7)
            # Repeatable by design: day 3 and day 14 are two sends, and the
            # funnel wants both. The day is in the properties so a reminder
            # that works can be told from one that does not.
            await funnel.emit_for_book(session, EventType.REMINDER_SENT, book.id,
                                       properties={"channel": channel,
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
    # One review request, seven days after delivery, never a second
    # (CR-003-9). After the reminders, because it is the least urgent
    # thing here and a failure in it must not cost anybody a reminder.
    from app.services.reviews import run_requests

    review_requests = await run_requests(session, now=now)
    delivered = await outbox.deliver_pending(session)
    return {"expired": expired, "reminders_queued": reminders,
            "abandoned": abandoned, "review_requests": review_requests,
            "stalled_renders_reaped": stalled, "outbox_delivered": delivered}
