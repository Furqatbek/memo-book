"""CR-003-2 — the three messages a customer hears during production.

The thing under test is restraint. An operator moves an order through six
or seven internal states; the customer hears about three of them, once
each, and never hears the same one twice. A bot that narrates every step
gets muted, and then the shipping message is muted too.

The second thing under test is that a message is never sent inline. The
operator is one person with a phone in a print shop; a Telegram outage
must not make their status update fail, and a status that was recorded
with its message silently dropped is worse than either.
"""
import uuid

import pytest
from sqlalchemy import select

from app.domain.states import OrderStatus
from app.models.book import Book
from app.models.order import Order, OrderEvent
from app.models.outbox import OutboxMessage
from app.services import outbox, production_updates
from tests.api.test_admin_orders import AUTH, admin, an_order, load  # noqa: F401


async def to_production(client, db, ref: str) -> None:
    """Walk an order to sent_to_production the way the console does."""
    resp = await client.post(f"/api/v1/admin/orders/{ref}/confirm-payment",
                             headers=AUTH, json={"note": "bank transfer seen"})
    assert resp.status_code == 200, resp.text
    resp = await client.post(f"/api/v1/admin/orders/{ref}/status", headers=AUTH,
                             json={"target": "sent_to_production"})
    assert resp.status_code == 200, resp.text


async def advance(client, ref: str, target: str, **extra):
    return await client.post(f"/api/v1/admin/orders/{ref}/status", headers=AUTH,
                             json={"target": target, **extra})


async def customer_messages(db, order_id: uuid.UUID | None = None) -> list[dict]:
    """Everything queued for a CUSTOMER, in order. Deliberately excludes the
    printer's and the operator's own notifications — those are a different
    audience and are allowed to be chatty."""
    rows = (await db.execute(
        select(OutboxMessage)
        .where(OutboxMessage.topic.in_((outbox.TOPIC_BOOK_REMINDER_TG,
                                        outbox.TOPIC_ORDER_PROGRESS)))
        .order_by(OutboxMessage.created_at))).scalars().all()
    return [r.payload for r in rows]


class TestWhichStagesTheCustomerHearsAbout:
    @pytest.mark.parametrize("status", ["printing", "binding", "shipped"])
    def test_the_three_that_reach_them(self, status):
        assert status in production_updates.CUSTOMER_STAGES

    @pytest.mark.parametrize("status", [
        "paid", "rendering", "rendered", "sent_to_production",
        "quality_check", "delivered", "cancelled", "refunded",
    ])
    def test_and_everything_else_stays_internal(self, status):
        """quality_check is the interesting one: it is a real stage the
        operator uses, and telling the customer "we are checking it for
        defects" invents a worry they did not have."""
        assert status not in production_updates.CUSTOMER_STAGES

    async def test_an_internal_move_queues_nothing(self, client, db, admin):
        ref = await an_order(client, db)
        await to_production(client, db, ref)
        assert await customer_messages(db) == []

        assert (await advance(client, ref, "printing")).status_code == 200
        assert (await advance(client, ref, "quality_check")).status_code == 200
        texts = [m["text"] for m in await customer_messages(db)]
        assert len(texts) == 1, (
            f"quality_check reached the customer: {texts}")


class TestIdempotency:
    async def test_the_same_transition_twice_sends_one_message(
            self, client, db, admin):
        """An operator on a phone in a print shop will press this twice. The
        state machine already refuses the second move; what is being proved
        here is that the message does not escape even if it did not."""
        ref = await an_order(client, db)
        await to_production(client, db, ref)
        await advance(client, ref, "printing")

        order = await load(db, ref)
        # Force the second attempt past the state machine, which is the only
        # way to test the notifier's own guard rather than the machine's.
        queued = await production_updates.notify(db, order, "printing")
        assert queued is False
        assert len(await customer_messages(db)) == 1

    async def test_the_guard_reads_the_audit_trail(self, client, db, admin):
        """No new table for a fact the order's own history already holds."""
        ref = await an_order(client, db)
        await to_production(client, db, ref)
        await advance(client, ref, "printing")
        order = await load(db, ref)

        assert await production_updates.already_notified(
            db, order.id, OrderStatus.PRINTING.value)
        assert not await production_updates.already_notified(
            db, order.id, OrderStatus.SHIPPED.value)

        note = (await db.execute(
            select(OrderEvent.note).where(
                OrderEvent.order_id == order.id,
                OrderEvent.note.like(f"{production_updates.SENT_NOTE}%"))
        )).scalars().first()
        assert note and note.startswith(production_updates.SENT_NOTE)


class TestTheMessages:
    def test_shipping_carries_the_eta_and_the_only_ask(self):
        text = production_updates.compose("shipped", None, "Thursday")
        assert "Thursday" in text
        assert production_updates.TAG_US in text

    def test_and_the_earlier_ones_ask_for_nothing(self):
        for status in ("printing", "binding"):
            text = production_updates.compose(status, None, None)
            assert production_updates.TAG_US not in text, (
                f"{status} asks the customer for something; only the last "
                "message is allowed to")

    def test_an_operators_note_is_appended_not_substituted(self):
        text = production_updates.compose(
            "printing", "Your cover stock arrived today.", None)
        assert production_updates.CUSTOMER_STAGES["printing"] in text
        assert "cover stock" in text

    def test_an_eta_on_a_stage_that_is_not_shipping_is_ignored(self):
        """"Expected Thursday" on the printing message would read as a
        delivery promise made three stages too early."""
        assert "Thursday" not in production_updates.compose(
            "printing", None, "Thursday")


class TestDelivery:
    async def test_nothing_is_sent_inline(self, client, db, admin, monkeypatch):
        """If this ever regresses, a Telegram outage starts failing the
        operator's status updates."""
        from app.services import telegram as telegram_svc

        calls: list = []
        monkeypatch.setattr(telegram_svc, "_call",
                            lambda method, body: calls.append(method))
        ref = await an_order(client, db)
        await to_production(client, db, ref)
        calls.clear()
        assert (await advance(client, ref, "printing")).status_code == 200
        assert calls == [], f"sent inline from the request handler: {calls}"

    async def test_telegram_is_preferred_when_the_book_is_linked(
            self, client, db, admin):
        ref = await an_order(client, db)
        order = await load(db, ref)
        book = (await db.execute(
            select(Book).where(Book.id == order.book_id))).scalar_one()
        book.telegram_chat_id = 4242
        await db.commit()

        await to_production(client, db, ref)
        await advance(client, ref, "shipped")
        messages = await customer_messages(db)
        assert len(messages) == 1
        assert messages[0]["chat_id"] == 4242

    async def test_email_is_the_fallback(self, client, db, admin):
        ref = await an_order(client, db)
        await to_production(client, db, ref)
        await advance(client, ref, "shipped")
        messages = await customer_messages(db)
        assert len(messages) == 1
        assert messages[0]["email"] == "aziza@example.com"

    async def test_a_photo_travels_as_a_KEY_not_a_url(self, client, db, admin):
        """The link is minted at delivery time. A URL signed when the
        message was queued would arrive expired if it waited out an outage
        — the same rule the print files follow."""
        ref = await an_order(client, db)
        order = await load(db, ref)
        book = (await db.execute(
            select(Book).where(Book.id == order.book_id))).scalar_one()
        book.telegram_chat_id = 99
        await db.commit()

        await to_production(client, db, ref)
        await advance(client, ref, "printing",
                      photo_key="ops/press/2026-01-01.jpg")
        payload = (await customer_messages(db))[0]
        assert payload["photo_key"] == "ops/press/2026-01-01.jpg"
        assert "http" not in payload["photo_key"]

    async def test_the_operators_note_reaches_the_customer_not_the_audit_log(
            self, client, db, admin):
        """Two fields, two audiences. `note` is internal shorthand — "Bek
        says Tuesday, chase him" — and must never be the thing the customer
        reads."""
        ref = await an_order(client, db)
        await to_production(client, db, ref)
        await advance(client, ref, "printing",
                      note="chase Bek about the stock",
                      customer_note="your cover stock arrived this morning")
        text = (await customer_messages(db))[0]["text"]
        assert "cover stock arrived" in text
        assert "chase Bek" not in text

    async def test_a_customer_with_no_channel_is_not_an_error(
            self, client, db, admin):
        """Plenty of customers give a phone number and nothing else. The
        operator's own notification already told them the order moved."""
        ref = await an_order(client, db)
        order = await load(db, ref)
        order.customer_email = None
        await db.commit()

        await to_production(client, db, ref)
        resp = await advance(client, ref, "shipped")
        assert resp.status_code == 200
        assert await customer_messages(db) == []


class TestTheOperatorCanActuallyReachThis:
    """The feature's entire value is a photograph of a press, taken on a
    phone, by one person. If the console cannot reach these stages or
    cannot carry the picture, everything above is code that never runs."""

    async def test_the_three_stages_are_offered_by_the_console(
            self, client, db, admin):
        from app.services.admin_orders import OPERATOR_TARGETS

        for status in production_updates.CUSTOMER_STAGES:
            assert status in OPERATOR_TARGETS, (
                f"{status} sends a customer message but no operator action "
                "can reach it")

    async def test_a_photo_uploads_and_comes_back_as_a_key(
            self, client, db, admin):
        from tests.render.helpers import fixture_photo_bytes

        ref = await an_order(client, db)
        resp = await client.post(
            f"/api/v1/admin/orders/{ref}/progress-photo", headers=AUTH,
            files={"photo": ("press.jpg", fixture_photo_bytes(900, 700, 3),
                             "image/jpeg")})
        assert resp.status_code == 201, resp.text
        key = resp.json()["photo_key"]
        assert key.startswith("ops/progress/")
        assert ref in key
        assert not key.startswith("http")

    async def test_the_photo_is_shrunk_and_stripped_of_its_exif(
            self, client, db, admin):
        """An operator's phone photo carries GPS. This picture is sent to a
        customer, so the print shop's location must not go with it."""
        import io

        from PIL import Image

        big = io.BytesIO()
        Image.new("RGB", (4000, 3000), (120, 90, 60)).save(
            big, format="JPEG",
            exif=Image.Exif() if not hasattr(Image, "_no_exif") else None)
        ref = await an_order(client, db)
        resp = await client.post(
            f"/api/v1/admin/orders/{ref}/progress-photo", headers=AUTH,
            files={"photo": ("press.jpg", big.getvalue(), "image/jpeg")})
        assert resp.status_code == 201, resp.text

        import anyio

        from app import storage
        from app.services.progress_photos import MAX_EDGE_PX

        data = await anyio.to_thread.run_sync(
            storage.get_bytes, resp.json()["photo_key"])
        out = Image.open(io.BytesIO(data))
        out.load()
        assert max(out.width, out.height) <= MAX_EDGE_PX
        assert not dict(out.getexif()), "EXIF survived the resize"

    async def test_a_file_that_is_not_a_photo_says_so(self, client, db, admin):
        ref = await an_order(client, db)
        resp = await client.post(
            f"/api/v1/admin/orders/{ref}/progress-photo", headers=AUTH,
            files={"photo": ("notes.txt", b"not an image", "text/plain")})
        assert resp.status_code == 422
        assert "photo" in resp.json()["detail"]

    async def test_the_upload_needs_the_admin_token_like_everything_else(
            self, client, db, admin):
        from tests.render.helpers import fixture_photo_bytes

        ref = await an_order(client, db)
        resp = await client.post(
            f"/api/v1/admin/orders/{ref}/progress-photo",
            files={"photo": ("p.jpg", fixture_photo_bytes(400, 300, 1),
                             "image/jpeg")})
        assert resp.status_code == 404

    async def test_an_unknown_order_cannot_be_used_as_a_dumping_ground(
            self, client, db, admin):
        from tests.render.helpers import fixture_photo_bytes

        resp = await client.post(
            "/api/v1/admin/orders/UB-NOPE1/progress-photo", headers=AUTH,
            files={"photo": ("p.jpg", fixture_photo_bytes(400, 300, 1),
                             "image/jpeg")})
        assert resp.status_code == 404
