"""The public status page exposes print-PDF links ONLY in dev environments."""
import uuid
from datetime import UTC, datetime

from app.config import get_settings
from app.models.order import Order
from app.models.payment import PdfArtifact
from app.services.orders import public_status


async def seed_rendered_order(client, db) -> str:
    book = (await client.post("/api/v1/books", json={"page_count": 16})).json()
    now = datetime.now(UTC)
    order = Order(book_id=uuid.UUID(book["book_id"]), human_ref="UB-GATE1",
                  customer_name="A", customer_phone="+998900000000",
                  customer_address="T", amount_minor=100, status="rendered",
                  preview_confirmed_at=now, created_at=now)
    db.add(order)
    await db.flush()
    db.add(PdfArtifact(order_id=order.id, kind="interior", storage_key="k1",
                       sha256="x", size_bytes=1, page_count=16, render_ms=1, created_at=now))
    await db.commit()
    return "UB-GATE1"


async def test_dev_env_exposes_urls(client, db, s3):
    ref = await seed_rendered_order(client, db)
    status = await public_status(db, ref, "+998900000000")
    assert "interior" in status["artifact_urls"]


async def test_prod_env_hides_urls(client, db, s3, monkeypatch):
    ref = await seed_rendered_order(client, db)
    monkeypatch.setenv("ENV", "prod")
    get_settings.cache_clear()
    try:
        status = await public_status(db, ref, "+998900000000")
    finally:
        get_settings.cache_clear()
    assert "artifact_urls" not in status
