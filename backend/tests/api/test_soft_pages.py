"""A79: the low-resolution judgement reaches somebody who can act on it.

The classifier was correct and connected to nothing that could prevent a bad
print. `placement_resolution()` was called only by its own tests, and
`RESOLUTION_TOO_LOW` — mapped to a status code since the first milestone —
was raised nowhere.

The fix is not to refuse the order. The threshold cannot tell a careless crop
from the only surviving photograph of somebody's grandmother, and the
customer is warned clearly, twice, before paying. What was missing is the
third reader: the person about to put ink on paper, for whom this is still a
cheap problem.
"""
import uuid

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.domain.resolution import soft_placements
from app.models.order import Order
from app.models.outbox import OutboxMessage
from app.services import outbox
from app.services.telegram import build_production_message
from tests.api.test_checkout import do_checkout
from tests.render.helpers import seed_rendered_book

TOKEN = "test-admin-token"
AUTH = {"X-Admin-Token": TOKEN}


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestTheDomainJudgement:
    def test_a_clean_book_reports_nothing(self):
        layout = {"cover": {}, "pages": [
            {"index": 0, "placements": [
                {"photo_id": "a", "w_mm": 154, "h_mm": 216, "fit": "cover"}]}]}
        assert soft_placements(layout, {"a": (3024, 4032)}) == []

    def test_pages_are_numbered_the_way_a_person_counts_them(self):
        """Page index 0 is page 1 on paper. Off-by-one here sends the printer
        to the wrong sheet."""
        layout = {"cover": {}, "pages": [
            {"index": 0, "placements": []},
            {"index": 1, "placements": [
                {"photo_id": "a", "w_mm": 154, "h_mm": 216, "fit": "cover"}]}]}
        found = soft_placements(layout, {"a": (640, 480)})
        assert [f["page"] for f in found] == [2]
        assert found[0]["where"] == "page 2"

    def test_the_cover_has_no_number(self):
        layout = {"cover": {"photo_id": "a"}, "pages": []}
        found = soft_placements(layout, {"a": (400, 400)})
        assert found[0]["page"] is None
        assert found[0]["where"] == "cover"

    def test_the_worst_comes_first(self):
        """The operator reads the top of the list."""
        layout = {"cover": {}, "pages": [
            # ~105 dpi letterboxed: a warning.
            {"index": 0, "placements": [
                {"photo_id": "soft", "w_mm": 154, "h_mm": 216,
                 "fit": "contain"}]},
            # under the 800px floor, full bleed: a block.
            {"index": 1, "placements": [
                {"photo_id": "bad", "w_mm": 154, "h_mm": 216,
                 "fit": "cover"}]}]}
        found = soft_placements(layout, {"soft": (640, 480), "bad": (300, 300)})
        assert [f["status"] for f in found] == ["block", "warn"]

    def test_a_photo_still_being_ingested_is_not_condemned(self):
        """No dimensions yet means unknown, not bad. Guessing "block" would
        warn the customer about a photo that turns out to be fine."""
        layout = {"cover": {}, "pages": [
            {"index": 0, "placements": [
                {"photo_id": "pending", "w_mm": 154, "h_mm": 216}]}]}
        assert soft_placements(layout, {}) == []


class TestThePrinterIsTold:
    def test_the_message_names_the_pages(self):
        message = build_production_message({
            "human_ref": "UB-AAAA1", "page_count": 32,
            "customer_name": "A", "customer_phone": "+998900000000",
            "amount_minor": 29900000, "interior_key": "k1", "cover_key": "k2",
            "soft_pages": [{"page": 3, "where": "page 3", "status": "block"},
                           {"page": None, "where": "cover", "status": "warn"}],
        })
        assert "page 3" in message and "cover" in message
        assert "BLURRY" in message

    def test_it_says_the_customer_already_agreed(self):
        """Otherwise the printer's first instinct is to stop and ask, which
        costs a day on an order that is fine to run."""
        message = build_production_message({
            "human_ref": "UB-AAAA1", "page_count": 32,
            "customer_name": "A", "customer_phone": "+998900000000",
            "amount_minor": 29900000, "interior_key": "k1", "cover_key": "k2",
            "soft_pages": [{"page": 3, "where": "page 3", "status": "warn"}],
        })
        assert "confirmed" in message.lower()

    def test_a_clean_book_adds_no_noise(self):
        message = build_production_message({
            "human_ref": "UB-AAAA1", "page_count": 32,
            "customer_name": "A", "customer_phone": "+998900000000",
            "amount_minor": 29900000, "interior_key": "k1", "cover_key": "k2",
            "soft_pages": [],
        })
        assert "resolution" not in message.lower()

    def test_a_long_list_is_truncated_rather_than_unreadable(self):
        soft = [{"page": n, "where": f"page {n}", "status": "warn"}
                for n in range(1, 21)]
        message = build_production_message({
            "human_ref": "UB-AAAA1", "page_count": 32,
            "customer_name": "A", "customer_phone": "+998900000000",
            "amount_minor": 29900000, "interior_key": "k1", "cover_key": "k2",
            "soft_pages": soft,
        })
        assert "+12 more" in message


class TestItSurvivesTheRealPipeline:
    async def test_a_rendered_order_carries_it_to_the_outbox(self, client, db):
        """End to end: a book with a genuinely small photo, paid, rendered —
        and the message queued for the printer says so."""
        book_id = await seed_rendered_book(db, client, 16,
                                           photo_pixels=(400, 300))
        from app.models.book import Book
        row = (await db.execute(
            select(Book).where(Book.id == uuid.UUID(book_id)))).scalar_one()
        headers = {"X-Edit-Token": row.edit_token}
        assert (await client.post(f"/api/v1/books/{book_id}/preview",
                                  headers=headers)).status_code == 202
        resp = await do_checkout(client, book_id, headers)
        assert resp.status_code == 201, resp.text

        # Loading the Book above put it in this session's identity map, and
        # checkout locked it through a DIFFERENT session. Without this,
        # mark_paid reads the stale `draft` copy and the transition is
        # refused for reasons that have nothing to do with the test.
        db.expire_all()

        from app.services.payments import mark_paid
        order = (await db.execute(select(Order).where(
            Order.human_ref == resp.json()["human_ref"]))).scalar_one()
        await mark_paid(db, order, note="t", provider="dev", txn_id="t1")

        message = (await db.execute(select(OutboxMessage).where(
            OutboxMessage.topic == outbox.TOPIC_ORDER_RENDERED
        ))).scalars().first()
        soft = message.payload["soft_pages"]
        assert soft, "a book of 400x300 photos reported no low-resolution pages"
        assert all(s["status"] == "block" for s in soft)

    async def test_the_console_shows_it_on_the_order(self, client, db, admin):
        book_id = await seed_rendered_book(db, client, 16,
                                           photo_pixels=(400, 300))
        from app.models.book import Book
        row = (await db.execute(
            select(Book).where(Book.id == uuid.UUID(book_id)))).scalar_one()
        headers = {"X-Edit-Token": row.edit_token}
        await client.post(f"/api/v1/books/{book_id}/preview", headers=headers)
        ref = (await do_checkout(client, book_id, headers)).json()["human_ref"]

        detail = (await client.get(f"/api/v1/admin/orders/{ref}",
                                   headers=AUTH)).json()
        assert detail["soft_pages"], "the console cannot see it"
        assert detail["soft_pages"][0]["where"].startswith("page ")

    async def test_a_good_book_reports_none(self, client, db, admin):
        """Deliberately NOT the shared fixture. Its 1600x1100 photos are
        genuinely soft on a full A5 page — 1100px over 216mm is 129 dpi —
        so using it here would assert that a real warning is absent."""
        book_id = await seed_rendered_book(db, client, 16,
                                           photo_pixels=(2600, 3600))
        from app.models.book import Book
        row = (await db.execute(
            select(Book).where(Book.id == uuid.UUID(book_id)))).scalar_one()
        headers = {"X-Edit-Token": row.edit_token}
        await client.post(f"/api/v1/books/{book_id}/preview", headers=headers)
        ref = (await do_checkout(client, book_id, headers)).json()["human_ref"]
        detail = (await client.get(f"/api/v1/admin/orders/{ref}",
                                   headers=AUTH)).json()
        assert detail["soft_pages"] == []
