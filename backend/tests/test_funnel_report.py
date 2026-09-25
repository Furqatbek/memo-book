"""The funnel report — Change 3.

The numbers this returns are the ones a decision about money gets made
from, so the tests are mostly about the counting rule rather than the
plumbing: distinct books and distinct sessions, never rows. Counting rows
would let one person who refreshed six times outweigh six people, and every
rate below them would be wrong in the direction that flatters us.
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.domain.events import EventType
from app.models.funnel_event import FunnelEvent

TOKEN = {"X-Admin-Token": "test-admin-token"}
T0 = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _admin_token(monkeypatch):
    from app.config import get_settings
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def seed(db, event: EventType, *, session_id="s1", book_id=None,
               campaign=None, at=None, source=None) -> None:
    db.add(FunnelEvent(
        id=uuid.uuid4(), book_id=book_id, session_id=session_id,
        event_type=event.value, properties={}, campaign=campaign,
        source=source, occurred_at=at or T0))
    await db.commit()


async def report(client, **params):
    resp = await client.get("/api/v1/internal/funnel", headers=TOKEN,
                            params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestItIsGated:
    async def test_no_token_is_a_404_like_every_admin_route(self, client):
        resp = await client.get("/api/v1/internal/funnel")
        assert resp.status_code == 404

    async def test_a_wrong_token_is_the_same_404(self, client):
        resp = await client.get("/api/v1/internal/funnel",
                                headers={"X-Admin-Token": "wrong"})
        assert resp.status_code == 404


class TestTheCountingRule:
    async def test_one_session_visiting_six_times_counts_once(self, client, db):
        """The whole reason not to count rows."""
        for _ in range(6):
            await seed(db, EventType.SITE_VISIT, session_id="same")
        assert (await report(client))["site_visit"] == 1

    async def test_six_sessions_count_six(self, client, db):
        for i in range(6):
            await seed(db, EventType.SITE_VISIT, session_id=f"s{i}")
        assert (await report(client))["site_visit"] == 6

    async def test_book_steps_count_distinct_books(self, client, db):
        a, b = uuid.uuid4(), uuid.uuid4()
        for book in (a, b):
            await seed(db, EventType.BOOK_STARTED, book_id=book)
        assert (await report(client))["book_started"] == 2

    async def test_the_database_itself_refuses_a_duplicate_milestone(self, db):
        """Not a Python check that could be bypassed by a second writer:
        the unique index means two requests arriving together cannot both
        insert, which is exactly the double-submit instrumentation exists
        to measure."""
        import sqlalchemy.exc

        book = uuid.uuid4()
        await seed(db, EventType.BOOK_STARTED, book_id=book)
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            await seed(db, EventType.BOOK_STARTED, book_id=book,
                       session_id="a-different-session")
        await db.rollback()

    async def test_a_repeatable_event_is_not_refused(self, db):
        """The same index must leave editor_opened alone, or a customer who
        comes back tomorrow stops being counted."""
        book = uuid.uuid4()
        for _ in range(3):
            await seed(db, EventType.EDITOR_OPENED, book_id=book)


class TestTheRates:
    async def test_each_step_is_measured_against_the_one_before(self, client, db):
        for i in range(10):
            await seed(db, EventType.SITE_VISIT, session_id=f"v{i}")
        for i in range(4):
            await seed(db, EventType.BOOK_STARTED, book_id=uuid.uuid4())
        for i in range(1):
            await seed(db, EventType.PAYMENT_SUCCEEDED, book_id=uuid.uuid4())
        body = await report(client)
        rates = body["conversion_rates"]
        assert body["site_visit"] == 10 and body["book_started"] == 4
        assert rates["book_started_of_site_visit"] == 0.4
        assert rates["payment_succeeded_of_site_visit"] == 0.1

    async def test_no_data_is_none_rather_than_zero(self, client, db):
        """"Nobody converted" and "we measured nothing" are different facts,
        and a report that renders them the same invites the wrong decision
        about where the money went."""
        body = await report(client)
        assert body["site_visit"] == 0
        assert body["conversion_rates"]["book_started_of_site_visit"] is None


class TestByCampaign:
    async def test_each_campaign_gets_its_own_funnel(self, client, db):
        await seed(db, EventType.SITE_VISIT, session_id="a", campaign="new-year")
        await seed(db, EventType.SITE_VISIT, session_id="b", campaign="new-year")
        await seed(db, EventType.SITE_VISIT, session_id="c", campaign="family")
        await seed(db, EventType.PAYMENT_SUCCEEDED, book_id=uuid.uuid4(),
                   campaign="new-year")
        body = await report(client)
        assert body["by_campaign"]["new-year"]["counts"]["site_visit"] == 2
        assert body["by_campaign"]["family"]["counts"]["site_visit"] == 1
        assert body["by_campaign"]["new-year"]["counts"]["payment_succeeded"] == 1
        assert body["by_campaign"]["family"]["counts"]["payment_succeeded"] == 0

    async def test_filtering_to_one_campaign_narrows_the_totals(self, client, db):
        await seed(db, EventType.SITE_VISIT, session_id="a", campaign="new-year")
        await seed(db, EventType.SITE_VISIT, session_id="b", campaign="family")
        body = await report(client, campaign="new-year")
        assert body["site_visit"] == 1
        assert set(body["by_campaign"]) == {"new-year"}

    async def test_untagged_traffic_is_in_the_totals_but_has_no_campaign(
            self, client, db):
        await seed(db, EventType.SITE_VISIT, session_id="direct")
        body = await report(client)
        assert body["site_visit"] == 1
        assert body["by_campaign"] == {}


class TestTheWindow:
    async def test_events_outside_the_window_are_excluded(self, client, db):
        await seed(db, EventType.SITE_VISIT, session_id="old",
                   at=T0 - timedelta(days=10))
        await seed(db, EventType.SITE_VISIT, session_id="new", at=T0)
        body = await report(client, **{"from": (T0 - timedelta(days=1)).isoformat()})
        assert body["site_visit"] == 1

    async def test_a_naive_timestamp_is_read_as_utc_rather_than_raising(
            self, client, db):
        """A date typed into a spreadsheet has no timezone on it."""
        await seed(db, EventType.SITE_VISIT, session_id="new", at=T0)
        body = await report(client, **{"from": "2026-05-01T00:00:00"})
        assert body["site_visit"] == 1

    async def test_the_window_is_echoed_back(self, client, db):
        body = await report(client, **{"from": "2026-05-01T00:00:00"})
        assert body["window"]["from"].startswith("2026-05-01")


class TestItSaysHowItCounted:
    async def test_the_payload_names_which_steps_are_client_reported(self, client):
        """Nobody should read the top of this funnel as gospel: an
        ad-blocker eats some of it, and the report says so itself."""
        body = await report(client)
        assert "client-reported" in body["counting"]["site_visit"]
        assert "server-observed" in body["counting"]["everything_else"]
