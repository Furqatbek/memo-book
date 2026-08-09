"""AUTO_CONFIRM_ORDERS: the trust-first card pilot — checkout confirms the
order immediately through the full webhook machinery; the default (off)
keeps the classic wait-for-payment flow."""
from sqlalchemy import select

from app.config import get_settings
from app.models.order import Order
from app.models.outbox import OutboxMessage
from tests.api.test_checkout import do_checkout, ready_book


def _enable(monkeypatch):
    monkeypatch.setenv("AUTO_CONFIRM_ORDERS", "true")
    get_settings.cache_clear()


async def test_checkout_confirms_and_renders_immediately(client, db, s3,
                                                         monkeypatch):
    book_id, headers = await ready_book(client, db)
    _enable(monkeypatch)
    try:
        resp = await do_checkout(client, book_id, headers)
    finally:
        get_settings.cache_clear()
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # TASK_EAGER in tests: render ran inline, so the response is already past
    # paid. The printer notification is queued in the same flow.
    assert body["order_status"] == "rendered"
    order = (await db.execute(
        select(Order).where(Order.human_ref == body["human_ref"])
    )).scalar_one()
    assert order.provider == "dev"
    assert order.provider_txn_id == f"auto-{order.id}"
    messages = (await db.execute(select(OutboxMessage))).scalars().all()
    assert [m.topic for m in messages] == ["order.rendered"]


async def test_default_off_keeps_pending_payment(client, db, s3):
    book_id, headers = await ready_book(client, db)
    resp = await do_checkout(client, book_id, headers)
    assert resp.status_code == 201
    assert resp.json()["order_status"] == "pending_payment"
