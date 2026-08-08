"""The public status payload carries the transfer card ONLY while the order
is awaiting payment, and only when a card is configured."""
import uuid
from datetime import UTC, datetime

from app.config import get_settings
from app.models.order import Order
from app.services.orders import public_status

PHONE = "+998901112233"


async def seed_order(client, db, ref: str, status: str) -> str:
    book = (await client.post("/api/v1/books", json={"page_count": 16})).json()
    now = datetime.now(UTC)
    db.add(Order(book_id=uuid.UUID(book["book_id"]), human_ref=ref,
                 customer_name="A", customer_phone=PHONE, customer_address="T",
                 amount_minor=100, status=status,
                 preview_confirmed_at=now, created_at=now))
    await db.commit()
    return ref


def _configure(monkeypatch):
    monkeypatch.setenv("PAY_CARD_NUMBER", "8600 1234 5678 9012")
    monkeypatch.setenv("PAY_CARD_HOLDER", "FURQATBEK T")
    get_settings.cache_clear()


async def test_pending_order_shows_card(client, db, monkeypatch):
    ref = await seed_order(client, db, "UB-CARD1", "pending_payment")
    _configure(monkeypatch)
    try:
        status = await public_status(db, ref, PHONE)
    finally:
        get_settings.cache_clear()
    assert status["pay_card"] == {"number": "8600 1234 5678 9012",
                                  "holder": "FURQATBEK T"}


async def test_paid_order_hides_card(client, db, monkeypatch):
    ref = await seed_order(client, db, "UB-CARD2", "paid")
    _configure(monkeypatch)
    try:
        status = await public_status(db, ref, PHONE)
    finally:
        get_settings.cache_clear()
    assert "pay_card" not in status


async def test_unconfigured_shows_no_card(client, db):
    ref = await seed_order(client, db, "UB-CARD3", "pending_payment")
    status = await public_status(db, ref, PHONE)
    assert "pay_card" not in status
