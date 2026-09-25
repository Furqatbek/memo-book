"""Telegram as a recovery channel — Change 2.

The customer half of the bot. An operator redeems a code with `/link`; a
customer taps a deep link that sends `/start <token>`, and from then on
their reminders arrive somewhere they actually read.

The tests that matter are about the ways this could go wrong quietly:

  * the deep-link token must NOT be the edit token — a link that travels
    through Telegram and gets forwarded must not carry the key to
    somebody's photographs;
  * a retried update must not act twice, because Telegram retries until it
    gets a 200 and the customer sees the duplicate;
  * `/stop` must stop everything, not the most recent book;
  * one chat must be able to hold several books.
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.models.book import Book
from app.models.outbox import OutboxMessage
from app.services import telegram as telegram_svc
from tests.api.test_books import auth, make_book

SECRET = "test-webhook-secret"
HOOK = "/api/v1/telegram/webhook"
HDRS = {"X-Telegram-Bot-Api-Secret-Token": SECRET}
CHAT = 555001


@pytest.fixture
def bot(monkeypatch):
    """The bot configured, and every outbound Telegram call captured."""
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token")
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "rspixelbot")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100123")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://rspixel.uz")
    get_settings.cache_clear()
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(telegram_svc, "_call",
                        lambda method, body: calls.append((method, body)))
    yield calls
    get_settings.cache_clear()


def start(token: str, chat_id: int = CHAT, update_id: int = 1) -> dict:
    return {"update_id": update_id,
            "message": {"message_id": 3, "from": {"id": 77},
                        "chat": {"id": chat_id}, "text": f"/start {token}"}}


def stop_cmd(chat_id: int = CHAT, update_id: int = 2) -> dict:
    return {"update_id": update_id,
            "message": {"message_id": 4, "from": {"id": 77},
                        "chat": {"id": chat_id}, "text": "/stop"}}


async def link_of(client, book) -> dict:
    resp = await client.get(f"/api/v1/books/{book['book_id']}/telegram-link",
                            headers=auth(book))
    assert resp.status_code == 200, resp.text
    return resp.json()


async def give_photo(db, book) -> None:
    """A draft with nothing in it gets no reminders (Change 4)."""
    from app.models.photo import Photo

    bid = uuid.UUID(book["book_id"])
    db.add(Photo(id=uuid.uuid4(), book_id=bid, status="ready",
                 original_key=f"books/{bid}/orig/a",
                 display_key=f"books/{bid}/disp/a",
                 thumb_key=f"books/{bid}/thumb/a",
                 mime_original="image/jpeg", bytes_original=1,
                 orig_width=100, orig_height=100,
                 uploaded_at=datetime.now(UTC), sha256=uuid.uuid4().hex))
    await db.commit()


async def book_row(db, book) -> Book:
    return (await db.execute(
        select(Book).where(Book.id == uuid.UUID(book["book_id"])))).scalar_one()


class TestTheDeepLink:
    async def test_it_points_at_the_bot_with_a_token(self, client, bot):
        book = await make_book(client, 16)
        body = await link_of(client, book)
        assert body["available"] is True
        assert body["deep_link"].startswith("https://t.me/rspixelbot?start=")
        assert body["linked"] is False

    async def test_the_token_is_not_the_edit_token(self, client, bot, db):
        """The security design of the whole feature. A deep link travels
        through Telegram's servers, sits in a chat list and gets forwarded;
        the edit token is all that stands between a stranger and these
        photographs."""
        book = await make_book(client, 16)
        token = (await link_of(client, book))["deep_link"].split("start=")[1]
        assert token != book["edit_token"]
        assert token not in book["edit_token"]
        row = await book_row(db, book)
        assert row.telegram_token == token
        assert row.edit_token != token

    async def test_asking_twice_gives_the_same_live_token(self, client, bot):
        """Otherwise every open of the panel leaves another working secret
        behind."""
        book = await make_book(client, 16)
        first = (await link_of(client, book))["deep_link"]
        second = (await link_of(client, book))["deep_link"]
        assert first == second

    async def test_somebody_elses_book_is_a_404(self, client, bot):
        book = await make_book(client, 16)
        resp = await client.get(f"/api/v1/books/{book['book_id']}/telegram-link",
                                headers={"X-Edit-Token": "not-the-token"})
        assert resp.status_code == 404

    async def test_with_no_bot_configured_the_offer_is_withdrawn(
            self, client, monkeypatch):
        """Better no button than one that lands nowhere — the P0-2 lesson
        in a different place."""
        monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "")
        get_settings.cache_clear()
        book = await make_book(client, 16)
        body = await link_of(client, book)
        assert body["available"] is False and body["deep_link"] is None
        get_settings.cache_clear()


class TestStartLinksTheChat:
    async def test_a_valid_token_links_and_confirms(self, client, bot, db):
        book = await make_book(client, 16)
        token = (await link_of(client, book))["deep_link"].split("start=")[1]
        resp = await client.post(HOOK, json=start(token), headers=HDRS)
        assert resp.status_code == 200

        row = await book_row(db, book)
        assert row.telegram_chat_id == CHAT
        assert row.telegram_linked_at is not None
        # The confirmation is QUEUED, not sent inline: a Telegram outage
        # must not make the webhook throw, and a lost confirmation has to
        # be retried rather than dropped.
        assert not [b for m, b in bot if m == "sendMessage"]
        msg = (await db.execute(select(OutboxMessage).where(
            OutboxMessage.topic == "telegram.reply"))).scalars().first()
        assert msg is not None
        assert str(book["book_id"]) in msg.payload["text"]

    async def test_the_token_is_spent(self, client, bot, db):
        """A forwarded copy of the link stops working once it has been used."""
        book = await make_book(client, 16)
        token = (await link_of(client, book))["deep_link"].split("start=")[1]
        await client.post(HOOK, json=start(token), headers=HDRS)
        row = await book_row(db, book)
        assert row.telegram_token is None

    async def test_the_link_endpoint_then_reports_it_linked(self, client, bot):
        book = await make_book(client, 16)
        token = (await link_of(client, book))["deep_link"].split("start=")[1]
        await client.post(HOOK, json=start(token), headers=HDRS)
        assert (await link_of(client, book))["linked"] is True

    async def test_it_records_the_contact_as_a_funnel_step(self, client, bot, db):
        from app.domain.events import EventType
        from tests.test_funnel import count_of

        book = await make_book(client, 16)
        token = (await link_of(client, book))["deep_link"].split("start=")[1]
        await client.post(HOOK, json=start(token), headers=HDRS)
        rows = await count_of(db, EventType.CONTACT_CAPTURED,
                              uuid.UUID(book["book_id"]))
        assert rows == 1


class TestAnUnusableTokenIsAnsweredPolitely:
    async def test_an_unknown_token_gets_a_friendly_reply_and_a_200(
            self, client, bot, db):
        """Links get forwarded. Somebody else's copy is an ordinary event,
        not an error — and a non-200 would make Telegram retry it for ever."""
        resp = await client.post(HOOK, json=start("no-such-token"), headers=HDRS)
        assert resp.status_code == 200
        msg = (await db.execute(select(OutboxMessage).where(
            OutboxMessage.topic == "telegram.reply"))).scalars().first()
        assert msg is not None and "expired" in msg.payload["text"].lower()

    async def test_an_expired_token_is_refused(self, client, bot, db):
        book = await make_book(client, 16)
        token = (await link_of(client, book))["deep_link"].split("start=")[1]
        row = await book_row(db, book)
        row.telegram_token_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()

        await client.post(HOOK, json=start(token), headers=HDRS)
        row = await book_row(db, book)
        assert row.telegram_chat_id is None

    async def test_a_bare_start_still_reaches_the_operator_help(self, client, bot):
        """The operator side must keep working: `/start` with no payload is
        not a customer arriving from a deep link."""
        resp = await client.post(HOOK, json={
            "update_id": 9,
            "message": {"message_id": 1, "from": {"id": 77},
                        "chat": {"id": CHAT}, "text": "/start"}},
            headers=HDRS)
        assert resp.status_code == 200


class TestItIsIdempotent:
    async def test_the_same_update_twice_acts_once(self, client, bot, db):
        """Telegram retries until it gets a 200. Acting twice would send the
        customer a duplicate, which is the visible half of the bug."""
        book = await make_book(client, 16)
        token = (await link_of(client, book))["deep_link"].split("start=")[1]
        payload = start(token, update_id=4242)
        await client.post(HOOK, json=payload, headers=HDRS)
        second = await client.post(HOOK, json=payload, headers=HDRS)
        assert second.status_code == 200
        assert second.json()["ignored"] == "duplicate update"
        replies = list((await db.execute(select(OutboxMessage).where(
            OutboxMessage.topic == "telegram.reply"))).scalars())
        assert len(replies) == 1

    async def test_a_different_update_is_not_deduplicated(self, client, bot, db):
        await client.post(HOOK, json=start("nope", update_id=1), headers=HDRS)
        await client.post(HOOK, json=start("nope", update_id=2), headers=HDRS)
        replies = list((await db.execute(select(OutboxMessage).where(
            OutboxMessage.topic == "telegram.reply"))).scalars())
        assert len(replies) == 2


class TestStop:
    async def test_stop_clears_every_book_in_that_chat(self, client, bot, db):
        """Somebody who asks to be left alone has not asked to be left alone
        about one of their three books."""
        books = []
        for i in range(3):
            book = await make_book(client, 16)
            token = (await link_of(client, book))["deep_link"].split("start=")[1]
            await client.post(HOOK, json=start(token, update_id=100 + i),
                              headers=HDRS)
            books.append(book)
        for book in books:
            assert (await book_row(db, book)).telegram_chat_id == CHAT

        await client.post(HOOK, json=stop_cmd(update_id=200), headers=HDRS)
        for book in books:
            row = await book_row(db, book)
            assert row.telegram_chat_id is None
            assert row.telegram_linked_at is None

    async def test_stop_in_a_chat_with_nothing_linked_is_still_polite(
            self, client, bot, db):
        resp = await client.post(HOOK, json=stop_cmd(chat_id=999, update_id=300),
                                 headers=HDRS)
        assert resp.status_code == 200
        msg = (await db.execute(select(OutboxMessage).where(
            OutboxMessage.topic == "telegram.reply"))).scalars().first()
        assert msg and "anyway" in msg.payload["text"].lower()

    async def test_one_chat_may_hold_several_books(self, client, bot, db):
        """Modelled as a nullable column, not a unique constraint: a person
        who makes one book for their mother and another for a wedding is one
        chat and two books, and a unique chat id would make the second link
        silently fail."""
        a = await make_book(client, 16)
        b = await make_book(client, 16)
        for i, book in enumerate((a, b)):
            token = (await link_of(client, book))["deep_link"].split("start=")[1]
            await client.post(HOOK, json=start(token, update_id=400 + i),
                              headers=HDRS)
        assert (await book_row(db, a)).telegram_chat_id == CHAT
        assert (await book_row(db, b)).telegram_chat_id == CHAT


class TestTheWebhookLock:
    async def test_a_wrong_secret_is_refused(self, client, bot):
        """Answered 404 rather than 401, deliberately and against the
        letter of the brief: A96's rule is that a wrong secret learns
        nothing a right one would, so this endpoint is never an oracle for
        whether an RS Pixel bot lives at this host. The requirement —
        reject anything without the secret — is met, and more strictly."""
        resp = await client.post(HOOK, json=start("x"),
                                 headers={"X-Telegram-Bot-Api-Secret-Token": "no"})
        assert resp.status_code == 404

    async def test_no_secret_configured_means_no_endpoint(
            self, client, monkeypatch):
        monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "")
        get_settings.cache_clear()
        resp = await client.post(HOOK, json=start("x"), headers=HDRS)
        assert resp.status_code == 404
        get_settings.cache_clear()


class TestRemindersPreferTelegram:
    async def test_a_linked_book_is_reminded_in_telegram_not_email(
            self, client, bot, db):
        from app.services.lifecycle import queue_reminders

        book = await make_book(client, 16)
        token = (await link_of(client, book))["deep_link"].split("start=")[1]
        await client.post(HOOK, json=start(token, update_id=500), headers=HDRS)

        await give_photo(db, book)
        row = await book_row(db, book)
        row.email = "a@example.com"          # both channels available
        row.updated_at = datetime.now(UTC) - timedelta(days=4)
        await db.commit()

        assert await queue_reminders(db) == 1
        msgs = list((await db.execute(select(OutboxMessage))).scalars())
        topics = {m.topic for m in msgs}
        assert "book.reminder.telegram" in topics
        assert "book.reminder" not in topics

    async def test_a_book_with_only_telegram_is_still_reminded(
            self, client, bot, db):
        """Before this change a reminder needed an email address, so a
        customer who gave us only Telegram would never have heard from us."""
        from app.services.lifecycle import queue_reminders

        book = await make_book(client, 16)
        token = (await link_of(client, book))["deep_link"].split("start=")[1]
        await client.post(HOOK, json=start(token, update_id=600), headers=HDRS)
        await give_photo(db, book)
        row = await book_row(db, book)
        row.updated_at = datetime.now(UTC) - timedelta(days=4)
        await db.commit()
        assert await queue_reminders(db) == 1

    async def test_the_telegram_reminder_carries_an_absolute_link(
            self, client, bot, db):
        """A relative "/editor/abc" is not a link in a chat window."""
        from app.services.lifecycle import queue_reminders

        book = await make_book(client, 16)
        token = (await link_of(client, book))["deep_link"].split("start=")[1]
        await client.post(HOOK, json=start(token, update_id=700), headers=HDRS)
        await give_photo(db, book)
        row = await book_row(db, book)
        row.updated_at = datetime.now(UTC) - timedelta(days=4)
        await db.commit()
        await queue_reminders(db)
        msg = (await db.execute(select(OutboxMessage).where(
            OutboxMessage.topic == "book.reminder.telegram"))).scalars().first()
        assert msg.payload["text"].startswith("Your book is waiting")
        assert "https://rspixel.uz/editor/" in msg.payload["text"]
        # Recovered drafts have to be tellable from new traffic.
        assert "utm_source=reminder" in msg.payload["text"]
        assert "utm_campaign=draft_recovery" in msg.payload["text"]

    async def test_it_goes_through_the_outbox_and_not_inline(
            self, client, bot, db):
        """The requirement in one assertion: queueing a reminder sends
        nothing by itself. Delivery is the worker's job, with the
        at-least-once machinery every other notification gets."""
        from app.services.lifecycle import queue_reminders

        book = await make_book(client, 16)
        token = (await link_of(client, book))["deep_link"].split("start=")[1]
        await client.post(HOOK, json=start(token, update_id=800), headers=HDRS)
        before = len(bot)
        await give_photo(db, book)
        row = await book_row(db, book)
        row.updated_at = datetime.now(UTC) - timedelta(days=4)
        await db.commit()
        await queue_reminders(db)
        assert len(bot) == before          # nothing sent yet
        assert (await db.execute(select(OutboxMessage).where(
            OutboxMessage.topic == "book.reminder.telegram"))).scalars().first()
