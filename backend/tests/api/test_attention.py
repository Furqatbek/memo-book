"""A76: the console's own view of what is stuck.

The reason this exists rather than leaning on the Telegram alerts: an alert
cannot report that alerting is broken. If the bot token is wrong or the
network to Telegram is down, every message retries eight times and is then
abandoned — including the one carrying the print files to the printer. The
order stays in `rendered`, which looks entirely healthy, and the customer
waits for a book nobody was told to print.
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.domain.states import OrderStatus
from app.models.order import Order, OrderEvent
from app.models.outbox import OutboxMessage, OutboxStatus
from app.services import outbox
from tests.services.test_stuck_orders import (
    break_the_render,
    paid_but_unrendered,
    paid_order,
)

TOKEN = "test-admin-token"
AUTH = {"X-Admin-Token": TOKEN}


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def attention(client) -> dict:
    resp = await client.get("/api/v1/admin/attention", headers=AUTH)
    assert resp.status_code == 200, resp.text
    return resp.json()


def kinds(body: dict) -> list[str]:
    return [item["kind"] for item in body["items"]]


class TestQuietWhenNothingIsWrong:
    async def test_a_healthy_system_reports_nothing(self, client, db, admin):
        await paid_order(client, db)
        body = await attention(client)
        assert body == {"count": 0, "items": []}


class TestAFailedRenderIsListed:
    async def test_it_shows_up_with_what_broke(self, client, db, admin,
                                               monkeypatch):
        break_the_render(monkeypatch, "cover artwork is 3 pixels wide")
        order = await paid_order(client, db)

        body = await attention(client)
        assert kinds(body) == ["render_failed"]
        item = body["items"][0]
        assert item["human_ref"] == order.human_ref
        assert "3 pixels wide" in (item["detail"] or "")
        assert item["action"], "an item with no suggested action is a puzzle"

    async def test_retrying_it_clears_the_entry(self, client, db, admin,
                                                monkeypatch):
        break_the_render(monkeypatch, "nope")
        order = await paid_order(client, db)
        assert (await attention(client))["count"] == 1

        # The operator's retry button, with a render that now works.
        monkeypatch.undo()
        resp = await client.post(
            f"/api/v1/admin/orders/{order.human_ref}/status",
            json={"target": "rendering"}, headers=AUTH)
        assert resp.status_code == 200, resp.text
        from app.services.fulfillment import run_order_render
        await run_order_render(db, order.id)

        assert (await attention(client))["count"] == 0


class TestAStalledRenderIsListedBeforeTheWatchdogGetsToIt:
    async def test_a_working_render_is_not_listed(self, client, db, admin,
                                                  monkeypatch):
        order = await paid_but_unrendered(client, db, monkeypatch)
        order.status = OrderStatus.RENDERING.value
        db.add(OrderEvent(id=uuid.uuid4(), order_id=order.id,
                          from_status=OrderStatus.PAID.value,
                          to_status=OrderStatus.RENDERING.value,
                          created_at=datetime.now(UTC)))
        await db.commit()
        assert (await attention(client))["count"] == 0

    async def test_an_overdue_one_is(self, client, db, admin, monkeypatch):
        order = await paid_but_unrendered(client, db, monkeypatch)
        order.status = OrderStatus.RENDERING.value
        db.add(OrderEvent(
            id=uuid.uuid4(), order_id=order.id,
            from_status=OrderStatus.PAID.value,
            to_status=OrderStatus.RENDERING.value,
            created_at=datetime.now(UTC) - timedelta(
                seconds=get_settings().render_stall_after_s + 60)))
        await db.commit()

        body = await attention(client)
        assert kinds(body) == ["render_stalled"]
        assert body["items"][0]["human_ref"] == order.human_ref


class TestTheHoleTelegramCannotReport:
    async def test_an_abandoned_message_is_listed(self, client, db, admin):
        """The case the whole module exists for. The order is `rendered` and
        looks perfect; the printer has heard nothing."""
        order = await paid_order(client, db)
        message = (await db.execute(
            select(OutboxMessage).where(
                OutboxMessage.topic == outbox.TOPIC_ORDER_RENDERED)
        )).scalars().first()
        message.status = OutboxStatus.FAILED.value
        message.last_error = "telegram sendMessage failed: 401 unauthorized"
        await db.commit()

        body = await attention(client)
        assert kinds(body) == ["undelivered"]
        item = body["items"][0]
        assert item["human_ref"] == order.human_ref
        assert "401" in (item["detail"] or "")

    async def test_it_says_what_that_means_not_just_the_topic(self, client, db,
                                                             admin):
        """"order.rendered" reads like good news. The operator needs to know
        the printer never got the files."""
        await paid_order(client, db)
        message = (await db.execute(
            select(OutboxMessage).where(
                OutboxMessage.topic == outbox.TOPIC_ORDER_RENDERED)
        )).scalars().first()
        message.status = OutboxStatus.FAILED.value
        await db.commit()

        summary = (await attention(client))["items"][0]["summary"]
        assert "printer" in summary and "never" in summary

    async def test_a_message_still_retrying_is_not_listed(self, client, db,
                                                          admin):
        """Pending with attempts left is the system working, not a problem —
        listing it would train the operator to ignore this screen."""
        await paid_order(client, db)
        message = (await db.execute(
            select(OutboxMessage).where(
                OutboxMessage.topic == outbox.TOPIC_ORDER_RENDERED)
        )).scalars().first()
        message.status = OutboxStatus.PENDING.value
        message.attempts = 5
        await db.commit()

        assert (await attention(client))["count"] == 0


class TestTheLockAppliesHere:
    async def test_it_needs_the_admin_token(self, client, admin):
        """This endpoint lists customer names and order references."""
        assert (await client.get("/api/v1/admin/attention")).status_code == 404

    async def test_it_carries_no_more_pii_than_it_needs(self, client, db,
                                                        admin, monkeypatch):
        """A name to recognise the order by; not the address or the phone.
        Those are one click away in the order detail."""
        break_the_render(monkeypatch, "nope")
        await paid_order(client, db)
        blob = str(await attention(client)).lower()
        for leaked in ("+998", "chilonzor", "example.com"):
            assert leaked not in blob, f"{leaked!r} leaked into the list"


class TestOrderingIsUseful:
    async def test_the_oldest_problem_comes_first(self, client, db, admin,
                                                  monkeypatch):
        break_the_render(monkeypatch, "nope")
        first = await paid_order(client, db)
        second = await paid_order(client, db)

        # Make the first genuinely older than the second.
        older = datetime.now(UTC) - timedelta(hours=3)
        row = (await db.execute(
            select(Order).where(Order.id == first.id))).scalar_one()
        row.created_at = older
        await db.commit()

        refs = [i["human_ref"] for i in (await attention(client))["items"]]
        assert refs == [first.human_ref, second.human_ref], refs
