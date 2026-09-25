"""Funnel instrumentation — Change 3.

Three properties carry this whole feature, and each is a way it could be
worse than useless:

  1. **It never breaks the thing it measures.** Analytics that can fail a
     checkout is worth less than no analytics.
  2. **It does not inflate.** A customer who refreshes has not started a
     second book, and a funnel that says otherwise makes every conversion
     rate below it wrong in the direction that flatters us.
  3. **Attribution survives to the money.** A payment that cannot be joined
     to the campaign that paid for the visit makes cost per acquisition
     uncomputable, which is the entire purpose of the change.
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.domain.events import (
    CLIENT_REPORTABLE,
    ONCE_PER_BOOK,
    REPEATABLE,
    EventType,
)
from app.models.funnel_event import FunnelEvent
from app.services import funnel
from tests.api.test_books import auth, make_book

SID = "test-session-aaaaaaaaaaaa"


async def count_of(db, event: EventType, book_id=None) -> int:
    stmt = select(func.count()).select_from(FunnelEvent).where(
        FunnelEvent.event_type == event.value)
    if book_id:
        stmt = stmt.where(FunnelEvent.book_id == uuid.UUID(str(book_id)))
    return int((await db.execute(stmt)).scalar() or 0)


async def rows_for(db, book_id) -> list[FunnelEvent]:
    return list((await db.execute(
        select(FunnelEvent).where(FunnelEvent.book_id == uuid.UUID(str(book_id)))
    )).scalars())


class TestTheVocabularyIsClosed:
    def test_every_repeatable_event_is_a_real_event(self):
        assert REPEATABLE <= set(EventType)

    def test_once_and_repeatable_partition_the_enum(self):
        assert ONCE_PER_BOOK | REPEATABLE == set(EventType)
        assert not (ONCE_PER_BOOK & REPEATABLE)

    def test_the_client_may_only_report_what_the_server_cannot_see(self):
        """If this set ever grows a money event, a browser could forge it."""
        assert EventType.PAYMENT_SUCCEEDED not in CLIENT_REPORTABLE
        assert EventType.CHECKOUT_SUBMITTED not in CLIENT_REPORTABLE
        assert EventType.BOOK_STARTED not in CLIENT_REPORTABLE

    def test_the_migration_predicate_matches_the_enum(self):
        """The partial unique index lives in two places — the model builds
        its predicate from the enum, the migration spells it out so the
        schema reads on its own. If they drift, the index stops guarding
        the events it was written for and nothing else notices."""
        import importlib.util
        import pathlib

        # The LATEST migration to touch the predicate. 0012 created it;
        # 0017 widened it when share views arrived.
        path = (pathlib.Path(__file__).resolve().parents[1]
                / "alembic" / "versions" / "0017_share_events_repeatable.py")
        # Loaded by path: a module name starting with a digit cannot be
        # imported the ordinary way.
        spec = importlib.util.spec_from_file_location("migpred", path)
        mig = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mig)
        assert set(mig.NEW) == {e.value for e in REPEATABLE}


class TestItNeverBreaksTheRequest:
    async def test_a_duplicate_is_refused_without_raising(self, db):
        book_id = None
        first = await funnel.emit(db, EventType.SITE_VISIT, session_id=SID,
                                  book_id=book_id)
        assert first is True

    async def test_a_second_once_only_event_returns_false(self, client, db):
        book = await make_book(client, 16)
        bid = uuid.UUID(book["book_id"])
        assert await funnel.emit(db, EventType.PREVIEW_VIEWED,
                                 session_id=SID, book_id=bid) is True
        # The index refuses it; the caller is told, and nothing raises.
        assert await funnel.emit(db, EventType.PREVIEW_VIEWED,
                                 session_id=SID, book_id=bid) is False
        assert await count_of(db, EventType.PREVIEW_VIEWED, bid) == 1

    async def test_the_caller_can_still_commit_after_a_refused_duplicate(
            self, client, db):
        """The property that matters most. A savepoint means the failed
        insert unwinds on its own; writing into the caller's transaction
        directly would poison it, and the customer's order would fail
        because we tried to count it."""
        book = await make_book(client, 16)
        bid = uuid.UUID(book["book_id"])
        await funnel.emit(db, EventType.DESIGN_COMPLETED, session_id=SID, book_id=bid)
        await funnel.emit(db, EventType.DESIGN_COMPLETED, session_id=SID, book_id=bid)
        await db.commit()          # would raise if the transaction were poisoned
        assert await count_of(db, EventType.DESIGN_COMPLETED, bid) == 1

    async def test_a_repeatable_event_may_repeat(self, client, db):
        book = await make_book(client, 16)
        bid = uuid.UUID(book["book_id"])
        for _ in range(3):
            assert await funnel.emit(db, EventType.EDITOR_OPENED,
                                     session_id=SID, book_id=bid) is True
        assert await count_of(db, EventType.EDITOR_OPENED, bid) == 3

    async def test_an_event_without_a_session_is_dropped_not_raised(self, db):
        assert await funnel.emit(db, EventType.SITE_VISIT, session_id=None) is False


class TestTheServerEmitsWhereItKnows:
    async def test_creating_a_book_records_book_started(self, client, db):
        book = await make_book(client, 16)
        assert await count_of(db, EventType.BOOK_STARTED,
                              uuid.UUID(book["book_id"])) == 1

    async def test_creating_two_books_records_two(self, client, db):
        await make_book(client, 16)
        await make_book(client, 16)
        assert await count_of(db, EventType.BOOK_STARTED) == 2

    async def test_requesting_a_preview_records_preview_viewed(self, client, db):
        book = await make_book(client, 16)
        await client.post(f"/api/v1/books/{book['book_id']}/preview",
                          headers=auth(book))
        assert await count_of(db, EventType.PREVIEW_VIEWED,
                              uuid.UUID(book["book_id"])) == 1

    async def test_an_email_records_contact_captured_with_its_channel(
            self, client, db):
        book = await make_book(client, 16)
        await client.patch(f"/api/v1/books/{book['book_id']}/email",
                           json={"email": "a@example.com"}, headers=auth(book))
        rows = [r for r in await rows_for(db, book["book_id"])
                if r.event_type == EventType.CONTACT_CAPTURED.value]
        assert len(rows) == 1
        assert rows[0].properties == {"channel": "email"}


class TestTheClientDoorIsNarrow:
    async def test_a_browser_may_report_a_site_visit(self, client, db):
        resp = await client.post("/api/v1/events", json={"type": "site_visit"})
        assert resp.status_code == 202

    @pytest.mark.parametrize("forged", [
        "payment_succeeded", "checkout_submitted", "book_started",
        "design_completed", "first_photo_uploaded",
    ])
    async def test_a_browser_may_not_forge_a_server_event(self, client, db, forged):
        """The door exists for three events the server cannot see. If it
        accepted these, a page could invent its own conversions."""
        resp = await client.post("/api/v1/events", json={"type": forged})
        assert resp.status_code == 422
        assert await count_of(db, EventType(forged)) == 0

    async def test_an_unknown_event_is_refused(self, client):
        resp = await client.post("/api/v1/events", json={"type": "free_money"})
        assert resp.status_code == 422

    async def test_checkout_opened_needs_the_books_edit_token(self, client, db):
        book = await make_book(client, 16)
        bad = await client.post("/api/v1/events", json={
            "type": "checkout_opened", "book_id": book["book_id"]},
            headers={"X-Edit-Token": "not-the-token"})
        assert bad.status_code == 404
        assert await count_of(db, EventType.CHECKOUT_OPENED) == 0

        ok = await client.post("/api/v1/events", json={
            "type": "checkout_opened", "book_id": book["book_id"]},
            headers=auth(book))
        assert ok.status_code == 202
        assert await count_of(db, EventType.CHECKOUT_OPENED) == 1

    async def test_replaying_checkout_opened_cannot_inflate_it(self, client, db):
        book = await make_book(client, 16)
        for _ in range(5):
            await client.post("/api/v1/events", json={
                "type": "checkout_opened", "book_id": book["book_id"]},
                headers=auth(book))
        assert await count_of(db, EventType.CHECKOUT_OPENED) == 1


class TestAttributionReachesTheMoney:
    async def test_a_books_later_events_inherit_its_first_attribution(
            self, client, db):
        """The point of the whole change. A webhook carries no cookie, so
        the payment takes its campaign off the book's first event — without
        this every sale reads as direct traffic and cost per acquisition
        cannot be computed at all."""
        book = await make_book(client, 16)
        bid = uuid.UUID(book["book_id"])
        started = (await rows_for(db, bid))[0]
        started.source, started.medium, started.campaign = (
            "instagram", "cpc", "new-year-2026")
        await db.commit()

        sid, attribution = await funnel.book_tracking(db, bid)
        assert attribution["campaign"] == "new-year-2026"

        await funnel.emit_for_book(db, EventType.PAYMENT_SUCCEEDED, bid)
        await db.commit()
        paid = [r for r in await rows_for(db, bid)
                if r.event_type == EventType.PAYMENT_SUCCEEDED.value][0]
        assert paid.campaign == "new-year-2026"
        assert paid.source == "instagram"
        assert paid.session_id == sid

    async def test_a_book_with_no_events_attributes_to_nothing(self, db):
        sid, attribution = await funnel.book_tracking(db, uuid.uuid4())
        assert sid is None and attribution == {}


class TestRecoveryAttribution:
    """Change 4 asks that reminder links attribute recovered orders; Change
    3 says first touch wins. Both are satisfied, and the reason matters.

    If a reminder click overwrote the session's campaign, a customer
    originally won by a New Year advert and merely RESCUED by a reminder
    would be recorded as having come from the reminder — stripping the
    campaign that actually paid for them of the sale, and making its cost
    per acquisition look worse than it is. So the acquisition stays with
    first touch and the rescue is recorded on its own event.
    """

    async def test_a_reminder_click_is_stamped_by_the_server(self, client, db):
        book = await make_book(client, 16)
        resp = await client.post("/api/v1/events", json={
            "type": "reminder_clicked", "day": 3})
        assert resp.status_code == 202
        row = [r for r in (await db.execute(
            select(FunnelEvent).where(
                FunnelEvent.event_type == EventType.REMINDER_CLICKED.value))
        ).scalars()][0]
        assert row.source == "reminder"
        assert row.campaign == "draft_recovery"
        assert row.properties == {"day": 3}

    async def test_it_does_not_need_the_client_to_say_so(self, client, db):
        """The page is never asked what campaign it came from. A click on
        our own reminder IS a draft recovery by definition, so there is
        nothing to trust the caller about and nothing to forge."""
        await client.post("/api/v1/events",
                          json={"type": "reminder_clicked", "day": 25,
                                "book_id": None})
        row = [r for r in (await db.execute(
            select(FunnelEvent).where(
                FunnelEvent.event_type == EventType.REMINDER_CLICKED.value))
        ).scalars()][0]
        assert row.campaign == "draft_recovery"

    async def test_the_books_own_acquisition_is_left_alone(self, client, db):
        """The point. The reminder rescued the sale; the advert won the
        customer, and still owns them."""
        book = await make_book(client, 16)
        bid = uuid.UUID(book["book_id"])
        started = (await rows_for(db, bid))[0]
        started.source, started.campaign = "instagram", "new-year-2026"
        await db.commit()

        await client.post("/api/v1/events",
                          json={"type": "reminder_clicked", "day": 25})
        _sid, attribution = await funnel.book_tracking(db, bid)
        assert attribution["campaign"] == "new-year-2026"

        await funnel.emit_for_book(db, EventType.PAYMENT_SUCCEEDED, bid)
        await db.commit()
        paid = [r for r in await rows_for(db, bid)
                if r.event_type == EventType.PAYMENT_SUCCEEDED.value][0]
        assert paid.campaign == "new-year-2026"
