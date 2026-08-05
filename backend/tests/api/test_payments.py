"""Milestone 9: webhook idempotency (R10), signature + amount verification,
and the paid -> rendering -> rendered fulfillment chain."""
import uuid

import anyio
import pytest
from sqlalchemy import select

from app import storage
from app.config import get_settings
from app.models.book import Book
from app.models.order import Order, OrderEvent
from app.models.payment import PaymentEvent, PdfArtifact
from app.models.photo import Photo
from tests.api.test_checkout import do_checkout, ready_book

SECRET_HEADER = {"X-Dev-Signature": "dev-secret-change-me"}


async def checked_out(client, db) -> tuple[str, dict, dict]:
    """Book through checkout; returns (book_id, headers, checkout body)."""
    book_id, headers = await ready_book(client, db)
    resp = await do_checkout(client, book_id, headers)
    assert resp.status_code == 201
    return book_id, headers, resp.json()


def pay_event(ref: str, amount: int, event_id: str = "evt-1") -> dict:
    return {"event_id": event_id, "action": "pay", "human_ref": ref,
            "amount_minor": amount}


async def send(client, body: dict, headers: dict | None = SECRET_HEADER):
    return await client.post("/api/v1/payments/dev/webhook", json=body,
                             headers=headers or {})


async def order_row(db, ref: str) -> Order:
    order = (await db.execute(
        select(Order).where(Order.human_ref == ref))).scalar_one()
    await db.refresh(order)
    return order


class TestHappyPath:
    async def test_paid_renders_and_produces_artifact(self, client, db):
        book_id, _headers, checkout = await checked_out(client, db)
        ref, amount = checkout["human_ref"], checkout["amount_minor"]
        assert checkout["payment"]["providers_available"] == ["dev"]

        resp = await send(client, pay_event(ref, amount))
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "ok"

        order = await order_row(db, ref)
        assert order.status == "rendered"
        assert order.paid_at is not None
        assert order.rendered_at is not None
        assert order.provider_txn_id == "evt-1"

        book = (await db.execute(
            select(Book).where(Book.id == uuid.UUID(book_id)))).scalar_one()
        await db.refresh(book)
        assert book.status == "ordered"

        artifacts = {a.kind: a for a in (await db.execute(
            select(PdfArtifact).where(PdfArtifact.order_id == order.id)
        )).scalars()}
        assert set(artifacts) == {"interior", "cover"}
        assert artifacts["interior"].page_count == 16
        assert artifacts["cover"].page_count == 1
        for artifact in artifacts.values():
            assert artifact.size_bytes > 0
            pdf = await anyio.to_thread.run_sync(storage.get_bytes,
                                                 artifact.storage_key)
            assert pdf.startswith(b"%PDF")

        events = (await db.execute(
            select(OrderEvent).where(OrderEvent.order_id == order.id)
            .order_by(OrderEvent.created_at)
        )).scalars().all()
        assert [e.to_status for e in events] == [
            "draft_order", "pending_payment", "paid", "rendering", "rendered",
        ]


class TestIdempotency:
    async def test_duplicate_webhook_no_duplicate_side_effects(self, client, db):
        _, _, checkout = await checked_out(client, db)
        ref, amount = checkout["human_ref"], checkout["amount_minor"]

        first = await send(client, pay_event(ref, amount))
        second = await send(client, pay_event(ref, amount))  # same event twice
        assert first.status_code == second.status_code == 200
        assert second.json()["order_status"] == "rendered"
        assert second.json()["duplicate"] is True

        order = await order_row(db, ref)
        artifacts = (await db.execute(select(PdfArtifact).where(
            PdfArtifact.order_id == order.id))).scalars().all()
        assert len(artifacts) == 2  # exactly one render: one interior + one cover

        payment_events = (await db.execute(select(PaymentEvent))).scalars().all()
        assert len(payment_events) == 1  # one idempotency row

        order_events = (await db.execute(select(OrderEvent).where(
            OrderEvent.order_id == order.id))).scalars().all()
        assert len(order_events) == 5  # no extra transitions

    async def test_new_event_id_on_paid_order_is_acknowledged(self, client, db):
        _, _, checkout = await checked_out(client, db)
        ref, amount = checkout["human_ref"], checkout["amount_minor"]
        await send(client, pay_event(ref, amount))
        resp = await send(client, pay_event(ref, amount, event_id="evt-2"))
        assert resp.status_code == 200
        assert resp.json()["duplicate"] is True  # acknowledged, not re-executed
        order = await order_row(db, ref)
        artifacts = (await db.execute(select(PdfArtifact).where(
            PdfArtifact.order_id == order.id))).scalars().all()
        assert len(artifacts) == 2  # still one interior + one cover


class TestSecurity:
    async def test_missing_signature_rejected_without_any_state_change(self, client, db):
        _, _, checkout = await checked_out(client, db)
        ref, amount = checkout["human_ref"], checkout["amount_minor"]
        resp = await send(client, pay_event(ref, amount), headers=None)
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "SIGNATURE_INVALID"
        assert (await order_row(db, ref)).status == "pending_payment"
        # Not even the audit table changed — rejected before parsing.
        assert (await db.execute(select(PaymentEvent))).scalars().all() == []

    async def test_wrong_signature_rejected(self, client, db):
        _, _, checkout = await checked_out(client, db)
        resp = await send(client,
                          pay_event(checkout["human_ref"], checkout["amount_minor"]),
                          headers={"X-Dev-Signature": "wrong"})
        assert resp.status_code == 403

    async def test_amount_mismatch_rejected_no_state_change(self, client, db):
        _, _, checkout = await checked_out(client, db)
        ref = checkout["human_ref"]
        wrong = checkout["amount_minor"] - 100
        resp = await send(client, pay_event(ref, wrong))
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "AMOUNT_MISMATCH"
        assert (await order_row(db, ref)).status == "pending_payment"
        # The event IS recorded for audit; replaying it returns the same error.
        assert len((await db.execute(select(PaymentEvent))).scalars().all()) == 1
        replay = await send(client, pay_event(ref, wrong))
        assert replay.status_code == 400

    async def test_unknown_order_is_provider_error_not_crash(self, client, db):
        resp = await send(client, pay_event("UB-XXXXX", 100))
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "ORDER_NOT_FOUND"

    async def test_disabled_provider_unknown(self, client, db, monkeypatch):
        _, _, checkout = await checked_out(client, db)
        monkeypatch.setenv("DEV_PAYMENTS_ENABLED", "false")
        get_settings.cache_clear()
        resp = await send(client,
                          pay_event(checkout["human_ref"], checkout["amount_minor"]))
        assert resp.status_code == 404


class TestCancel:
    async def test_provider_cancel_unlocks_book(self, client, db):
        book_id, headers, checkout = await checked_out(client, db)
        ref = checkout["human_ref"]
        resp = await send(client, {"event_id": "c1", "action": "cancel",
                                   "human_ref": ref})
        assert resp.status_code == 200
        assert (await order_row(db, ref)).status == "cancelled"
        book = (await client.get(f"/api/v1/books/{book_id}", headers=headers)).json()
        assert book["status"] == "draft"

    async def test_cancel_after_paid_is_illegal(self, client, db):
        _, _, checkout = await checked_out(client, db)
        ref, amount = checkout["human_ref"], checkout["amount_minor"]
        await send(client, pay_event(ref, amount))
        resp = await send(client, {"event_id": "c2", "action": "cancel",
                                   "human_ref": ref})
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "ILLEGAL_TRANSITION"


class TestRenderFailure:
    async def test_payment_accepted_even_when_render_fails(self, client, db):
        book_id, _, checkout = await checked_out(client, db)
        ref, amount = checkout["human_ref"], checkout["amount_minor"]
        # Break the render: delete one original from storage.
        photo = (await db.execute(select(Photo).where(
            Photo.book_id == uuid.UUID(book_id)))).scalars().first()
        await anyio.to_thread.run_sync(storage.delete_keys, [photo.original_key])

        resp = await send(client, pay_event(ref, amount))
        assert resp.status_code == 200  # the payment itself succeeded

        order = await order_row(db, ref)
        assert order.status == "render_failed"  # not a zombie state
        assert order.paid_at is not None
        artifacts = (await db.execute(select(PdfArtifact))).scalars().all()
        assert artifacts == []


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    yield
    get_settings.cache_clear()
