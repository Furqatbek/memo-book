"""Milestone 8: checkout gauntlet, locking, audit trail, public lookup."""
import re
import uuid

from sqlalchemy import select

from app.config import get_settings
from app.models.book import Book
from app.models.order import Order, OrderEvent
from app.services.orders import cancel_order
from tests.api.test_books import auth, make_book
from tests.render.helpers import seed_rendered_book

CUSTOMER = {
    "name": "Aziza Karimova",
    "phone": "+998 90 123-45-67",
    "address": "Tashkent, Chilonzor 5, dom 12, kv 34",
    "email": "aziza@example.com",
    "confirmed_preview": True,
}


async def ready_book(client, db) -> tuple[str, dict]:
    """A complete 16-page book with a fresh, confirmed-able preview."""
    book_id = await seed_rendered_book(db, client, 16)
    row = (await db.execute(
        select(Book).where(Book.id == uuid.UUID(book_id)))).scalar_one()
    headers = {"X-Edit-Token": row.edit_token}
    resp = await client.post(f"/api/v1/books/{book_id}/preview", headers=headers)
    assert resp.status_code == 202
    return book_id, headers


async def do_checkout(client, book_id, headers, **overrides):
    return await client.post(f"/api/v1/books/{book_id}/checkout",
                             json={**CUSTOMER, **overrides}, headers=headers)


class TestCheckoutHappyPath:
    async def test_locks_book_and_creates_pending_order(self, client, db):
        book_id, headers = await ready_book(client, db)
        resp = await do_checkout(client, book_id, headers)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert re.fullmatch(r"UB-[23456789ABCDEFGHJKMNPQRSTUVWXYZ]{5}",
                            body["human_ref"])
        assert body["order_status"] == "pending_payment"
        assert body["amount_minor"] == get_settings().price_minor_16
        assert body["currency"] == "UZS"

        book = (await client.get(f"/api/v1/books/{book_id}", headers=headers)).json()
        assert book["status"] == "locked"

        # 423 on every layout mutation after locking.
        patch = await client.patch(f"/api/v1/books/{book_id}/layout",
                                   json=book["layout"],
                                   headers={**headers, "If-Match": "3"})
        assert patch.status_code == 423

    async def test_audit_trail_written(self, client, db):
        book_id, headers = await ready_book(client, db)
        await do_checkout(client, book_id, headers)
        order = (await db.execute(select(Order).where(
            Order.book_id == uuid.UUID(book_id)))).scalar_one()
        events = (await db.execute(
            select(OrderEvent).where(OrderEvent.order_id == order.id)
            .order_by(OrderEvent.created_at)
        )).scalars().all()
        assert [(e.from_status, e.to_status) for e in events] == [
            (None, "draft_order"),
            ("draft_order", "pending_payment"),
        ]
        assert order.preview_confirmed_at is not None

    async def test_amount_is_integer_minor_units(self, client, db):
        book_id, headers = await ready_book(client, db)
        body = (await do_checkout(client, book_id, headers)).json()
        assert isinstance(body["amount_minor"], int)
        assert body["amount_minor"] > 0


class TestCheckoutGauntlet:
    async def test_without_confirmed_preview_rejected(self, client, db):
        book_id, headers = await ready_book(client, db)
        resp = await do_checkout(client, book_id, headers, confirmed_preview=False)
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "PREVIEW_NOT_CONFIRMED"
        # Nothing happened: no order, book still editable.
        assert (await db.execute(select(Order))).scalar_one_or_none() is None
        book = (await client.get(f"/api/v1/books/{book_id}", headers=headers)).json()
        assert book["status"] == "draft"

    async def test_without_any_preview_rejected(self, client, db):
        book_id = await seed_rendered_book(db, client, 16)
        row = (await db.execute(
            select(Book).where(Book.id == uuid.UUID(book_id)))).scalar_one()
        resp = await do_checkout(client, book_id, {"X-Edit-Token": row.edit_token})
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "PREVIEW_STALE"

    async def test_stale_preview_rejected(self, client, db):
        book_id, headers = await ready_book(client, db)
        book = (await client.get(f"/api/v1/books/{book_id}", headers=headers)).json()
        layout = book["layout"]
        layout["pages"][0]["texts"] = [{
            "id": "t1", "x_mm": 12, "y_mm": 100, "w_mm": 50, "h_mm": 10,
            "content": "edited after preview",
        }]
        patched = await client.patch(
            f"/api/v1/books/{book_id}/layout", json=layout,
            headers={**headers, "If-Match": str(book["layout_version"])},
        )
        assert patched.status_code == 200

        resp = await do_checkout(client, book_id, headers)
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "PREVIEW_STALE"

    async def test_insufficient_photos_rejected(self, client, db):
        # Empty book, preview rendered (blank pages) and confirmed anyway.
        book = await make_book(client, 16)
        await client.post(f"/api/v1/books/{book['book_id']}/preview",
                          headers=auth(book))
        resp = await do_checkout(client, book["book_id"], auth(book))
        assert resp.status_code == 409
        body = resp.json()["error"]
        assert body["code"] == "PHOTOS_INSUFFICIENT"
        assert body["details"] == {"have": 0, "need": 16}

    async def test_enough_photos_but_empty_pages_rejected(self, client, db):
        book_id, headers = await ready_book(client, db)
        # Blank out one placement, re-preview so the preview is fresh.
        book = (await client.get(f"/api/v1/books/{book_id}", headers=headers)).json()
        layout = book["layout"]
        layout["pages"][7]["placements"] = []
        await client.patch(f"/api/v1/books/{book_id}/layout", json=layout,
                           headers={**headers, "If-Match": str(book["layout_version"])})
        await client.post(f"/api/v1/books/{book_id}/preview", headers=headers)

        resp = await do_checkout(client, book_id, headers)
        assert resp.status_code == 409
        body = resp.json()["error"]
        assert body["code"] == "PAGES_INCOMPLETE"
        assert body["details"]["empty_pages"] == [7]

    async def test_double_checkout_rejected(self, client, db):
        book_id, headers = await ready_book(client, db)
        assert (await do_checkout(client, book_id, headers)).status_code == 201
        second = await do_checkout(client, book_id, headers)
        assert second.status_code == 423
        assert second.json()["error"]["code"] == "BOOK_LOCKED"


class TestCancellation:
    async def test_cancel_unlocks_book_and_recheckout_reuses_order(self, client, db):
        book_id, headers = await ready_book(client, db)
        first = (await do_checkout(client, book_id, headers)).json()
        order = (await db.execute(select(Order).where(
            Order.book_id == uuid.UUID(book_id)))).scalar_one()

        await cancel_order(db, order.id, note="provider timeout")
        book = (await client.get(f"/api/v1/books/{book_id}", headers=headers)).json()
        assert book["status"] == "draft"

        second = await do_checkout(client, book_id, headers,
                                   name="Someone Else", phone="+998 91 000 11 22")
        assert second.status_code == 201
        assert second.json()["human_ref"] == first["human_ref"]  # same order row

        events = (await db.execute(
            select(OrderEvent).where(OrderEvent.order_id == order.id)
            .order_by(OrderEvent.created_at)
        )).scalars().all()
        assert [e.to_status for e in events] == [
            "draft_order", "pending_payment", "cancelled", "pending_payment",
        ]


class TestPublicLookup:
    async def test_lookup_by_ref_and_phone(self, client, db):
        book_id, headers = await ready_book(client, db)
        ref = (await do_checkout(client, book_id, headers)).json()["human_ref"]

        resp = await client.get(f"/api/v1/orders/{ref}",
                                params={"phone": "998901234567"})  # other formatting
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "pending_payment"
        assert body["page_count"] == 16
        assert body["paid_at"] is None
        assert "customer_name" not in body  # public endpoint leaks no PII

    async def test_wrong_phone_indistinguishable_from_unknown_ref(self, client, db):
        book_id, headers = await ready_book(client, db)
        ref = (await do_checkout(client, book_id, headers)).json()["human_ref"]
        wrong_phone = await client.get(f"/api/v1/orders/{ref}",
                                       params={"phone": "+998 99 999 99 99"})
        unknown_ref = await client.get("/api/v1/orders/UB-XXXXX",
                                       params={"phone": "998901234567"})
        assert wrong_phone.status_code == unknown_ref.status_code == 404
        assert wrong_phone.json() == unknown_ref.json()
