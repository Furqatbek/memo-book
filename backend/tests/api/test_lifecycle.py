"""Milestone 12: draft expiry with storage GC (R6) and reminders (R7)."""
import uuid
from datetime import UTC, datetime, timedelta

import anyio
from sqlalchemy import select

from app import storage
from app.models.book import Book
from app.models.outbox import OutboxMessage
from app.models.photo import Photo
from app.services import email as email_svc
from app.services.lifecycle import expire_drafts, queue_reminders, run_nightly
from tests.api.test_books import make_book
from tests.render.helpers import seed_rendered_book

NOW = datetime(2026, 9, 1, 3, 0, tzinfo=UTC)


async def age_book(db, book_id: str, *, expires_delta_days: int,
                   updated_delta_days: int = 0, email: str | None = None,
                   status: str | None = None) -> Book:
    book = (await db.execute(
        select(Book).where(Book.id == uuid.UUID(book_id)))).scalar_one()
    book.expires_at = NOW + timedelta(days=expires_delta_days)
    book.updated_at = NOW - timedelta(days=updated_delta_days)
    if email:
        book.email = email
    if status:
        book.status = status
    await db.commit()
    return book


async def photo_keys(db, book_id: str) -> list[str]:
    photos = (await db.execute(
        select(Photo).where(Photo.book_id == uuid.UUID(book_id)))).scalars().all()
    return [p.original_key for p in photos]


class TestExpiry:
    async def test_old_draft_expired_and_objects_deleted(self, client, db):
        book_id = await seed_rendered_book(db, client, 16)
        await age_book(db, book_id, expires_delta_days=-1)
        keys = await photo_keys(db, book_id)
        assert await anyio.to_thread.run_sync(storage.object_exists, keys[0])

        expired = await expire_drafts(db, now=NOW)
        assert expired == 1
        book = (await db.execute(
            select(Book).where(Book.id == uuid.UUID(book_id)))).scalar_one()
        await db.refresh(book)
        assert book.status == "expired"
        for key in keys:
            assert not await anyio.to_thread.run_sync(storage.object_exists, key)

    async def test_fresh_draft_untouched(self, client, db):
        book_id = await seed_rendered_book(db, client, 16)
        await age_book(db, book_id, expires_delta_days=+29)
        assert await expire_drafts(db, now=NOW) == 0
        book = (await db.execute(
            select(Book).where(Book.id == uuid.UUID(book_id)))).scalar_one()
        assert book.status == "draft"

    async def test_ordered_book_never_expired_photos_never_deleted(self, client, db):
        """The dangerous case (spec 9.2): an ordered book far past its
        expires_at keeps its status AND its photos."""
        book_id = await seed_rendered_book(db, client, 16)
        await age_book(db, book_id, expires_delta_days=-40, status="ordered")
        keys = await photo_keys(db, book_id)

        assert await expire_drafts(db, now=NOW) == 0
        book = (await db.execute(
            select(Book).where(Book.id == uuid.UUID(book_id)))).scalar_one()
        assert book.status == "ordered"
        for key in keys:
            assert await anyio.to_thread.run_sync(storage.object_exists, key)

    async def test_locked_book_never_expired(self, client, db):
        book_id = await seed_rendered_book(db, client, 16)
        await age_book(db, book_id, expires_delta_days=-5, status="locked")
        assert await expire_drafts(db, now=NOW) == 0

    async def test_expiry_idempotent_when_run_twice(self, client, db):
        book_id = await seed_rendered_book(db, client, 16)
        await age_book(db, book_id, expires_delta_days=-1)
        assert await expire_drafts(db, now=NOW) == 1
        assert await expire_drafts(db, now=NOW) == 0  # second run: nothing


class TestReminders:
    async def test_day3_reminder_queued_once(self, client, db):
        book = await make_book(client, 16)
        await age_book(db, book["book_id"], expires_delta_days=25,
                       updated_delta_days=4, email="traveller@example.com")

        assert await queue_reminders(db, now=NOW) == 1
        row = (await db.execute(select(Book).where(
            Book.id == uuid.UUID(book["book_id"])))).scalar_one()
        await db.refresh(row)
        assert row.reminder_3d_sent is True
        assert row.reminder_14d_sent is False

        [message] = (await db.execute(select(OutboxMessage))).scalars().all()
        assert message.topic == "book.reminder"
        assert message.payload["email"] == "traveller@example.com"
        assert message.payload["days_since_edit"] == 3

        # Idempotent: the flag stops a duplicate.
        assert await queue_reminders(db, now=NOW) == 0

    async def test_day14_reminder_follows(self, client, db):
        book = await make_book(client, 16)
        await age_book(db, book["book_id"], expires_delta_days=10,
                       updated_delta_days=15, email="traveller@example.com")
        # Both windows have passed: both reminders queue, once each.
        assert await queue_reminders(db, now=NOW) == 2
        assert await queue_reminders(db, now=NOW) == 0

    async def test_no_email_no_reminder(self, client, db):
        book = await make_book(client, 16)
        await age_book(db, book["book_id"], expires_delta_days=20,
                       updated_delta_days=10)
        assert await queue_reminders(db, now=NOW) == 0

    async def test_locked_book_gets_no_reminder(self, client, db):
        book = await make_book(client, 16)
        await age_book(db, book["book_id"], expires_delta_days=20,
                       updated_delta_days=10, email="t@example.com",
                       status="locked")
        assert await queue_reminders(db, now=NOW) == 0

    async def test_reminder_delivery_uses_email_seam(self, client, db, monkeypatch):
        sent: list[tuple[str, str, str]] = []
        monkeypatch.setattr(email_svc, "send_email",
                            lambda to, subject, text: sent.append((to, subject, text)))
        book = await make_book(client, 16)
        await age_book(db, book["book_id"], expires_delta_days=25,
                       updated_delta_days=4, email="traveller@example.com")

        result = await run_nightly(db, now=NOW)
        assert result["reminders_queued"] == 1
        assert result["outbox_delivered"] == 1
        [(to, _subject, text)] = sent
        assert to == "traveller@example.com"
        assert "30 days" in text
        assert f"/editor/{book['book_id']}" in text

    async def test_unconfigured_email_transport_retries(self, client, db):
        book = await make_book(client, 16)
        await age_book(db, book["book_id"], expires_delta_days=25,
                       updated_delta_days=4, email="t@example.com")
        result = await run_nightly(db, now=NOW)
        assert result["reminders_queued"] == 1
        assert result["outbox_delivered"] == 0  # transport raises -> retry later
        [message] = (await db.execute(select(OutboxMessage))).scalars().all()
        await db.refresh(message)
        assert message.status == "pending"
        assert "not configured" in message.last_error
