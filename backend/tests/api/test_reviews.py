"""CR-003-9 — the post-delivery review request.

Two things are being protected here and they pull in opposite directions.

One is the customer: ONE request, seven days after the book arrived, and
never a second. A follow-up converts almost nobody and costs the goodwill
of somebody who has just spent real money and been pleased about it.

The other is everybody who reads the site's reviews. The rules are the
founder's and they are not negotiable —

    never publish without the permission box;
    never edit a review's wording;
    never invent one.

— and the tests below are the mechanical half of keeping them: that the
permission flag defaults to false and is the only thing that sets it, that
the text is stored exactly as typed, and that nothing in this codebase has
a path that writes a review nobody wrote.
"""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.domain.events import EventType
from app.models.book import Book
from app.models.funnel_event import FunnelEvent
from app.models.order import OrderEvent
from app.models.outbox import OutboxMessage
from app.models.review import ReviewRequest
from app.services import outbox
from app.services import reviews as svc
from tests.api.conftest import ADMIN_TOKEN
from tests.api.test_admin_orders import AUTH, an_order, load


@pytest.fixture
def admin_on(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("ADMIN_TOKEN", ADMIN_TOKEN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def delivered_order(client, db, *, days_ago: int = 8) -> str:
    """An order walked all the way to `delivered`, that long ago."""
    ref = await an_order(client, db)
    await client.post(f"/api/v1/admin/orders/{ref}/confirm-payment",
                      headers=AUTH, json={"note": "seen"})
    for target in ("sent_to_production", "shipped", "delivered"):
        resp = await client.post(f"/api/v1/admin/orders/{ref}/status",
                                 headers=AUTH, json={"target": target})
        assert resp.status_code == 200, (target, resp.text)

    order = await load(db, ref)
    event = (await db.execute(
        select(OrderEvent).where(OrderEvent.order_id == order.id,
                                 OrderEvent.to_status == "delivered")
    )).scalars().first()
    event.created_at = datetime.now(UTC) - timedelta(days=days_ago)
    await db.commit()
    return ref


class TestWhenWeAsk:
    async def test_seven_days_after_delivery(self, client, db, admin_on):
        ref = await delivered_order(client, db, days_ago=8)
        assert [o.human_ref for o in await svc.due(db)] == [ref]

    async def test_and_not_before(self, client, db, admin_on):
        """A book that arrived this morning has not been looked through,
        shown to anybody, or lived with."""
        await delivered_order(client, db, days_ago=2)
        assert await svc.due(db) == []

    async def test_an_undelivered_order_is_never_asked(self, client, db,
                                                       admin_on):
        ref = await an_order(client, db)
        await client.post(f"/api/v1/admin/orders/{ref}/confirm-payment",
                          headers=AUTH, json={"note": "seen"})
        assert await svc.due(db) == []

    async def test_exactly_once_and_never_again(self, client, db, admin_on):
        """The CR says it twice: no follow-up, never a second ask."""
        ref = await delivered_order(client, db)
        order = await load(db, ref)
        assert await svc.ask(db, order) is True
        assert await svc.due(db) == []
        assert await svc.ask(db, order) is False

        rows = (await db.execute(select(ReviewRequest).where(
            ReviewRequest.order_id == order.id))).scalars().all()
        assert len(rows) == 1

    async def test_the_nightly_run_asks_them(self, client, db, admin_on):
        await delivered_order(client, db)
        assert await svc.run_requests(db) == 1
        assert await svc.run_requests(db) == 0

    async def test_a_customer_with_no_channel_is_left_askable(
            self, client, db, admin_on):
        """No row is written, deliberately: if a phone number turns into an
        email later, they get asked properly instead of being permanently
        marked as asked."""
        ref = await delivered_order(client, db)
        order = await load(db, ref)
        order.customer_email = None
        await db.commit()

        assert await svc.ask(db, order) is False
        assert await svc.existing_for_order(db, order.id) is None


class TestTheAsk:
    async def test_it_carries_a_link_and_asks_for_honesty(self, client, db,
                                                          admin_on):
        ref = await delivered_order(client, db)
        order = await load(db, ref)
        await svc.ask(db, order)
        review = await svc.existing_for_order(db, order.id)

        texts = [m.payload["text"] for m in (await db.execute(
            select(OutboxMessage))).scalars().all() if "text" in m.payload]
        ask = next(t for t in texts if review.token in t)
        assert "honest" in ask
        assert "photo" in ask

    async def test_telegram_is_preferred_where_we_have_it(self, client, db,
                                                          admin_on):
        ref = await delivered_order(client, db)
        order = await load(db, ref)
        book = (await db.execute(select(Book).where(
            Book.id == order.book_id))).scalar_one()
        book.telegram_chat_id = 3131
        await db.commit()

        await svc.ask(db, order)
        sent = [m for m in (await db.execute(
            select(OutboxMessage))).scalars().all()
            if m.topic == outbox.TOPIC_BOOK_REMINDER_TG]
        assert sent and sent[-1].payload["chat_id"] == 3131

    async def test_the_event_is_recorded(self, client, db, admin_on):
        ref = await delivered_order(client, db)
        order = await load(db, ref)
        await svc.ask(db, order)
        kinds = (await db.execute(select(FunnelEvent.event_type).where(
            FunnelEvent.book_id == order.book_id))).scalars().all()
        assert EventType.REVIEW_REQUESTED.value in kinds


class TestPermission:
    """The box is the whole thing. Everything else about a review can be
    missing; this is the difference between a review and a private
    message."""

    async def test_it_defaults_to_false(self, client, db, admin_on):
        ref = await delivered_order(client, db)
        order = await load(db, ref)
        await svc.ask(db, order)
        token = (await svc.existing_for_order(db, order.id)).token

        resp = await client.post(f"/api/v1/reviews/{token}",
                                 json={"text": "It is beautiful."})
        assert resp.status_code == 200
        assert resp.json()["may_publish"] is False

        review = await svc.find(db, token)
        await db.refresh(review)
        assert review.may_publish is False

    async def test_a_photo_does_not_imply_it(self, client, db, admin_on,
                                             s3):
        """Somebody sending a picture of their book is pleased, not
        consenting to be quoted on a website."""
        from tests.render.helpers import fixture_photo_bytes

        ref = await delivered_order(client, db)
        order = await load(db, ref)
        await svc.ask(db, order)
        token = (await svc.existing_for_order(db, order.id)).token

        up = await client.post(
            f"/api/v1/reviews/{token}/photo",
            files={"photo": ("book.jpg", fixture_photo_bytes(800, 600, 1),
                             "image/jpeg")})
        assert up.status_code == 201
        await client.post(f"/api/v1/reviews/{token}",
                          json={"text": "Lovely."})
        review = await svc.find(db, token)
        await db.refresh(review)
        assert review.photo_key
        assert review.may_publish is False

    async def test_ticking_it_is_the_only_way_to_grant_it(self, client, db,
                                                          admin_on):
        ref = await delivered_order(client, db)
        order = await load(db, ref)
        await svc.ask(db, order)
        token = (await svc.existing_for_order(db, order.id)).token

        await client.post(f"/api/v1/reviews/{token}",
                          json={"text": "Worth every som.",
                                "display_name": "Aziza K.",
                                "may_publish": True})
        review = await svc.find(db, token)
        await db.refresh(review)
        assert review.may_publish is True

    async def test_withdrawing_it_works(self, client, db, admin_on):
        """Somebody who changes their mind and re-submits must not be left
        published because the first version said yes."""
        ref = await delivered_order(client, db)
        order = await load(db, ref)
        await svc.ask(db, order)
        token = (await svc.existing_for_order(db, order.id)).token

        await client.post(f"/api/v1/reviews/{token}",
                          json={"text": "Good.", "may_publish": True})
        await client.post(f"/api/v1/reviews/{token}",
                          json={"text": "Good.", "may_publish": False})
        review = await svc.find(db, token)
        await db.refresh(review)
        assert review.may_publish is False


class TestTheWordsAreNotTouched:
    async def test_the_text_is_stored_exactly_as_written(self, client, db,
                                                         admin_on):
        """Tidying a customer's sentence is putting words in their mouth,
        and they cannot check what we made them say."""
        written = ("Kitob juda chiroyli chiqdi!!! rahmat sizlarga  "
                   "\nfaqat yetkazib berish biroz kechikdi")
        ref = await delivered_order(client, db)
        order = await load(db, ref)
        await svc.ask(db, order)
        token = (await svc.existing_for_order(db, order.id)).token

        await client.post(f"/api/v1/reviews/{token}",
                          json={"text": written, "may_publish": True})
        review = await svc.find(db, token)
        await db.refresh(review)
        # Only the outer whitespace goes; the words, the punctuation, the
        # double space and the criticism all stay.
        assert review.text == written.strip()
        assert "kechikdi" in review.text

    async def test_the_language_they_wrote_in_is_kept(self, client, db,
                                                      admin_on):
        """So the site can mark it up correctly rather than let a screen
        reader read Uzbek as though it were Russian."""
        ref = await delivered_order(client, db)
        order = await load(db, ref)
        await svc.ask(db, order)
        token = (await svc.existing_for_order(db, order.id)).token
        await client.post(f"/api/v1/reviews/{token}",
                          json={"text": "Zoʻr.", "lang": "uz"})
        review = await svc.find(db, token)
        await db.refresh(review)
        assert review.lang == "uz"

    async def test_nothing_in_the_codebase_publishes_a_review(self):
        """The site's list is hand-curated in assets/reviews.js, and the
        only path into it is a person copying an approved row. If that ever
        stops being true, this test is where it shows up."""
        import pathlib

        repo = pathlib.Path(__file__).resolve().parents[3]
        reviews_js = (repo / "assets" / "reviews.js").read_text("utf-8")
        assert "fetch(" not in reviews_js, (
            "reviews.js fetches something — the published list must stay a "
            "hand-curated literal")
        assert "/api/" not in reviews_js


class TestTheLink:
    async def test_it_opens_a_form_and_nothing_else(self, client, db,
                                                    admin_on):
        ref = await delivered_order(client, db)
        order = await load(db, ref)
        await svc.ask(db, order)
        token = (await svc.existing_for_order(db, order.id)).token

        page = await client.get(f"/r/{token}")
        assert page.status_code == 200
        assert "noindex" in page.headers["x-robots-tag"]
        # Not an account, not an order, not a price.
        assert ref not in page.text
        assert order.customer_phone not in page.text

    async def test_the_permission_box_starts_unticked_in_the_markup(
            self, client, db, admin_on):
        ref = await delivered_order(client, db)
        order = await load(db, ref)
        await svc.ask(db, order)
        token = (await svc.existing_for_order(db, order.id)).token
        html = (await client.get(f"/r/{token}")).text
        box = html[html.index('id="r-publish"') - 60:
                   html.index('id="r-publish"') + 20]
        assert "checked" not in box, box

    async def test_an_unknown_token_is_a_404(self, client, db):
        for bad in ("nope", "a" * 43):
            assert (await client.get(f"/r/{bad}")).status_code == 404
            resp = await client.post(f"/api/v1/reviews/{bad}",
                                     json={"text": "hello"})
            assert resp.status_code == 404

    async def test_an_empty_review_is_refused(self, client, db, admin_on):
        ref = await delivered_order(client, db)
        order = await load(db, ref)
        await svc.ask(db, order)
        token = (await svc.existing_for_order(db, order.id)).token
        resp = await client.post(f"/api/v1/reviews/{token}", json={"text": ""})
        assert resp.status_code == 422


class TestTheOperatorSeesThem:
    async def test_submitted_reviews_reach_the_console(self, client, db,
                                                       admin_on):
        ref = await delivered_order(client, db)
        order = await load(db, ref)
        await svc.ask(db, order)
        token = (await svc.existing_for_order(db, order.id)).token
        await client.post(f"/api/v1/reviews/{token}",
                          json={"text": "Beautiful book.",
                                "display_name": "Aziza K.", "city": "Tashkent",
                                "may_publish": True})

        body = (await client.get("/api/v1/admin/reviews", headers=AUTH)).json()
        row = next(r for r in body["reviews"] if r["human_ref"] == ref)
        assert row["text"] == "Beautiful book."
        assert row["may_publish"] is True
        assert "by hand" in body["publishing"]

    async def test_an_unanswered_request_is_not_listed_as_a_review(
            self, client, db, admin_on):
        ref = await delivered_order(client, db)
        order = await load(db, ref)
        await svc.ask(db, order)
        body = (await client.get("/api/v1/admin/reviews", headers=AUTH)).json()
        assert all(r["human_ref"] != ref for r in body["reviews"])

    async def test_the_console_needs_the_admin_token(self, client, db):
        assert (await client.get("/api/v1/admin/reviews")).status_code == 404


class TestTheEvent:
    async def test_submitting_records_one(self, client, db, admin_on):
        ref = await delivered_order(client, db)
        order = await load(db, ref)
        await svc.ask(db, order)
        token = (await svc.existing_for_order(db, order.id)).token
        await client.post(f"/api/v1/reviews/{token}",
                          json={"text": "Good.", "may_publish": True})

        rows = (await db.execute(select(FunnelEvent).where(
            FunnelEvent.book_id == order.book_id,
            FunnelEvent.event_type == EventType.REVIEW_SUBMITTED.value)
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].properties["may_publish"] is True

    async def test_a_correction_does_not_count_as_a_second_review(
            self, client, db, admin_on):
        ref = await delivered_order(client, db)
        order = await load(db, ref)
        await svc.ask(db, order)
        token = (await svc.existing_for_order(db, order.id)).token
        for _ in range(3):
            await client.post(f"/api/v1/reviews/{token}",
                              json={"text": "Good.", "may_publish": True})
        rows = (await db.execute(select(FunnelEvent).where(
            FunnelEvent.book_id == order.book_id,
            FunnelEvent.event_type == EventType.REVIEW_SUBMITTED.value)
        )).scalars().all()
        assert len(rows) == 1


async def test_it_runs_as_part_of_the_nightly_job(client, db, admin_on):
    from app.services.lifecycle import run_nightly

    await delivered_order(client, db)
    result = await run_nightly(db)
    assert result["review_requests"] == 1
    assert (await db.execute(select(ReviewRequest))).scalars().all()
