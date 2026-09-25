"""Milestone 12: draft expiry with storage GC (R6) and reminders (R7)."""
import uuid
from datetime import UTC, datetime, timedelta

import anyio
import pytest
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


async def give_photo(db, book_id: str) -> Photo:
    """A book with nothing in it gets no reminders (Change 4), so every
    reminder test needs one photograph to be about."""
    photo = Photo(id=uuid.uuid4(), book_id=uuid.UUID(book_id), status="ready",
                  original_key=f"books/{book_id}/orig/a",
                  display_key=f"books/{book_id}/disp/a",
                  thumb_key=f"books/{book_id}/thumb/a",
                  mime_original="image/jpeg", bytes_original=1,
                  orig_width=100, orig_height=100, uploaded_at=NOW,
                  sha256=uuid.uuid4().hex)
    db.add(photo)
    await db.commit()
    return photo


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
        await give_photo(db, book["book_id"])
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
        await give_photo(db, book["book_id"])
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
        await give_photo(db, book["book_id"])
        await age_book(db, book["book_id"], expires_delta_days=25,
                       updated_delta_days=4, email="traveller@example.com")

        result = await run_nightly(db, now=NOW)
        assert result["reminders_queued"] == 1
        assert result["outbox_delivered"] == 1
        [(to, _subject, text)] = sent
        assert to == "traveller@example.com"
        # The wording is the day's, and the number is read off the book's
        # own expiry rather than assumed (Change 4).
        assert "waiting" in text
        assert f"/editor/{book['book_id']}" in text

    async def test_unconfigured_email_transport_retries(self, client, db):
        book = await make_book(client, 16)
        await give_photo(db, book["book_id"])
        await age_book(db, book["book_id"], expires_delta_days=25,
                       updated_delta_days=4, email="t@example.com")
        result = await run_nightly(db, now=NOW)
        assert result["reminders_queued"] == 1
        assert result["outbox_delivered"] == 0  # transport raises -> retry later
        [message] = (await db.execute(select(OutboxMessage))).scalars().all()
        await db.refresh(message)
        assert message.status == "pending"
        assert "not configured" in message.last_error


class TestFunnelEventsFromTheNightlyJob:
    """Change 3: the two funnel events nobody's browser can report.

    A payment webhook and a nightly job both run with no cookie in sight,
    so these take their session and campaign off the book's own first
    event — which is what keeps a lost customer attributable to the
    campaign that paid to bring them in.
    """

    async def test_an_untouched_book_with_photos_is_recorded_as_abandoned(
            self, client, db):
        from app.domain.events import EventType
        from app.services.lifecycle import mark_abandoned
        from tests.test_funnel import count_of

        book = await make_book(client, 16)
        db.add(Photo(id=uuid.uuid4(), book_id=uuid.UUID(book["book_id"]),
                     status="ready", original_key="k", mime_original="image/jpeg",
                     bytes_original=1, orig_width=100, orig_height=100,
                     uploaded_at=NOW, sha256=uuid.uuid4().hex))
        await age_book(db, book["book_id"], expires_delta_days=20,
                       updated_delta_days=5)
        assert await mark_abandoned(db, now=NOW) == 1
        assert await count_of(db, EventType.BOOK_ABANDONED,
                              uuid.UUID(book["book_id"])) == 1

    async def test_it_is_counted_once_however_many_nights_pass(self, client, db):
        """A book sitting untouched for a fortnight is one lost customer,
        not fourteen."""
        from app.domain.events import EventType
        from app.services.lifecycle import mark_abandoned
        from tests.test_funnel import count_of

        book = await make_book(client, 16)
        db.add(Photo(id=uuid.uuid4(), book_id=uuid.UUID(book["book_id"]),
                     status="ready", original_key="k", mime_original="image/jpeg",
                     bytes_original=1, orig_width=100, orig_height=100,
                     uploaded_at=NOW, sha256=uuid.uuid4().hex))
        await age_book(db, book["book_id"], expires_delta_days=20,
                       updated_delta_days=5)
        await mark_abandoned(db, now=NOW)
        await mark_abandoned(db, now=NOW + timedelta(days=1))
        assert await count_of(db, EventType.BOOK_ABANDONED,
                              uuid.UUID(book["book_id"])) == 1

    async def test_a_book_with_no_photos_is_a_bounce_not_an_abandonment(
            self, client, db):
        """Lumping the two together would make the abandonment rate read
        far worse than it is, and hide the step that actually leaks."""
        from app.domain.events import EventType
        from app.services.lifecycle import mark_abandoned
        from tests.test_funnel import count_of

        book = await make_book(client, 16)
        await age_book(db, book["book_id"], expires_delta_days=20,
                       updated_delta_days=5)
        assert await mark_abandoned(db, now=NOW) == 0
        assert await count_of(db, EventType.BOOK_ABANDONED) == 0

    async def test_a_book_touched_yesterday_is_not_abandoned(self, client, db):
        from app.services.lifecycle import mark_abandoned

        book = await make_book(client, 16)
        db.add(Photo(id=uuid.uuid4(), book_id=uuid.UUID(book["book_id"]),
                     status="ready", original_key="k", mime_original="image/jpeg",
                     bytes_original=1, orig_width=100, orig_height=100,
                     uploaded_at=NOW, sha256=uuid.uuid4().hex))
        await age_book(db, book["book_id"], expires_delta_days=20,
                       updated_delta_days=1)          # 24h, inside the 72h line
        assert await mark_abandoned(db, now=NOW) == 0

    async def test_a_queued_reminder_records_its_day(self, client, db):
        from app.domain.events import EventType
        from app.models.funnel_event import FunnelEvent

        book = await make_book(client, 16)
        await give_photo(db, book["book_id"])
        await age_book(db, book["book_id"], expires_delta_days=20,
                       updated_delta_days=4, email="a@example.com")
        assert await queue_reminders(db, now=NOW) == 1
        rows = [r for r in (await db.execute(
            select(FunnelEvent).where(
                FunnelEvent.event_type == EventType.REMINDER_SENT.value))
        ).scalars()]
        assert len(rows) == 1
        assert rows[0].properties == {"channel": "email", "day": 3}

    async def test_the_reminder_link_says_which_reminder_it_was(self, client, db):
        """Without the marker a click cannot be told apart from any other
        visit, and reminder_sent has nothing to be measured against."""
        book = await make_book(client, 16)
        await give_photo(db, book["book_id"])
        await age_book(db, book["book_id"], expires_delta_days=20,
                       updated_delta_days=4, email="a@example.com")
        await queue_reminders(db, now=NOW)
        msg = (await db.execute(select(OutboxMessage))).scalars().first()
        # `r=3` tells a day-3 click from a day-25 one; the utm pair marks
        # the whole thing as a recovery rather than new traffic.
        assert "?r=3" in msg.payload["edit_url"]
        assert "utm_campaign=draft_recovery" in msg.payload["edit_url"]


class TestTheThreeReminders:
    """Change 4: day 3, day 14, and a new day 25 that says the deadline.

    A draft expires 30 days after its last edit, so day 25 is the last
    reminder that can still be acted on — and the only one where urgency is
    a fact rather than a tone of voice.
    """

    async def _aged(self, client, db, days: int, *, photo: bool = True,
                    email: str | None = "t@example.com") -> dict:
        book = await make_book(client, 16)
        if photo:
            await give_photo(db, book["book_id"])
        row = (await db.execute(select(Book).where(
            Book.id == uuid.UUID(book["book_id"])))).scalar_one()
        row.updated_at = NOW - timedelta(days=days)
        # Expiry moves with every edit, so a book last touched `days` ago
        # expires 30 days after that — which is what makes "27 days left"
        # true rather than a number we made up.
        row.expires_at = row.updated_at + timedelta(days=30)
        row.email = email
        await db.commit()
        return book

    async def _texts(self, db) -> list[str]:
        return [m.payload["text"] for m in
                (await db.execute(select(OutboxMessage))).scalars()]

    async def test_day_3_says_how_many_days_are_actually_left(self, client, db):
        await self._aged(client, db, 4)
        assert await queue_reminders(db, now=NOW) == 1
        [text] = await self._texts(db)
        assert "waiting" in text
        # 30 - 4 = 26. Read off the book's expiry, not assumed from the
        # reminder day, because an edit since then would move it.
        assert "26 days left" in text, text

    async def test_the_spec_example_holds_for_a_book_three_days_old(
            self, client, db):
        await self._aged(client, db, 3)
        await queue_reminders(db, now=NOW)
        [text] = await self._texts(db)
        assert "27 days left" in text, text

    async def test_day_14_is_the_quiet_one(self, client, db):
        await self._aged(client, db, 15)
        await queue_reminders(db, now=NOW)
        texts = await self._texts(db)
        assert any("Still saved" in x for x in texts), texts

    async def test_day_25_names_the_deadline(self, client, db):
        await self._aged(client, db, 26)
        await queue_reminders(db, now=NOW)
        texts = await self._texts(db)
        last = [x for x in texts if "expires in" in x]
        assert last, texts
        assert "4 days" in last[0], last[0]
        assert "deleted" in last[0]

    async def test_each_day_fires_once_however_often_the_job_runs(
            self, client, db):
        await self._aged(client, db, 26)
        first = await queue_reminders(db, now=NOW)
        assert first == 3                      # all three windows passed
        assert await queue_reminders(db, now=NOW) == 0
        assert await queue_reminders(db, now=NOW + timedelta(days=1)) == 0

    async def test_an_empty_draft_gets_nothing(self, client, db):
        """There is no book to come back to, and a reminder about one is
        the definition of spam."""
        await self._aged(client, db, 26, photo=False)
        assert await queue_reminders(db, now=NOW) == 0

    @pytest.mark.parametrize("status", ["locked", "ordered"])
    async def test_a_locked_or_ordered_book_is_never_reminded(
            self, client, db, status):
        book = await self._aged(client, db, 26)
        row = (await db.execute(select(Book).where(
            Book.id == uuid.UUID(book["book_id"])))).scalar_one()
        row.status = status
        await db.commit()
        assert await queue_reminders(db, now=NOW) == 0

    async def test_every_reminder_link_is_tagged_for_recovery(self, client, db):
        """So an order that came back from a reminder can be told from one
        that arrived new."""
        await self._aged(client, db, 26)
        await queue_reminders(db, now=NOW)
        for text in await self._texts(db):
            assert "utm_source=reminder" in text
            assert "utm_campaign=draft_recovery" in text

    async def test_the_reminder_carries_one_of_their_own_photographs(
            self, client, db):
        await self._aged(client, db, 4)
        await queue_reminders(db, now=NOW)
        [msg] = (await db.execute(select(OutboxMessage))).scalars().all()
        assert msg.payload["photo_key"].endswith("/thumb/a")

    async def test_each_day_records_a_funnel_event_with_its_day(
            self, client, db):
        from app.domain.events import EventType
        from app.models.funnel_event import FunnelEvent

        await self._aged(client, db, 26)
        await queue_reminders(db, now=NOW)
        rows = [r for r in (await db.execute(select(FunnelEvent).where(
            FunnelEvent.event_type == EventType.REMINDER_SENT.value))).scalars()]
        assert sorted(r.properties["day"] for r in rows) == [3, 14, 25]


class TestTheSeasonalNote:
    """A campaign line that switches on with config and no code change."""

    async def _one(self, client, db):
        book = await make_book(client, 16)
        await give_photo(db, book["book_id"])
        row = (await db.execute(select(Book).where(
            Book.id == uuid.UUID(book["book_id"])))).scalar_one()
        row.updated_at = NOW - timedelta(days=4)
        row.expires_at = row.updated_at + timedelta(days=30)
        row.email = "t@example.com"
        await db.commit()
        await queue_reminders(db, now=NOW)
        [msg] = (await db.execute(select(OutboxMessage))).scalars().all()
        return msg.payload["text"]

    async def test_it_is_absent_by_default(self, client, db):
        assert "New Year" not in await self._one(client, db)

    async def test_setting_it_appends_it_to_the_reminder(
            self, client, db, monkeypatch):
        from app.config import get_settings

        monkeypatch.setenv("REMINDER_SEASONAL_NOTE",
                           "Order by 25 November for delivery before New Year.")
        get_settings.cache_clear()
        text = await self._one(client, db)
        assert "Order by 25 November" in text
        # Appended, never woven in: switching it off must not be able to
        # leave half a sentence behind.
        assert text.index("waiting") < text.index("Order by 25 November")
        get_settings.cache_clear()
