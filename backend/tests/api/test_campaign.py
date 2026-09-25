"""CR-003-7 and CR-003-8 — the countdown and the places counter.

Two numbers reach a customer from here and both are promises. The
countdown promises a printer's schedule; the places counter promises that
a thing is nearly gone. So most of this file is about the second one,
because the rule it has to satisfy is absolute and is the founder's:

    every scarcity or availability figure shown to a customer is computed
    from real data, or it does not ship.

The tests that matter are therefore the ones asserting what happens with
NO ceiling configured — no number, no banner, no closure, and above all no
invented figure — and the one asserting that the number, when it exists,
counts orders somebody actually paid for.
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models.book import Book
from app.models.order import Order
from app.services import campaign as svc
from tests.api.conftest import ADMIN_TOKEN
from tests.api.test_admin_orders import AUTH, an_order
from tests.api.test_checkout import do_checkout, ready_book

TODAY = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def window(monkeypatch):
    """A New Year campaign: arrive by 31 December, 14 days to make."""
    monkeypatch.setenv("CAMPAIGN_DEADLINE", "2026-12-31")
    monkeypatch.setenv("CAMPAIGN_LABEL", "New Year")
    monkeypatch.setenv("PRODUCTION_DAYS", "14")
    monkeypatch.setenv("MONTHLY_CAPACITY", "0")
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestTheCountdown:
    async def test_it_counts_to_the_order_by_date_not_the_deadline(
            self, db, window):
        """The deadline is when the book must ARRIVE. Counting to it would
        promise a customer seventeen days that the printer needs fourteen
        of."""
        now = await svc.current(db, TODAY)
        assert now.deadline.isoformat() == "2026-12-31"
        assert now.order_by.isoformat() == "2026-12-17"
        assert now.days_left == 46

    async def test_it_disappears_once_the_order_by_date_has_passed(
            self, db, window):
        """A banner counting down to a date in the past is worse than no
        banner: it tells a customer the product is unattended."""
        after = datetime(2026, 12, 18, 9, 0, tzinfo=UTC)
        assert await svc.current(db, after) is None

    async def test_the_last_day_says_so_rather_than_saying_zero_days(
            self, db, window):
        last = datetime(2026, 12, 17, 8, 0, tzinfo=UTC)
        w = await svc.current(db, last)
        assert w.days_left == 0
        assert "last day" in svc.banner_line(w)

    async def test_one_day_is_singular(self, db, window):
        w = await svc.current(db, datetime(2026, 12, 16, 8, 0, tzinfo=UTC))
        assert "within 1 day to" in svc.banner_line(w)

    async def test_no_deadline_means_no_campaign_at_all(self, db, monkeypatch):
        monkeypatch.setenv("CAMPAIGN_DEADLINE", "")
        get_settings.cache_clear()
        try:
            assert await svc.current(db, TODAY) is None
        finally:
            get_settings.cache_clear()

    async def test_an_unparseable_date_switches_it_off_rather_than_guessing(
            self, db, monkeypatch):
        """A guess here is a promise made by accident."""
        monkeypatch.setenv("CAMPAIGN_DEADLINE", "25 December")
        get_settings.cache_clear()
        try:
            assert await svc.current(db, TODAY) is None
        finally:
            get_settings.cache_clear()

    async def test_the_endpoint_answers_null_rather_than_erroring(
            self, client, db):
        body = (await client.get("/api/v1/campaign")).json()
        assert body == {"campaign": None}

    async def test_the_endpoint_carries_the_computed_numbers(
            self, client, db, window):
        body = (await client.get("/api/v1/campaign")).json()["campaign"]
        assert body["label"] == "New Year"
        assert body["order_by"] == "2026-12-17"
        assert isinstance(body["days_left"], int)
        assert body["open"] is True


class TestThePlacesCounterIsRealOrAbsent:
    async def test_with_no_ceiling_there_is_no_number(self, client, db,
                                                      window):
        """The important one. Not zero, not null, not "limited places" —
        the keys are simply not there, so a client cannot render a figure
        nobody computed."""
        body = (await client.get("/api/v1/campaign")).json()["campaign"]
        assert "places_left" not in body
        assert "capacity" not in body
        assert body["sold_out"] is False

    async def test_with_a_ceiling_it_counts_orders_actually_paid_for(
            self, client, db, window, monkeypatch):
        monkeypatch.setenv("MONTHLY_CAPACITY", "3")
        get_settings.cache_clear()

        # One order that reached `paid`, and one that never did.
        ref = await an_order(client, db)
        await client.post(f"/api/v1/admin/orders/{ref}/confirm-payment",
                          headers=AUTH, json={"note": "seen"})
        book_id, headers = await ready_book(client, db)
        unpaid = await do_checkout(client, book_id, headers)
        assert unpaid.status_code == 201

        body = (await client.get("/api/v1/campaign")).json()["campaign"]
        assert body["capacity"] == 3
        assert body["places_left"] == 2, (
            "an unpaid order was counted as a place taken")

    async def test_a_pending_order_is_not_a_place(self, db, window):
        """Counting them would make the remaining figure smaller than the
        truth — the flattering direction, and therefore the one to be most
        careful about."""
        from app.domain.states import OrderStatus

        assert OrderStatus.PENDING_PAYMENT.value not in svc.TAKEN_STATUSES
        assert OrderStatus.DRAFT_ORDER.value not in svc.TAKEN_STATUSES
        assert OrderStatus.CANCELLED.value not in svc.TAKEN_STATUSES
        assert OrderStatus.PAID.value in svc.TAKEN_STATUSES
        assert OrderStatus.PRINTING.value in svc.TAKEN_STATUSES

    async def test_a_finished_book_frees_its_place_again(self, db, window):
        """What the printer quoted is THROUGHPUT — how many they can make
        in a month. A book already shipped is off the press. Leaving it in
        the count would ratchet the counter down for ever until somebody
        reset it by hand, and a scarcity figure that stops describing
        anything is the thing this rule exists to prevent."""
        from app.domain.states import OrderStatus

        assert OrderStatus.SHIPPED.value not in svc.TAKEN_STATUSES
        assert OrderStatus.DELIVERED.value not in svc.TAKEN_STATUSES

    async def test_it_never_goes_below_zero(self, db, window, monkeypatch,
                                            client):
        """The ceiling is lowered AFTER the orders exist, which is what
        happens when the printer revises their number mid-campaign. The
        counter must read zero, not minus one."""
        for _ in range(2):
            ref = await an_order(client, db)
            await client.post(f"/api/v1/admin/orders/{ref}/confirm-payment",
                              headers=AUTH, json={"note": "seen"})
        monkeypatch.setenv("MONTHLY_CAPACITY", "1")
        get_settings.cache_clear()
        w = await svc.current(db)
        assert w.taken == 2
        assert w.places_left == 0
        assert w.sold_out is True


class TestFullMeansClosed:
    """A counter that reaches zero and keeps selling is a lie told slowly."""

    async def test_checkout_is_refused_when_the_places_are_gone(
            self, client, db, window, monkeypatch):
        monkeypatch.setenv("MONTHLY_CAPACITY", "1")
        get_settings.cache_clear()
        ref = await an_order(client, db)
        await client.post(f"/api/v1/admin/orders/{ref}/confirm-payment",
                          headers=AUTH, json={"note": "seen"})

        book_id, headers = await ready_book(client, db)
        refused = await do_checkout(client, book_id, headers)
        assert refused.status_code == 409
        body = refused.json()["error"]
        assert body["code"] == "CAMPAIGN_FULL"
        # And it tells them their work is safe, which is the thing they
        # will actually be worried about.
        assert "saved" in body["message"]
        assert "charged" in body["message"]

    async def test_with_no_ceiling_nothing_is_ever_refused(
            self, client, db, window):
        book_id, headers = await ready_book(client, db)
        resp = await do_checkout(client, book_id, headers)
        assert resp.status_code == 201

    async def test_an_order_already_placed_keeps_its_place(
            self, client, db, window, monkeypatch):
        """Somebody who paid before the ceiling was reached is not thrown
        out of the queue by somebody else's order."""
        monkeypatch.setenv("MONTHLY_CAPACITY", "1")
        get_settings.cache_clear()
        ref = await an_order(client, db)
        await client.post(f"/api/v1/admin/orders/{ref}/confirm-payment",
                          headers=AUTH, json={"note": "seen"})
        order = (await db.execute(select(Order).where(
            Order.human_ref == ref))).scalar_one()
        assert order.status == "rendered"


class TestTheReminderCarriesTheCountdown:
    async def test_the_computed_line_beats_the_hand_written_note(
            self, db, window, monkeypatch):
        """A hand-written note cannot count down, and on the 26th it will
        still be saying "order by 25 November"."""
        monkeypatch.setenv("REMINDER_SEASONAL_NOTE",
                           "Order by 25 November for New Year.")
        get_settings.cache_clear()
        note = await svc.seasonal_note(db, TODAY)
        assert "25 November" not in note
        assert "New Year" in note

    async def test_outside_the_window_the_hand_written_note_returns(
            self, db, window, monkeypatch):
        monkeypatch.setenv("REMINDER_SEASONAL_NOTE", "A standing note.")
        get_settings.cache_clear()
        after = datetime(2027, 1, 5, 9, 0, tzinfo=UTC)
        assert await svc.seasonal_note(db, after) == "A standing note."

    async def test_with_neither_there_is_no_note(self, db, monkeypatch):
        monkeypatch.setenv("CAMPAIGN_DEADLINE", "")
        monkeypatch.setenv("REMINDER_SEASONAL_NOTE", "")
        get_settings.cache_clear()
        try:
            assert await svc.seasonal_note(db) == ""
        finally:
            get_settings.cache_clear()

    async def test_a_real_reminder_carries_it(self, client, db, window):
        """End to end: the line has to reach the message, not just the
        function that builds it."""
        from app.models.outbox import OutboxMessage
        from app.services import lifecycle

        book = await client.post("/api/v1/books", json={"page_count": 16})
        body = book.json()
        row = (await db.execute(select(Book).where(
            Book.id == uuid.UUID(body["book_id"])))).scalar_one()
        row.email = "her@example.com"
        row.updated_at = datetime.now(UTC) - timedelta(days=4)
        await db.commit()

        # A draft with a photograph in it; an empty one is never reminded.
        from app.models.photo import Photo, PhotoStatus

        db.add(Photo(id=uuid.uuid4(), book_id=row.id,
                     status=PhotoStatus.READY.value,
                     original_key="k", thumb_key="t", mime_original="image/jpeg",
                     bytes_original=10, uploaded_at=datetime.now(UTC)))
        await db.commit()

        assert await lifecycle.queue_reminders(db) >= 1
        texts = [m.payload["text"] for m in (await db.execute(
            select(OutboxMessage))).scalars().all() if "text" in m.payload]
        assert any("New Year" in text for text in texts), texts
