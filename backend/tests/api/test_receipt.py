"""A100: the customer attaches proof of their transfer.

In the card-transfer pilot nobody tells us a payment arrived — the operator
matches transfers against the bank by hand. The receipt is the one piece of
evidence only the customer has.

The load-bearing test here is `test_a_file_pretending_to_be_a_png`. These
objects are served from our own storage hostname, so a stored HTML file
would be a script running on that origin, and a browser will cheerfully send
`image/png` for whatever it is handed. The type is therefore read out of the
BYTES and the declared one is ignored entirely.
"""
import pytest
from sqlalchemy import select

from app import storage
from app.models.order import Order
from app.models.outbox import OutboxMessage, OutboxStatus
from app.services.orders import PAY_CARD_STATUSES
from app.services.outbox import TOPIC_ORDER_RECEIPT
from app.services.receipts import RECEIPT_MAX_BYTES
from tests.api.test_checkout import CUSTOMER, do_checkout, ready_book

PHONE = CUSTOMER["phone"]

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200
PDF = b"%PDF-1.7\n" + b"\x00" * 200


async def an_order(client, db) -> str:
    book_id, headers = await ready_book(client, db)
    resp = await do_checkout(client, book_id, headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["human_ref"]


async def load(db, ref: str) -> Order:
    db.expire_all()
    return (await db.execute(
        select(Order).where(Order.human_ref == ref))).scalar_one()


async def receipt_messages(db) -> list[OutboxMessage]:
    """The outbox rows this upload wrote, oldest first.

    Refreshed one by one rather than through `expire_all`, which would also
    expire an Order the caller is still holding — and reading an expired
    instance is lazy IO in a place async SQLAlchemy will not do it.
    """
    rows = (await db.execute(
        select(OutboxMessage)
        .where(OutboxMessage.topic == TOPIC_ORDER_RECEIPT)
        .order_by(OutboxMessage.created_at))).scalars().all()
    for row in rows:
        await db.refresh(row)
    return list(rows)


async def send(client, ref: str, data: bytes, *, phone: str = PHONE,
               name: str = "receipt.png", mime: str = "image/png"):
    return await client.post(
        f"/api/v1/orders/{ref}/receipt",
        data={"phone": phone},
        files={"receipt": (name, data, mime)})


class TestAttachingOne:
    @pytest.mark.parametrize("label,data,expected", [
        ("png", PNG, "image/png"),
        ("jpeg", JPEG, "image/jpeg"),
        ("pdf", PDF, "application/pdf"),
    ])
    async def test_the_three_formats_we_accept(self, client, db, label, data,
                                               expected):
        ref = await an_order(client, db)
        resp = await send(client, ref, data)
        assert resp.status_code == 200, resp.text
        assert resp.json()["receipt_content_type"] == expected
        order = await load(db, ref)
        assert order.receipt_key and order.receipt_bytes == len(data)
        assert order.receipt_uploaded_at is not None

    async def test_the_bytes_land_in_storage(self, client, db):
        ref = await an_order(client, db)
        await send(client, ref, PDF, name="whatever.txt", mime="text/plain")
        order = await load(db, ref)
        assert storage.get_bytes(order.receipt_key) == PDF
        # Named by what it IS, not by what it arrived as.
        assert order.receipt_key.endswith(".pdf")
        assert order.receipt_content_type == "application/pdf"


class TestWhatWeRefuse:
    async def test_a_file_pretending_to_be_a_png(self, client, db):
        """The one that matters. These objects are served from our own
        storage hostname, so an HTML file stored here is a script on that
        origin — and the browser's declared type is the uploader's word,
        which is exactly what we are not taking."""
        ref = await an_order(client, db)
        resp = await send(client, ref, b"<html><script>alert(1)</script>",
                          name="receipt.png", mime="image/png")
        assert resp.status_code == 422
        assert "PNG, JPEG or PDF" in resp.text
        assert (await load(db, ref)).receipt_key is None

    @pytest.mark.parametrize("data", [
        b"GIF89a" + b"\x00" * 50,            # a real image, still not one of ours
        b"PK\x03\x04" + b"\x00" * 50,        # a zip
        b"not a file at all",
    ])
    async def test_other_formats(self, client, db, data):
        ref = await an_order(client, db)
        assert (await send(client, ref, data)).status_code == 422
        assert (await load(db, ref)).receipt_key is None

    async def test_something_too_big(self, client, db):
        ref = await an_order(client, db)
        huge = PNG + b"\x00" * RECEIPT_MAX_BYTES
        resp = await send(client, ref, huge)
        assert resp.status_code == 422
        assert "limit" in resp.text
        assert (await load(db, ref)).receipt_key is None

    async def test_a_file_exactly_at_the_limit_is_fine(self, client, db):
        """Off-by-one on a published limit is the difference between "2 MB"
        being true and being nearly true."""
        ref = await an_order(client, db)
        at_limit = PNG + b"\x00" * (RECEIPT_MAX_BYTES - len(PNG))
        assert len(at_limit) == RECEIPT_MAX_BYTES
        assert (await send(client, ref, at_limit)).status_code == 200

    async def test_an_empty_file(self, client, db):
        ref = await an_order(client, db)
        assert (await send(client, ref, b"")).status_code == 422


class TestWhoMayAttach:
    async def test_a_wrong_phone_is_refused(self, client, db):
        ref = await an_order(client, db)
        resp = await send(client, ref, PNG, phone="+998 99 999 99 99")
        assert resp.status_code == 404
        assert (await load(db, ref)).receipt_key is None

    async def test_a_wrong_phone_looks_like_an_unknown_reference(
            self, client, db):
        """The same property the status page has (A77): guessing must learn
        nothing, so the two answers have to be identical."""
        ref = await an_order(client, db)
        wrong_phone = await send(client, ref, PNG, phone="+998 99 999 99 99")
        unknown_ref = await send(client, "UB-NOPE1", PNG)
        assert wrong_phone.status_code == unknown_ref.status_code == 404
        assert wrong_phone.json() == unknown_ref.json()

    async def test_the_phone_may_be_written_differently(self, client, db):
        """It is the customer's own number typed again, not a password."""
        ref = await an_order(client, db)
        assert (await send(client, ref, PNG, phone="998901234567")
                ).status_code == 200


class TestWhenItStillMeansSomething:
    async def test_it_closes_once_the_book_has_gone_to_print(
            self, client, db):
        """Past this point the operator has matched the payment and sent the
        book to production. A receipt filed against a decision already made
        is evidence nobody will look at."""
        ref = await an_order(client, db)
        order = await load(db, ref)
        order.status = "sent_to_production"
        await db.commit()
        resp = await send(client, ref, PNG)
        assert resp.status_code == 409
        assert (await load(db, ref)).receipt_key is None

    async def test_the_window_is_the_one_the_card_is_shown_in(self):
        """The upload box and the bank card must open and close together —
        an order still asking for money must still accept the proof of it."""
        from app.services import orders as svc

        assert svc.PAY_CARD_STATUSES == PAY_CARD_STATUSES
        assert "sent_to_production" not in PAY_CARD_STATUSES
        assert "pending_payment" in PAY_CARD_STATUSES


class TestReplacing:
    async def test_a_second_upload_replaces_the_first(self, client, db):
        """Nearly always a correction of the first, so it overwrites rather
        than piling up."""
        ref = await an_order(client, db)
        await send(client, ref, PNG)
        first = (await load(db, ref)).receipt_key
        await send(client, ref, JPEG, name="better.jpg", mime="image/jpeg")
        order = await load(db, ref)
        assert order.receipt_content_type == "image/jpeg"
        assert storage.get_bytes(order.receipt_key) == JPEG
        # The old object had a different name, so it would have been left
        # behind — an orphan nobody can reach is still a receipt in a bucket.
        assert first != order.receipt_key
        assert not storage.object_exists(first)


class TestWhoSeesIt:
    async def test_the_customer_is_told_it_arrived_but_not_handed_it_back(
            self, client, db):
        """This page is guarded by a phone number, which is a weaker thing
        than a login, and a receipt can carry a bank balance across it."""
        ref = await an_order(client, db)
        await send(client, ref, PNG)
        body = (await client.get(f"/api/v1/orders/{ref}",
                                 params={"phone": PHONE})).json()
        assert body["receipt_uploaded_at"] is not None
        assert "receipt_url" not in body
        assert "receipt_key" not in body
        assert PNG[:8].decode("latin-1") not in str(body)

    async def test_before_any_upload_it_says_so(self, client, db):
        ref = await an_order(client, db)
        body = (await client.get(f"/api/v1/orders/{ref}",
                                 params={"phone": PHONE})).json()
        assert body["receipt_uploaded_at"] is None

    async def test_the_operator_gets_a_link_to_open(self, client, db):
        """It has to be in front of them at the moment they decide whether
        the money came."""
        from app.services.admin_orders import order_detail

        ref = await an_order(client, db)
        await send(client, ref, PDF, name="r.pdf", mime="application/pdf")
        detail = await order_detail(db, ref)
        assert detail["receipt"]["url"]
        assert detail["receipt"]["content_type"] == "application/pdf"
        assert detail["receipt"]["bytes"] == len(PDF)

    async def test_and_nothing_when_there_is_none(self, client, db):
        from app.services.admin_orders import order_detail

        ref = await an_order(client, db)
        assert (await order_detail(db, ref))["receipt"] is None


@pytest.fixture
def telegram_capture(monkeypatch):
    """Every message the operator chat would receive, with its keyboard."""
    from app.services import telegram as telegram_svc

    sent: list[tuple[str, dict | None]] = []
    monkeypatch.setattr(telegram_svc, "_post_telegram",
                        lambda text, markup=None: sent.append((text, markup)))
    return sent


class TestTheOperatorIsTold:
    """A102: a receipt saved where nobody is told about it is a customer
    waiting for a book while their proof of payment sits in a bucket.

    The upload now announces itself in the Telegram chat with a link to open
    the file — so the operator can go to the bank with the evidence in front
    of them rather than noticing the receipt next time they open the console.
    """

    async def test_an_upload_sends_a_message_with_a_link(
            self, client, db, telegram_capture):
        ref = await an_order(client, db)
        await send(client, ref, PNG)
        [(text, _markup)] = telegram_capture
        assert ref in text
        assert "receipt" in text.lower()
        assert "http" in text
        assert "PNG" in text

    async def test_the_link_points_at_the_bytes_that_were_stored(
            self, client, db, telegram_capture):
        """The load-bearing one. A link in a message and an object in a
        bucket are two separate things, and the message is only worth
        sending if it opens the file this customer actually uploaded."""
        ref = await an_order(client, db)
        await send(client, ref, PDF, name="r.pdf", mime="application/pdf")
        order = await load(db, ref)
        [(text, _)] = telegram_capture
        assert order.receipt_key in text
        assert storage.get_bytes(order.receipt_key) == PDF

    async def test_the_link_is_signed_and_time_limited(
            self, client, db, telegram_capture):
        ref = await an_order(client, db)
        await send(client, ref, PNG)
        [(text, _)] = telegram_capture
        url = [w for w in text.split() if w.startswith("http")][0]
        assert "Expires=" in url or "X-Amz-Signature=" in url

    async def test_the_message_carries_no_customer_pii(
            self, client, db, telegram_capture):
        """A76's rule for this chat: reference, money and the file. The name
        and the phone are a click away in a console that asks who you are."""
        ref = await an_order(client, db)
        await send(client, ref, PNG)
        [(text, _)] = telegram_capture
        for private in (CUSTOMER["name"], CUSTOMER["phone"],
                        CUSTOMER.get("email") or "\0",
                        CUSTOMER.get("address") or "\0"):
            assert private not in text

    async def test_it_offers_no_buttons(self, client, db, telegram_capture):
        """Confirming a payment is not a Telegram action — it stamps
        `paid_at` and starts the render, so it lives in the console. The only
        button this order could offer is *Cancel*, and a cancel button
        directly under a receipt is one fat thumb from killing the order the
        receipt is evidence for."""
        ref = await an_order(client, db)
        await send(client, ref, PNG)
        [(text, markup)] = telegram_capture
        assert markup is None
        assert "admin console" in text

    async def test_a_replacement_is_announced_too(
            self, client, db, telegram_capture):
        """A corrected receipt is precisely the thing worth a second
        message, and the new link must not point at the deleted object."""
        ref = await an_order(client, db)
        await send(client, ref, PNG)
        await send(client, ref, JPEG, name="better.jpg", mime="image/jpeg")
        assert len(telegram_capture) == 2
        order = await load(db, ref)
        assert order.receipt_key in telegram_capture[1][0]
        assert order.receipt_key not in telegram_capture[0][0]

    async def test_a_refused_upload_tells_nobody(
            self, client, db, telegram_capture):
        ref = await an_order(client, db)
        assert (await send(client, ref, b"GIF89a" + b"\x00" * 50)
                ).status_code == 422
        assert telegram_capture == []
        assert await receipt_messages(db) == []

    async def test_the_message_is_enqueued_with_the_key_not_a_url(self, client, db,
                                                                  telegram_capture):
        """Presigning at enqueue time puts a deadline on a message that has
        not been sent yet, so a delivery that waited out a Telegram outage
        and three backoffs would arrive with a link that no longer opens."""
        ref = await an_order(client, db)
        await send(client, ref, PNG)
        [message] = await receipt_messages(db)
        assert message.payload["receipt_key"].endswith(".png")
        assert "http" not in str(message.payload)

    async def test_it_is_committed_with_the_receipt_not_after_it(
            self, client, db, telegram_capture):
        """The outbox point: one transaction records the receipt and the
        message, so there is no window in which the file exists and nothing
        is going to say so."""
        ref = await an_order(client, db)
        await send(client, ref, PNG)
        order = await load(db, ref)
        [message] = await receipt_messages(db)
        assert order.receipt_key and message.payload["human_ref"] == ref
        assert message.status == OutboxStatus.SENT.value
