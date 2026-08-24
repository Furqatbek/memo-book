"""The full journey, one test (spec Part 9.5) — plus the unhappy path."""

import io

import anyio
from pypdf import PdfReader
from sqlalchemy import select

from app import storage
from app.models.order import Order
from app.models.outbox import OutboxMessage
from app.models.payment import PdfArtifact
from app.services import telegram as telegram_svc
from tests.api.test_photos import photo_list, upload_photo
from tests.services.test_image_processing import build_exif, heic_bytes, jpeg_bytes

MM_TO_PT = 72 / 25.4


async def test_full_journey(client, db, monkeypatch):
    telegram_sent: list[str] = []
    monkeypatch.setattr(telegram_svc, "_post_telegram", telegram_sent.append)

    # 1. Create book, tier 16
    book = (await client.post("/api/v1/books", json={"page_count": 16})).json()
    book_id = book["book_id"]
    headers = {"X-Edit-Token": book["edit_token"]}

    # 2. Upload 16 photos: mixed JPEG + HEIC + one rotated EXIF, timestamps
    #    deliberately uploaded in reverse chronological order.
    for i in range(16):
        ts = f"2026:06:{16 - i:02d} 10:00:00"  # earliest photo uploaded LAST
        if i == 3:
            data, mime = heic_bytes(datetime_str=ts), "image/heic"
        elif i == 5:
            data, mime = jpeg_bytes(400, 200, exif=build_exif(ts, orientation=6)), "image/jpeg"
        else:
            data, mime = jpeg_bytes(1200 + i, 900, exif=build_exif(ts)), "image/jpeg"
        await upload_photo(client, book, data, mime=mime)

    # 3. Ingest completed (eager): all 16 ready, the rotated one stored
    #    post-rotation.
    photos = await photo_list(client, book)
    assert [p["status"] for p in photos] == ["ready"] * 16
    rotated = photos[5]
    assert (rotated["width"], rotated["height"]) == (200, 400)

    # 4. Auto-place: chronological despite upload order (R2).
    placed = (await client.post(f"/api/v1/books/{book_id}/auto-place",
                                headers={**headers, "If-Match": "1"})).json()
    expected = [p["photo_id"] for p in sorted(photos, key=lambda p: p["taken_at"])]
    got = [page["placements"][0]["photo_id"] for page in placed["layout"]["pages"]]
    assert got == expected

    # 5. Text near the page edge is clamped on save.
    layout = placed["layout"]
    layout["pages"][0]["texts"] = [{
        "id": "t1", "x_mm": 1.0, "y_mm": 50, "w_mm": 30, "h_mm": 10,
        "content": "Registan",
    }]
    patched = (await client.patch(f"/api/v1/books/{book_id}/layout", json=layout,
                                  headers={**headers, "If-Match": "2"})).json()
    assert patched["layout"]["pages"][0]["texts"][0]["x_mm"] == 5.0

    # 6. Eligibility -> eligible.
    eligibility = (await client.get(f"/api/v1/books/{book_id}/checkout-eligibility",
                                    headers=headers)).json()
    assert eligibility == {"eligible": True, "photo_count": 16, "page_count": 16,
                           "issues": [], "suggested_tier": None}

    # 7. Preview: 16 watermarked pages.
    await client.post(f"/api/v1/books/{book_id}/preview", headers=headers)
    preview = (await client.get(f"/api/v1/books/{book_id}/preview",
                                headers=headers)).json()
    assert preview["status"] == "ready" and len(preview["page_urls"]) == 16

    customer = {"name": "Aziza Karimova", "phone": "+998901234567",
                "address": "Tashkent, Chilonzor 5", "confirmed_preview": True}

    # 8. Checkout WITHOUT confirmed_preview -> rejected.
    rejected = await client.post(f"/api/v1/books/{book_id}/checkout",
                                 json={**customer, "confirmed_preview": False},
                                 headers=headers)
    assert rejected.status_code == 422

    # 9. Checkout WITH -> locked + pending_payment.
    checkout = (await client.post(f"/api/v1/books/{book_id}/checkout",
                                  json=customer, headers=headers)).json()
    ref, amount = checkout["human_ref"], checkout["amount_minor"]
    assert checkout["order_status"] == "pending_payment"

    # 10. Layout patch after locking -> 423.
    locked_patch = await client.patch(f"/api/v1/books/{book_id}/layout",
                                      json=patched["layout"],
                                      headers={**headers, "If-Match": "3"})
    assert locked_patch.status_code == 423

    # 11. Payment webhook -> paid, render enqueued (eager: runs now).
    event = {"event_id": "e2e-1", "action": "pay", "human_ref": ref,
             "amount_minor": amount}
    sig = {"X-Dev-Signature": "dev-secret-change-me"}
    first = await client.post("/api/v1/payments/dev/webhook", json=event, headers=sig)
    assert first.status_code == 200

    # 12. The SAME webhook again -> no duplicate effects.
    second = await client.post("/api/v1/payments/dev/webhook", json=event, headers=sig)
    assert second.json()["duplicate"] is True

    # 13. Render done: interior artifact, 16 pages, correct dimensions.
    order = (await db.execute(select(Order).where(Order.human_ref == ref))).scalar_one()
    await db.refresh(order)
    assert order.status == "rendered"
    artifacts = {a.kind: a for a in (await db.execute(
        select(PdfArtifact).where(PdfArtifact.order_id == order.id))).scalars()}
    assert set(artifacts) == {"interior", "cover"}
    pdf = await anyio.to_thread.run_sync(storage.get_bytes,
                                         artifacts["interior"].storage_key)
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 16
    assert abs(float(reader.pages[0].mediabox.width) / MM_TO_PT - 154.0) < 0.1

    # 14. Outbox message exists; the Telegram payload is a URL, not the file.
    [message] = (await db.execute(select(OutboxMessage))).scalars().all()
    assert message.topic == "order.rendered"
    [text] = telegram_sent
    assert "http" in text and ref in text
    assert "%PDF" not in text

    # 15. Public status lookup by ref + phone. Dev env also hands the
    #     print-PDF links to the order screen (prod never does).
    status = (await client.get(f"/api/v1/orders/{ref}",
                               params={"phone": "998901234567"})).json()
    assert status["status"] == "rendered"
    assert status["page_count"] == 16
    assert set(status["artifact_urls"]) == {"interior", "cover"}


async def test_unhappy_path_shortfall_blocks_checkout(client, db):
    book = (await client.post("/api/v1/books", json={"page_count": 16})).json()
    headers = {"X-Edit-Token": book["edit_token"]}
    for i in range(10):
        await upload_photo(client, book, jpeg_bytes(1000 + i, 800))
    await client.post(f"/api/v1/books/{book['book_id']}/preview", headers=headers)

    resp = await client.post(
        f"/api/v1/books/{book['book_id']}/checkout",
        json={"name": "A", "phone": "+998900000000", "address": "Tashkent, X 1",
              "confirmed_preview": True},
        headers=headers,
    )
    assert resp.status_code == 409
    error = resp.json()["error"]
    assert error["code"] == "PHOTOS_INSUFFICIENT"
    assert error["details"] == {"have": 10, "empty_pages": 16,
                                "unplaced_photos": 10, "shortfall": 6}
    assert (await db.execute(select(Order))).scalar_one_or_none() is None
