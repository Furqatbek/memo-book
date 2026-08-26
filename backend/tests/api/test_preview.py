"""Milestone 7: 72dpi watermarked preview — the confirmation gate's evidence."""
import io
import uuid

import anyio
from PIL import Image
from sqlalchemy import select

from app import storage
from app.models.book import Book
from tests.api.test_books import auth, make_book
from tests.render.helpers import seed_rendered_book

# 154mm/216mm canvas at 72dpi
EXPECTED_W = round(1819 * 72 / 300)  # 437
EXPECTED_H = round(2551 * 72 / 300)  # 612


async def request_and_get(client, book_id, headers):
    resp = await client.post(f"/api/v1/books/{book_id}/preview", headers=headers)
    assert resp.status_code == 202
    assert resp.json() == {"status": "processing"}
    state = await client.get(f"/api/v1/books/{book_id}/preview", headers=headers)
    assert state.status_code == 200
    return state.json()


async def fetch_page(book_id: str, index: int) -> Image.Image:
    data = await anyio.to_thread.run_sync(
        storage.get_bytes, f"books/{book_id}/preview/page-{index}.jpg"
    )
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


class TestPreview:
    async def test_full_book_preview_ready_with_urls(self, client, db):
        book_id = await seed_rendered_book(db, client, 16)
        book_row = (await db.execute(
            select(Book).where(Book.id == uuid.UUID(book_id)))).scalar_one()
        headers = {"X-Edit-Token": book_row.edit_token}

        state = await request_and_get(client, book_id, headers)
        assert state["status"] == "ready"
        assert state["stale"] is False
        assert len(state["page_urls"]) == 16
        assert all(url.startswith("http") for url in state["page_urls"])

    async def test_pages_are_72dpi_and_watermarked(self, client, db):
        book = await make_book(client, 16)  # empty book: white pages
        state = await request_and_get(client, book["book_id"], auth(book))
        assert state["status"] == "ready"

        img = await fetch_page(book["book_id"], 0)
        assert abs(img.width - EXPECTED_W) <= 2
        assert abs(img.height - EXPECTED_H) <= 2
        # A blank page would be pure white; the watermark must show.
        extrema = img.convert("L").getextrema()
        assert extrema[0] < 240, "watermark not visible on blank page"

    async def test_every_page_rendered_including_empty(self, client, db):
        book = await make_book(client, 16)
        await request_and_get(client, book["book_id"], auth(book))
        for i in range(16):
            img = await fetch_page(book["book_id"], i)
            assert img.width > 0

    async def test_preview_shows_text(self, client, db):
        book = await make_book(client, 16)
        layout = book["layout"]
        layout["pages"][0]["texts"] = [{
            "id": "t1", "x_mm": 12, "y_mm": 100, "w_mm": 124, "h_mm": 18,
            "content": "SAMARKAND", "size_pt": 24, "color": "#000000",
        }]
        patched = await client.patch(f"/api/v1/books/{book['book_id']}/layout",
                                     json=layout,
                                     headers={**auth(book), "If-Match": "1"})
        assert patched.status_code == 200

        await request_and_get(client, book["book_id"], auth(book))
        with_text = await fetch_page(book["book_id"], 0)
        without_text = await fetch_page(book["book_id"], 1)
        # The text band should make page 0 darker than the blank page 1.
        from app.domain.geometry import BLEED_MM, PX_PER_MM
        y_px = int((100 + BLEED_MM) * PX_PER_MM * 72 / 300)
        band_with = with_text.convert("L").crop((0, y_px, with_text.width, y_px + 30))
        band_without = without_text.convert("L").crop((0, y_px, with_text.width, y_px + 30))
        hist_with = sum(band_with.histogram()[:128])
        hist_without = sum(band_without.histogram()[:128])
        assert hist_with > hist_without

    async def test_stale_after_layout_change(self, client, db):
        book = await make_book(client, 16)
        state = await request_and_get(client, book["book_id"], auth(book))
        assert state["stale"] is False

        layout = book["layout"]
        layout["pages"][0]["texts"] = [{
            "id": "t1", "x_mm": 12, "y_mm": 100, "w_mm": 50, "h_mm": 10,
            "content": "changed",
        }]
        await client.patch(f"/api/v1/books/{book['book_id']}/layout", json=layout,
                           headers={**auth(book), "If-Match": "1"})
        state = (await client.get(f"/api/v1/books/{book['book_id']}/preview",
                                  headers=auth(book))).json()
        assert state["status"] == "ready"
        assert state["stale"] is True

    async def test_no_preview_yet(self, client):
        book = await make_book(client, 16)
        state = (await client.get(f"/api/v1/books/{book['book_id']}/preview",
                                  headers=auth(book))).json()
        # Whole-dict equality on purpose: this is the shape the editor codes
        # against, and a field appearing or vanishing should be a decision
        # somebody made, not a diff nobody noticed. `back_url` is null until
        # the customer puts something on the back panel (A91).
        assert state == {"status": "none", "cover_url": None, "back_url": None,
                         "page_urls": [], "stale": False, "page_count": 16,
                         "layout_version": 1}

    async def test_wrong_token_404(self, client):
        book = await make_book(client, 16)
        resp = await client.post(f"/api/v1/books/{book['book_id']}/preview",
                                 headers={"X-Edit-Token": "wrong"})
        assert resp.status_code == 404

    async def test_preview_keys_are_separate_from_print_keys(self, client, db):
        """The preview must never be mistakable for the print file."""
        book_id = await seed_rendered_book(db, client, 16)
        book_row = (await db.execute(
            select(Book).where(Book.id == uuid.UUID(book_id)))).scalar_one()
        await request_and_get(client, book_id, {"X-Edit-Token": book_row.edit_token})
        exists = await anyio.to_thread.run_sync(
            storage.object_exists, f"books/{book_id}/render/interior.pdf"
        )
        assert not exists  # preview wrote nothing into the render namespace


class TestCoverPreview:
    async def test_cover_url_present_and_watermarked(self, client, db):
        book = (await client.post("/api/v1/books", json={"page_count": 16})).json()
        headers = {"X-Edit-Token": book["edit_token"]}
        layout = book["layout"]
        layout["cover"]["title"] = "Sayohat"
        layout["cover"]["bg_color"] = "#204060"
        await client.patch(f"/api/v1/books/{book['book_id']}/layout", json=layout,
                           headers={**headers, "If-Match": "1"})
        await client.post(f"/api/v1/books/{book['book_id']}/preview", headers=headers)
        state = (await client.get(f"/api/v1/books/{book['book_id']}/preview",
                                  headers=headers)).json()
        assert state["status"] == "ready"
        assert state["cover_url"]

        import io

        import httpx
        from PIL import Image

        from app import storage
        key = f"books/{book['book_id']}/preview/cover.jpg"
        img = Image.open(io.BytesIO(storage.get_bytes(key)))
        assert img.format == "JPEG"
        # background colour shows in a corner (behind the watermark tint)
        r, _g, b = img.convert("RGB").getpixel((3, 3))
        assert b > r  # blue-ish background, not white
        assert httpx.URL(state["cover_url"])  # presigned, parseable
