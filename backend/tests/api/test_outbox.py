"""Milestone 11: transactional outbox + Telegram notification (R9)."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.outbox import OutboxMessage, OutboxStatus
from app.services import outbox as outbox_svc
from app.services import telegram as telegram_svc
from tests.api.test_payments import checked_out, pay_event, send


@pytest.fixture
def telegram_capture(monkeypatch):
    """Successful Telegram transport; captures every sent message text."""
    sent: list[str] = []
    monkeypatch.setattr(telegram_svc, "_post_telegram", sent.append)
    return sent


@pytest.fixture
def telegram_down(monkeypatch):
    def boom(text: str) -> None:
        raise telegram_svc.TelegramError("telegram is down")
    monkeypatch.setattr(telegram_svc, "_post_telegram", boom)


async def outbox_rows(db) -> list[OutboxMessage]:
    rows = (await db.execute(
        select(OutboxMessage).order_by(OutboxMessage.created_at)
    )).scalars().all()
    for row in rows:
        await db.refresh(row)
    return rows


def aware(dt: datetime) -> datetime:
    """SQLite returns naive datetimes for timezone-aware columns; Postgres
    returns aware ones. Normalize for comparisons."""
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class TestOutboxHappyPath:
    async def test_rendered_order_notifies_telegram_with_links(
            self, client, db, telegram_capture):
        _, _, checkout = await checked_out(client, db)
        ref, amount = checkout["human_ref"], checkout["amount_minor"]
        resp = await send(client, pay_event(ref, amount))
        assert resp.status_code == 200

        [message] = await outbox_rows(db)
        assert message.topic == "order.rendered"
        assert message.status == OutboxStatus.SENT.value
        assert message.payload["human_ref"] == ref

        [text] = telegram_capture
        # R9: reference, customer, pages, amount, and LINKS — never the file.
        assert ref in text
        assert "Aziza Karimova" in text
        assert "+998 90 123-45-67" in text
        assert "Address: Tashkent, Chilonzor 5, dom 12, kv 34" in text
        assert "Email: aziza@example.com" in text
        assert "Pages: 16" in text
        assert text.count("http") >= 2
        assert "interior.pdf" in text and "cover.pdf" in text
        assert "%PDF" not in text
        # No type was picked for this book — no dangling Type line.
        assert "Type:" not in text

    async def test_book_type_reaches_the_printer(
            self, client, db, telegram_capture):
        import uuid as uuid_mod

        from app.models.book import Book

        book_id, _, checkout = await checked_out(client, db)
        book = (await db.execute(
            select(Book).where(Book.id == uuid_mod.UUID(book_id))
        )).scalar_one()
        book.book_type = "travel"
        await db.commit()
        await send(client, pay_event(checkout["human_ref"],
                                     checkout["amount_minor"]))
        [text] = telegram_capture
        assert "Type: ✈️ Travel book" in text

    async def test_links_are_time_limited_signed_urls(
            self, client, db, telegram_capture):
        _, _, checkout = await checked_out(client, db)
        await send(client, pay_event(checkout["human_ref"],
                                     checkout["amount_minor"]))
        [text] = telegram_capture
        # Presigned URLs carry signature + expiry query parameters.
        assert "Signature=" in text or "X-Amz-Signature=" in text


class TestOutboxResilience:
    async def test_telegram_outage_keeps_message_pending_never_lost(
            self, client, db, telegram_down):
        _, _, checkout = await checked_out(client, db)
        resp = await send(client, pay_event(checkout["human_ref"],
                                            checkout["amount_minor"]))
        # The payment and render both succeeded regardless of Telegram.
        assert resp.status_code == 200
        assert resp.json()["order_status"] == "rendered"

        [message] = await outbox_rows(db)
        assert message.status == OutboxStatus.PENDING.value
        assert message.attempts == 1
        assert "telegram is down" in message.last_error
        assert aware(message.next_attempt_at) > datetime.now(UTC)

    async def test_recovery_delivers_on_next_pass(
            self, client, db, telegram_down, monkeypatch):
        _, _, checkout = await checked_out(client, db)
        await send(client, pay_event(checkout["human_ref"],
                                     checkout["amount_minor"]))
        [message] = await outbox_rows(db)
        assert message.status == OutboxStatus.PENDING.value

        # Telegram recovers; make the retry due now.
        sent: list[str] = []
        monkeypatch.setattr(telegram_svc, "_post_telegram", sent.append)
        message.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()

        delivered = await outbox_svc.deliver_pending(db)
        assert delivered == 1
        assert len(sent) == 1
        [message] = await outbox_rows(db)
        assert message.status == OutboxStatus.SENT.value

    async def test_delivery_pass_skips_sent_messages(
            self, client, db, telegram_capture):
        _, _, checkout = await checked_out(client, db)
        await send(client, pay_event(checkout["human_ref"],
                                     checkout["amount_minor"]))
        assert len(telegram_capture) == 1
        # A second pass sends nothing new — duplicates come only from
        # crash-between-send-and-commit, which consumers must tolerate.
        assert await outbox_svc.deliver_pending(db) == 0
        assert len(telegram_capture) == 1

    async def test_backoff_grows_and_gives_up_at_max_attempts(
            self, client, db, telegram_down):
        _, _, checkout = await checked_out(client, db)
        await send(client, pay_event(checkout["human_ref"],
                                     checkout["amount_minor"]))

        previous_gap = timedelta(0)
        for attempt in range(2, outbox_svc.MAX_ATTEMPTS + 1):
            [message] = await outbox_rows(db)
            message.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
            await db.commit()
            await outbox_svc.deliver_pending(db)
            [message] = await outbox_rows(db)
            assert message.attempts == attempt
            if message.status == OutboxStatus.PENDING.value:
                gap = aware(message.next_attempt_at) - datetime.now(UTC)
                assert gap >= previous_gap  # exponential (capped) backoff
                previous_gap = min(gap, timedelta(seconds=outbox_svc.BACKOFF_CAP_S / 2))

        [message] = await outbox_rows(db)
        assert message.status == OutboxStatus.FAILED.value
        assert message.attempts == outbox_svc.MAX_ATTEMPTS


class TestTelegramMessage:
    def test_unconfigured_credentials_raise_for_retry(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
        from app.config import get_settings
        get_settings.cache_clear()
        with pytest.raises(telegram_svc.TelegramError, match="not configured"):
            telegram_svc._post_telegram("hello")
        get_settings.cache_clear()
