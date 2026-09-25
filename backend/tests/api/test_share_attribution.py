"""The share loop, end to end — CR-003-1.

The CR asks for exactly one journey to be proved:

    owner creates a share link -> a third party views it -> clicks the CTA
    -> creates a book, attributed to the share.

It is worth proving as one test rather than four, because the thing that
breaks is never a step; it is the join between them. Each half works on
its own and the attribution still ends up as `t.me`, and then the report
says shares produce nothing and the feature gets dropped.

Everything below runs through the real cookie middleware, which is where
the join actually lives.
"""
import json
import uuid
from http.cookies import SimpleCookie

import httpx
import pytest
from sqlalchemy import select

from app.api.share import SHARE_ATTRIBUTION
from app.api.tracking import ATTR_COOKIE
from app.domain.events import EventType
from app.models.book import Book
from app.models.funnel_event import FunnelEvent
from tests.render.helpers import seed_rendered_book


@pytest.fixture
async def visitor(sessionmaker, s3, monkeypatch):
    """A second browser: its own cookie jar, nothing shared with the owner.

    The default `client` fixture is the owner's browser. Attribution is a
    per-visitor fact, so a test that used one jar for both would prove
    nothing at all.
    """
    from app.config import get_settings
    from app.db.session import get_session
    from app.main import create_app

    monkeypatch.setenv("TASK_EAGER", "true")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("PRICES_CONFIRMED", "true")
    get_settings.cache_clear()
    app = create_app()

    async def _override_session():
        async with sessionmaker() as session:
            yield session

    app.dependency_overrides[get_session] = _override_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport,
                                 base_url="http://test") as c:
        yield c
    get_settings.cache_clear()


async def owner_shares(client, db, pages: int = 16) -> str:
    book_id = await seed_rendered_book(db, client, pages)
    row = (await db.execute(
        select(Book).where(Book.id == uuid.UUID(book_id)))).scalar_one()
    resp = await client.post(f"/api/v1/books/{book_id}/share",
                             headers={"X-Edit-Token": row.edit_token})
    assert resp.status_code == 200, resp.text
    return resp.json()["share_token"]


def stored_attribution(browser) -> dict:
    """The attribution cookie as the SERVER will read it back.

    Starlette quotes a cookie value containing commas and quotes, and httpx
    hands the raw quoted string back. Reading it without unquoting tests a
    string the server never sees.
    """
    jar = SimpleCookie()
    jar.load(f"{ATTR_COOKIE}={browser.cookies[ATTR_COOKIE]}")
    return json.loads(jar[ATTR_COOKIE].value)


async def events_for(db, book_id) -> list[FunnelEvent]:
    return list((await db.execute(
        select(FunnelEvent).where(FunnelEvent.book_id == book_id)
        .order_by(FunnelEvent.occurred_at))).scalars())


class TestTheWholeLoop:
    async def test_a_book_made_from_a_share_is_attributed_to_the_share(
            self, client, visitor, db):
        token = await owner_shares(client, db)

        # A stranger opens the link from a group chat. Telegram either
        # strips the referrer or sends its own host; neither is the truth.
        page = await visitor.get(f"/s/{token}",
                                 headers={"referer": "https://t.me/"})
        assert page.status_code == 200
        stored = stored_attribution(visitor)
        assert stored == SHARE_ATTRIBUTION, (
            "a shared book's viewer was filed under the referring host")

        # They look at the pages, then press the only button on the page.
        assert (await visitor.get(f"/api/v1/shared/{token}")).status_code == 200
        clicked = await visitor.post("/api/v1/events",
                                     json={"type": "share_cta_clicked"})
        assert clicked.status_code == 202

        # And start a book of their own.
        made = await visitor.post("/api/v1/books", json={"page_count": 16})
        assert made.status_code == 201
        new_id = uuid.UUID(made.json()["book_id"])

        rows = await events_for(db, new_id)
        started = [e for e in rows
                   if e.event_type == EventType.BOOK_STARTED.value]
        assert started, "the new book recorded no book_started"
        assert started[0].source == "share"
        assert started[0].campaign == "share"

    async def test_the_cta_link_carries_the_same_three_values(
            self, client, db):
        """Belt and braces: a viewer who already had an attribution stored
        keeps it — first landing wins — but for everyone else the link's
        own utm parameters must say the same thing the page stamped, or the
        report shows two sources for one journey."""
        token = await owner_shares(client, db)
        html = (await client.get(f"/s/{token}")).text
        for key, value in SHARE_ATTRIBUTION.items():
            assert f"utm_{key}={value}" in html

    async def test_the_viewers_own_journey_is_counted_once(
            self, client, visitor, db):
        """Opening the link three times is one person, not three. The view
        counter is the owner's number and counts views; the funnel is the
        business's number and counts people."""
        token = await owner_shares(client, db)
        for _ in range(3):
            await visitor.get(f"/api/v1/shared/{token}")
        book = (await db.execute(
            select(Book).where(Book.share_token == token))).scalar_one()
        viewed = [e for e in await events_for(db, book.id)
                  if e.event_type == EventType.SHARE_LINK_VIEWED.value]
        assert len(viewed) == 3       # repeatable: each view is a view
        assert len({e.session_id for e in viewed}) == 1


class TestFirstLandingStillWins:
    async def test_an_earlier_campaign_is_not_overwritten_by_a_share(
            self, client, visitor, db):
        """Somebody who came from the New Year ad a week ago, then looked at
        a friend's shared book, was still acquired by the ad. Recording the
        share here would quietly take credit for money that was already
        spent."""
        token = await owner_shares(client, db)
        # Any path goes through the same middleware; /health is the one
        # that exists without a static site mounted under the tests.
        first = await visitor.get(
            "/health?utm_source=facebook&utm_campaign=newyear")
        assert first.status_code == 200
        await visitor.get(f"/s/{token}")

        stored = stored_attribution(visitor)
        assert stored["source"] == "facebook"
        assert stored["campaign"] == "newyear"

        made = await visitor.post("/api/v1/books", json={"page_count": 16})
        rows = await events_for(db, uuid.UUID(made.json()["book_id"]))
        started = next(e for e in rows
                       if e.event_type == EventType.BOOK_STARTED.value)
        assert started.source == "facebook"

    async def test_the_share_token_never_reaches_the_attribution(
            self, client, visitor, db):
        """It is a secret. A report, a log line and a cookie are all places
        somebody else can end up reading."""
        token = await owner_shares(client, db)
        await visitor.get(f"/s/{token}")
        assert token not in visitor.cookies[ATTR_COOKIE]

        book = (await db.execute(
            select(Book).where(Book.share_token == token))).scalar_one()
        for event in await events_for(db, book.id):
            assert token not in repr(
                (event.source, event.medium, event.campaign, event.properties))
