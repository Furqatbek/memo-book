"""A73: the orders section of the admin console.

This replaces three SSH scripts with buttons, so the thing worth proving is
that the buttons run the same machinery: the state machine decides what is
possible, every change writes an audit row, and confirming a transfer does
everything an acquirer's callback would — including enqueueing the render
exactly once.
"""
import uuid

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.domain.states import BookStatus, OrderStatus
from app.models.book import Book
from app.models.order import Order, OrderEvent
from app.models.payment import PdfArtifact
from app.services.admin_orders import OPERATOR_TARGETS
from tests.api.test_checkout import do_checkout, ready_book

TOKEN = "test-admin-token"
AUTH = {"X-Admin-Token": TOKEN}

ORDER_ROUTES = [
    ("GET", "/api/v1/admin/orders"),
    ("GET", "/api/v1/admin/orders/UB-ZZZZZ"),
    ("POST", "/api/v1/admin/orders/UB-ZZZZZ/confirm-payment"),
    ("POST", "/api/v1/admin/orders/UB-ZZZZZ/status"),
    ("POST", "/api/v1/admin/orders/UB-ZZZZZ/resend"),
]


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def an_order(client, db) -> str:
    """A real checked-out order, sitting in pending_payment."""
    book_id, headers = await ready_book(client, db)
    resp = await do_checkout(client, book_id, headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["human_ref"]


async def load(db, ref: str) -> Order:
    return (await db.execute(
        select(Order).where(Order.human_ref == ref))).scalar_one()


class TestTheLockCoversOrdersToo:
    @pytest.mark.parametrize("method,path", ORDER_ROUTES)
    async def test_every_order_route_needs_the_token(self, client, admin,
                                                     method, path):
        assert (await client.request(method, path)).status_code == 404

    @pytest.mark.parametrize("method,path", ORDER_ROUTES)
    async def test_no_configured_token_means_no_order_routes(self, client,
                                                             monkeypatch,
                                                             method, path):
        monkeypatch.setenv("ADMIN_TOKEN", "")
        get_settings.cache_clear()
        try:
            resp = await client.request(method, path, headers=AUTH)
            assert resp.status_code == 404
        finally:
            get_settings.cache_clear()


class TestTheList:
    async def test_it_shows_a_new_order_with_what_the_operator_needs(
            self, client, db, admin):
        ref = await an_order(client, db)
        body = (await client.get("/api/v1/admin/orders", headers=AUTH)).json()
        row = next(o for o in body["orders"] if o["human_ref"] == ref)
        assert row["status"] == "pending_payment"
        assert row["customer_name"] and row["customer_phone"]
        assert row["amount_minor"] > 0
        assert row["page_count"] == 16
        assert row["awaiting_payment_check"] is True

    async def test_open_is_the_default_and_hides_finished_orders(
            self, client, db, admin):
        ref = await an_order(client, db)
        await client.post(f"/api/v1/admin/orders/{ref}/status", headers=AUTH,
                          json={"target": "cancelled"})
        default = (await client.get("/api/v1/admin/orders", headers=AUTH)).json()
        assert [o["human_ref"] for o in default["orders"]] == []
        every = (await client.get("/api/v1/admin/orders?status=",
                                  headers=AUTH)).json()
        assert [o["human_ref"] for o in every["orders"]] == [ref]

    async def test_filtering_by_one_status(self, client, db, admin):
        ref = await an_order(client, db)
        hit = (await client.get("/api/v1/admin/orders?status=pending_payment",
                                headers=AUTH)).json()
        assert [o["human_ref"] for o in hit["orders"]] == [ref]
        miss = (await client.get("/api/v1/admin/orders?status=shipped",
                                 headers=AUTH)).json()
        assert miss["orders"] == []

    async def test_search_by_reference_name_and_phone(self, client, db, admin):
        ref = await an_order(client, db)
        order = await load(db, ref)
        for term in (ref, ref.lower(), order.customer_name[:4],
                     order.customer_phone[-6:]):
            found = (await client.get(f"/api/v1/admin/orders?status=&q={term}",
                                      headers=AUTH)).json()
            assert [o["human_ref"] for o in found["orders"]] == [ref], term

    async def test_a_phone_search_survives_punctuation(self, client, db, admin):
        """People type +998 90 123-45-67; the stored string is whatever they
        typed, so the digits have to be what is matched."""
        ref = await an_order(client, db)
        order = await load(db, ref)
        digits = "".join(c for c in order.customer_phone if c.isdigit())
        found = (await client.get(
            f"/api/v1/admin/orders?status=&q=%2B{digits[-9:]}", headers=AUTH)).json()
        assert [o["human_ref"] for o in found["orders"]] == [ref]


class TestNextStatusesComeFromTheStateMachine:
    async def test_a_pending_order_offers_only_cancel(self, client, db, admin):
        ref = await an_order(client, db)
        detail = (await client.get(f"/api/v1/admin/orders/{ref}",
                                   headers=AUTH)).json()
        assert detail["next_statuses"] == ["cancelled"]

    async def test_paid_is_never_an_operator_target(self):
        """Becoming paid does more than change a status — it locks the book
        and enqueues the render — so it has its own action and must not be
        reachable through the generic one."""
        assert OrderStatus.PAID.value not in OPERATOR_TARGETS

    async def test_a_rendered_order_can_go_to_production(self, client, db, admin):
        ref = await an_order(client, db)
        await client.post(f"/api/v1/admin/orders/{ref}/confirm-payment",
                          headers=AUTH)
        detail = (await client.get(f"/api/v1/admin/orders/{ref}",
                                   headers=AUTH)).json()
        assert detail["status"] == "rendered"      # eager render in tests
        assert "sent_to_production" in detail["next_statuses"]


class TestConfirmingATransfer:
    async def test_it_pays_the_order_and_locks_the_book(self, client, db, admin):
        ref = await an_order(client, db)
        resp = await client.post(f"/api/v1/admin/orders/{ref}/confirm-payment",
                                 headers=AUTH)
        assert resp.status_code == 200
        body = resp.json()
        assert body["already"] is False
        assert body["paid_at"] is not None
        assert body["provider"] == "card-transfer"

        order = await load(db, ref)
        await db.refresh(order)
        book = (await db.execute(
            select(Book).where(Book.id == order.book_id))).scalar_one()
        await db.refresh(book)
        assert book.status == BookStatus.ORDERED.value

    async def test_it_writes_an_audit_row_saying_who_did_it(
            self, client, db, admin):
        ref = await an_order(client, db)
        await client.post(f"/api/v1/admin/orders/{ref}/confirm-payment",
                          headers=AUTH, json={"note": "sberbank 12:04"})
        order = await load(db, ref)
        events = list((await db.execute(
            select(OrderEvent).where(OrderEvent.order_id == order.id)
        )).scalars())
        paid = [e for e in events if e.to_status == OrderStatus.PAID.value]
        assert len(paid) == 1
        assert paid[0].note == "sberbank 12:04"

    async def test_the_render_runs_and_produces_print_files(
            self, client, db, admin):
        ref = await an_order(client, db)
        await client.post(f"/api/v1/admin/orders/{ref}/confirm-payment",
                          headers=AUTH)
        detail = (await client.get(f"/api/v1/admin/orders/{ref}",
                                   headers=AUTH)).json()
        kinds = {a["kind"] for a in detail["artifacts"]}
        assert kinds == {"interior", "cover"}
        assert all(a["url"].startswith("http") for a in detail["artifacts"])
        assert all(a["bytes"] > 0 for a in detail["artifacts"])

    async def test_confirming_twice_does_not_render_twice(
            self, client, db, admin):
        """A double click must not bill the printer twice."""
        ref = await an_order(client, db)
        await client.post(f"/api/v1/admin/orders/{ref}/confirm-payment",
                          headers=AUTH)
        again = await client.post(f"/api/v1/admin/orders/{ref}/confirm-payment",
                                  headers=AUTH)
        assert again.status_code == 200
        assert again.json()["already"] is True

        order = await load(db, ref)
        artifacts = list((await db.execute(
            select(PdfArtifact).where(PdfArtifact.order_id == order.id)
        )).scalars())
        assert len(artifacts) == 2          # one interior, one cover. Not four.
        events = list((await db.execute(
            select(OrderEvent).where(OrderEvent.order_id == order.id)
        )).scalars())
        assert len([e for e in events if e.to_status == "paid"]) == 1

    async def test_it_refuses_an_order_that_is_already_finished(
            self, client, db, admin):
        ref = await an_order(client, db)
        await client.post(f"/api/v1/admin/orders/{ref}/status", headers=AUTH,
                          json={"target": "cancelled"})
        resp = await client.post(f"/api/v1/admin/orders/{ref}/confirm-payment",
                                 headers=AUTH)
        assert resp.status_code == 409

    async def test_an_unknown_reference_is_404(self, client, admin):
        resp = await client.post(
            "/api/v1/admin/orders/UB-NOPE1/confirm-payment", headers=AUTH)
        assert resp.status_code == 404


class TestMovingAnOrderAlong:
    async def _to_rendered(self, client, db) -> str:
        ref = await an_order(client, db)
        await client.post(f"/api/v1/admin/orders/{ref}/confirm-payment",
                          headers=AUTH)
        return ref

    async def test_the_fulfilment_path(self, client, db, admin):
        ref = await self._to_rendered(client, db)
        for target in ("sent_to_production", "shipped", "delivered"):
            resp = await client.post(f"/api/v1/admin/orders/{ref}/status",
                                     headers=AUTH, json={"target": target})
            assert resp.status_code == 200, resp.text
            assert resp.json()["status"] == target

    async def test_it_refuses_a_transition_the_machine_forbids(
            self, client, db, admin):
        ref = await an_order(client, db)          # pending_payment
        resp = await client.post(f"/api/v1/admin/orders/{ref}/status",
                                 headers=AUTH, json={"target": "shipped"})
        assert resp.status_code == 409

    async def test_it_refuses_a_target_that_is_not_an_operator_action(
            self, client, db, admin):
        ref = await an_order(client, db)
        for target in ("paid", "rendered", "draft_order", "", "nonsense"):
            resp = await client.post(f"/api/v1/admin/orders/{ref}/status",
                                     headers=AUTH, json={"target": target})
            assert resp.status_code == 409, target

    async def test_cancelling_unlocks_the_book_for_editing(
            self, client, db, admin):
        ref = await an_order(client, db)
        resp = await client.post(f"/api/v1/admin/orders/{ref}/status",
                                 headers=AUTH, json={"target": "cancelled"})
        assert resp.json()["status"] == "cancelled"
        order = await load(db, ref)
        book = (await db.execute(
            select(Book).where(Book.id == order.book_id))).scalar_one()
        await db.refresh(book)
        assert book.status == BookStatus.DRAFT.value

    async def test_cancelling_a_paid_order_also_unlocks_it(
            self, client, db, admin):
        """The trust-first pilot confirms orders before the money is checked,
        so the operator must be able to undo one (A56)."""
        ref = await self._to_rendered(client, db)
        resp = await client.post(f"/api/v1/admin/orders/{ref}/status",
                                 headers=AUTH, json={"target": "cancelled"})
        assert resp.status_code == 200
        order = await load(db, ref)
        book = (await db.execute(
            select(Book).where(Book.id == order.book_id))).scalar_one()
        await db.refresh(book)
        assert book.status == BookStatus.DRAFT.value

    async def test_every_move_leaves_an_audit_row(self, client, db, admin):
        ref = await self._to_rendered(client, db)
        await client.post(f"/api/v1/admin/orders/{ref}/status", headers=AUTH,
                          json={"target": "sent_to_production",
                                "note": "handed to Bek"})
        detail = (await client.get(f"/api/v1/admin/orders/{ref}",
                                   headers=AUTH)).json()
        moves = [(e["from"], e["to"], e["note"]) for e in detail["events"]]
        assert ("rendered", "sent_to_production", "handed to Bek") in moves


class TestTheDetailScreen:
    async def test_it_carries_the_delivery_details(self, client, db, admin):
        ref = await an_order(client, db)
        detail = (await client.get(f"/api/v1/admin/orders/{ref}",
                                   headers=AUTH)).json()
        assert detail["customer_address"]
        assert detail["book_status"] == BookStatus.LOCKED.value
        assert detail["events"], "an order always has at least its creation"

    async def test_it_has_no_print_files_before_the_render(
            self, client, db, admin):
        ref = await an_order(client, db)
        detail = (await client.get(f"/api/v1/admin/orders/{ref}",
                                   headers=AUTH)).json()
        assert detail["artifacts"] == []

    async def test_an_unknown_reference_is_404(self, client, admin):
        resp = await client.get("/api/v1/admin/orders/UB-NOPE1", headers=AUTH)
        assert resp.status_code == 404


class TestResendingToThePrinter:
    async def test_it_refuses_before_the_files_exist(self, client, db, admin):
        ref = await an_order(client, db)
        resp = await client.post(f"/api/v1/admin/orders/{ref}/resend",
                                 headers=AUTH)
        assert resp.status_code == 409

    async def test_it_queues_the_production_message_again(
            self, client, db, admin):
        from app.models.outbox import OutboxMessage

        ref = await an_order(client, db)
        await client.post(f"/api/v1/admin/orders/{ref}/confirm-payment",
                          headers=AUTH)
        before = len(list((await db.execute(select(OutboxMessage))).scalars()))
        resp = await client.post(f"/api/v1/admin/orders/{ref}/resend",
                                 headers=AUTH)
        assert resp.status_code == 200
        after = len(list((await db.execute(select(OutboxMessage))).scalars()))
        assert after == before + 1

    async def test_it_does_not_change_the_order(self, client, db, admin):
        ref = await an_order(client, db)
        await client.post(f"/api/v1/admin/orders/{ref}/confirm-payment",
                          headers=AUTH)
        before = (await client.get(f"/api/v1/admin/orders/{ref}",
                                   headers=AUTH)).json()
        await client.post(f"/api/v1/admin/orders/{ref}/resend", headers=AUTH)
        after = (await client.get(f"/api/v1/admin/orders/{ref}",
                                  headers=AUTH)).json()
        assert after["status"] == before["status"]
        assert len(after["events"]) == len(before["events"])


class TestWhatIsDeliberatelyAbsent:
    async def test_there_is_no_way_to_delete_an_order(self, client, db, admin):
        ref = await an_order(client, db)
        order = await load(db, ref)
        for path in (f"/api/v1/admin/orders/{ref}",
                     f"/api/v1/admin/orders/{order.id}"):
            resp = await client.request("DELETE", path, headers=AUTH)
            assert resp.status_code in (404, 405), path

    async def test_the_customer_still_cannot_reach_the_print_files(
            self, client, db, admin, monkeypatch):
        """The console hands the operator signed links; the public status
        page must not, outside dev environments."""
        monkeypatch.setenv("ENV", "prod")
        get_settings.cache_clear()
        try:
            ref = await an_order(client, db)
            await client.post(f"/api/v1/admin/orders/{ref}/confirm-payment",
                              headers=AUTH)
            order = await load(db, ref)
            public = await client.get(
                f"/api/v1/orders/{ref}?phone={order.customer_phone}")
            assert public.status_code == 200
            assert "artifact_urls" not in public.json()
        finally:
            get_settings.cache_clear()


class TestUuidsAreNotReferences:
    async def test_a_uuid_in_the_reference_slot_is_not_found(
            self, client, admin):
        resp = await client.get(f"/api/v1/admin/orders/{uuid.uuid4()}",
                                headers=AUTH)
        assert resp.status_code == 404
