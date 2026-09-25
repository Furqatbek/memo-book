"""CR-003-3 — gift mode at checkout.

One rule carries the whole feature: **the recipient never hears from us.**
A present somebody was told about in advance is not a present, and the
messages that would spoil it are exactly the ones this system is otherwise
proud of sending — three production updates, a reminder, a review request.

So the tests are mostly about silence. The recipient's details exist for
one purpose, which is telling the person packing the box where to send it
and what to write on the card, and they must not leak into any channel.
"""
import uuid

import pytest
from sqlalchemy import select

from app.models.book import Book
from app.models.gift import GiftDetails
from app.models.outbox import OutboxMessage
from app.services import orders as orders_svc
from app.services import outbox, telegram
from tests.api.test_admin_orders import AUTH, load
from tests.api.test_checkout import CUSTOMER, do_checkout, ready_book
from tests.api.test_production_updates import (
    advance,
    customer_messages,
    to_production,
)

GIFT = {
    "recipient_name": "Dilnoza Rashidova",
    "recipient_phone": "+998 91 777-88-99",
    "recipient_address": "Nukus, Doslyq 14, kv 7",
    "gift_message": "Ko'p yillik do'stligimiz uchun",
    "hide_price": True,
}


async def gift_order(client, db, **gift_overrides) -> str:
    book_id, headers = await ready_book(client, db)
    resp = await do_checkout(client, book_id, headers,
                             gift={**GIFT, **gift_overrides})
    assert resp.status_code == 201, resp.text
    return resp.json()["human_ref"]


class TestWhoTheOrderBelongsTo:
    async def test_the_buyer_stays_the_customer(self, client, db):
        """They paid, they are told what is happening, and they are who we
        ring if anything is wrong. The recipient is an address."""
        ref = await gift_order(client, db)
        order = await load(db, ref)
        assert order.customer_name == CUSTOMER["name"]
        assert order.customer_phone == CUSTOMER["phone"]
        assert order.customer_email == CUSTOMER["email"]
        assert order.customer_address == CUSTOMER["address"]

    async def test_the_recipient_is_stored_separately(self, client, db):
        ref = await gift_order(client, db)
        order = await load(db, ref)
        gift = await orders_svc.gift_for(db, order.id)
        assert gift is not None
        assert gift.recipient_name == GIFT["recipient_name"]
        assert gift.recipient_address == GIFT["recipient_address"]

    async def test_hiding_the_price_is_the_default(self, client, db):
        """A present with the price in the box is not a present. Opt out,
        never opt in."""
        book_id, headers = await ready_book(client, db)
        minimal = {k: v for k, v in GIFT.items()
                   if k in ("recipient_name", "recipient_phone",
                            "recipient_address")}
        resp = await do_checkout(client, book_id, headers, gift=minimal)
        assert resp.status_code == 201, resp.text
        order = await load(db, resp.json()["human_ref"])
        gift = await orders_svc.gift_for(db, order.id)
        assert gift.hide_price is True

    async def test_an_ordinary_order_has_no_gift_row(self, client, db):
        book_id, headers = await ready_book(client, db)
        resp = await do_checkout(client, book_id, headers)
        order = await load(db, resp.json()["human_ref"])
        assert await orders_svc.gift_for(db, order.id) is None


class TestTheRecipientHearsNothing:
    async def test_no_production_message_goes_to_them(self, client, db, admin):
        """The integration test the CR asks for by name: all three updates
        reach the buyer, and the recipient receives nothing at all."""
        ref = await gift_order(client, db)
        await to_production(client, db, ref)
        for stage in ("printing", "binding", "shipped"):
            assert (await advance(client, ref, stage)).status_code == 200

        messages = await customer_messages(db)
        assert len(messages) == 3, [m["text"] for m in messages]
        for message in messages:
            # Every one of them went to the buyer's own address.
            assert message.get("email") == CUSTOMER["email"]
            blob = repr(message)
            assert GIFT["recipient_name"] not in blob
            assert GIFT["recipient_phone"].replace(" ", "") not in \
                blob.replace(" ", "")
            assert "Nukus" not in blob

    async def test_the_recipients_phone_is_never_a_channel(self, client, db,
                                                           admin):
        """There is no code path that could send to it — which is the point
        of keeping those details in a table of their own. This test is the
        thing that would notice if somebody added one."""
        ref = await gift_order(client, db)
        await to_production(client, db, ref)
        await advance(client, ref, "shipped")
        rows = (await db.execute(select(OutboxMessage))).scalars().all()
        for row in rows:
            blob = repr(row.payload)
            if row.topic in (outbox.TOPIC_BOOK_REMINDER_TG,
                             outbox.TOPIC_ORDER_PROGRESS,
                             outbox.TOPIC_BOOK_REMINDER):
                assert GIFT["recipient_phone"] not in blob, row.topic

    async def test_a_gift_book_is_not_reminded_to_the_recipient(
            self, client, db):
        """Reminders go to the book, and the book belongs to the buyer. The
        recipient does not have one and must never acquire one."""
        ref = await gift_order(client, db)
        order = await load(db, ref)
        book = (await db.execute(
            select(Book).where(Book.id == order.book_id))).scalar_one()
        assert book.email in (None, CUSTOMER["email"])


class TestWhatThePrinterIsTold:
    """The opposite requirement, and just as important: the person packing
    the box must see everything, loudly, because every line changes what
    they do."""

    def _payload(self, **gift):
        order = type("O", (), {
            "id": uuid.uuid4(), "human_ref": "UB-ABCDE",
            "status": "rendered", "customer_name": "Aziza",
            "customer_phone": "+998 90 000-00-00", "customer_address": "Tashkent",
            "customer_email": "aziza@example.com",
            "amount_minor": 39000000, "currency": "UZS"})()
        book = type("B", (), {"page_count": 16, "book_type": "travel"})()
        gift_obj = type("G", (), {
            "recipient_name": GIFT["recipient_name"],
            "recipient_phone": GIFT["recipient_phone"],
            "recipient_address": GIFT["recipient_address"],
            "gift_message": gift.get("gift_message", GIFT["gift_message"]),
            "deliver_after": gift.get("deliver_after"),
            "hide_price": gift.get("hide_price", True)})()
        return outbox.rendered_payload(order, book, "i.pdf", "c.pdf",
                                       gift=gift_obj)

    def test_the_message_shouts_that_it_is_a_gift(self, s3):
        text = telegram.build_production_message(self._payload())
        assert "GIFT" in text
        assert "do not contact the recipient" in text

    def test_it_carries_the_delivery_address_and_the_card(self, s3):
        text = telegram.build_production_message(self._payload())
        assert GIFT["recipient_address"] in text
        assert GIFT["gift_message"] in text

    def test_it_says_to_keep_the_price_out_of_the_box(self, s3):
        text = telegram.build_production_message(self._payload())
        assert "No price anywhere in the box." in text

    def test_and_does_not_when_the_buyer_asked_for_the_price_to_stay(self, s3):
        text = telegram.build_production_message(
            self._payload(hide_price=False))
        assert "No price anywhere in the box." not in text

    def test_a_deliver_after_date_is_impossible_to_miss(self, s3):
        from datetime import date

        text = telegram.build_production_message(
            self._payload(deliver_after=date(2026, 12, 30)))
        assert "2026-12-30" in text
        assert "NOT before" in text

    def test_the_gift_block_comes_before_the_print_links(self, s3):
        """The packer reads the top of the message and opens the files. A
        gift instruction below two long presigned URLs is an instruction
        nobody sees."""
        text = telegram.build_production_message(self._payload())
        assert text.index("GIFT") < text.index("Interior PDF")

    def test_an_ordinary_order_says_nothing_about_gifts(self, s3):
        order = type("O", (), {
            "id": uuid.uuid4(), "human_ref": "UB-ABCDE", "status": "rendered",
            "customer_name": "Aziza", "customer_phone": "+998 90 000-00-00",
            "customer_address": "Tashkent", "customer_email": None,
            "amount_minor": 39000000, "currency": "UZS"})()
        book = type("B", (), {"page_count": 16, "book_type": "travel"})()
        text = telegram.build_production_message(
            outbox.rendered_payload(order, book, "i.pdf", "c.pdf"))
        assert "GIFT" not in text


class TestReCheckout:
    async def test_a_cancelled_order_re_checked_out_replaces_the_gift(
            self, client, db, admin):
        """One order row per book (A33). A stale recipient from a cancelled
        attempt would send the book to the wrong address."""
        ref = await gift_order(client, db)
        order = await load(db, ref)
        book_id = str(order.book_id)
        await client.post(f"/api/v1/admin/orders/{ref}/status", headers=AUTH,
                          json={"target": "cancelled"})

        row = (await db.execute(
            select(Book).where(Book.id == uuid.UUID(book_id)))).scalar_one()
        headers = {"X-Edit-Token": row.edit_token}
        await client.post(f"/api/v1/books/{book_id}/preview", headers=headers)
        resp = await do_checkout(client, book_id, headers,
                                 gift={**GIFT,
                                       "recipient_name": "Someone Else",
                                       "recipient_address": "Andijan, 5"})
        assert resp.status_code == 201, resp.text

        again = await load(db, resp.json()["human_ref"])
        gift = await orders_svc.gift_for(db, again.id)
        assert gift.recipient_name == "Someone Else"
        assert gift.recipient_address == "Andijan, 5"

        # Exactly one row: the first recipient is gone, not sitting behind
        # the second waiting to be picked up by a query that forgot to sort.
        rows = (await db.execute(select(GiftDetails))).scalars().all()
        assert len(rows) == 1


class TestValidation:
    @pytest.mark.parametrize("missing", [
        "recipient_name", "recipient_phone", "recipient_address"])
    async def test_a_gift_needs_somewhere_to_go(self, client, db, missing):
        book_id, headers = await ready_book(client, db)
        gift = {k: v for k, v in GIFT.items() if k != missing}
        resp = await do_checkout(client, book_id, headers, gift=gift)
        assert resp.status_code == 422

    async def test_an_unknown_gift_field_is_refused(self, client, db):
        """extra="forbid". A typo'd field name that silently did nothing
        would be a gift instruction the buyer thinks they gave."""
        book_id, headers = await ready_book(client, db)
        resp = await do_checkout(client, book_id, headers,
                                 gift={**GIFT, "hidePrice": False})
        assert resp.status_code == 422


class TestTheEvent:
    async def test_enabling_gift_mode_is_recorded(self, client, db):
        """The gift share of orders shapes the next two campaigns, and a
        number nobody has to go and count by hand is the only kind that
        gets looked at."""
        from app.domain.events import EventType
        from app.models.funnel_event import FunnelEvent

        ref = await gift_order(client, db)
        order = await load(db, ref)
        kinds = (await db.execute(
            select(FunnelEvent.event_type).where(
                FunnelEvent.book_id == order.book_id))).scalars().all()
        assert EventType.GIFT_MODE_ENABLED.value in kinds

    async def test_an_ordinary_checkout_does_not_record_it(self, client, db):
        from app.domain.events import EventType
        from app.models.funnel_event import FunnelEvent

        book_id, headers = await ready_book(client, db)
        await do_checkout(client, book_id, headers)
        kinds = (await db.execute(
            select(FunnelEvent.event_type).where(
                FunnelEvent.book_id == uuid.UUID(book_id)))).scalars().all()
        assert EventType.GIFT_MODE_ENABLED.value not in kinds
