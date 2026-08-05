"""Milestone 6 render tests (spec Part 9.3): correctness, determinism,
golden raster, failure handling, resource discipline."""
import io
import threading
import time
import uuid
from pathlib import Path

import anyio
import fitz  # PyMuPDF
import pytest
from PIL import Image
from pypdf import PdfReader
from sqlalchemy import select

from app import storage
from app.models.book import Book
from app.models.photo import Photo, PhotoStatus
from app.render.color import convert_pdf_to_cmyk, ghostscript_available
from app.render.compose import RenderError
from app.services.render import render_interior
from tests.render.helpers import (
    T0,
    full_bleed_page,
    seed_rendered_book,
    solid_jpeg,
)

MM_TO_PT = 72 / 25.4
GOLDEN_DIR = Path(__file__).parent / "golden"

TEXT = [{
    "id": "t1", "x_mm": 12.0, "y_mm": 180.0, "w_mm": 124.0, "h_mm": 18.0,
    "content": "Amalfi coast", "font": "Inter", "size_pt": 11,
    "align": "left", "color": "#1a1a1a",
}]


async def fetch_pdf(book_id: str) -> bytes:
    return await anyio.to_thread.run_sync(
        storage.get_bytes, f"books/{book_id}/render/interior.pdf"
    )


class TestCorrectness:
    async def test_16_pages_at_exact_size(self, client, db):
        book_id = await seed_rendered_book(db, client, 16, texts_on_first_page=TEXT)
        meta = await render_interior(db, uuid.UUID(book_id))
        assert meta["page_count"] == 16

        reader = PdfReader(io.BytesIO(await fetch_pdf(book_id)))
        assert len(reader.pages) == 16
        for page in reader.pages:
            w_mm = float(page.mediabox.width) / MM_TO_PT
            h_mm = float(page.mediabox.height) / MM_TO_PT
            assert abs(w_mm - 154.0) < 0.1
            assert abs(h_mm - 216.0) < 0.1

    async def test_renders_from_originals_not_display(self, client, db):
        """Original is red, display derivative is blue. The printed page must
        be red — and the page raster must out-resolve the 2000px display cap."""
        resp = await client.post("/api/v1/books", json={"page_count": 16})
        book_id = resp.json()["book_id"]
        pid = uuid.uuid4()
        orig_key = f"books/{book_id}/orig/{pid}"
        display_key = f"books/{book_id}/display/{pid}.jpg"
        await anyio.to_thread.run_sync(
            storage.put_bytes, orig_key, solid_jpeg(3000, 2000, (200, 20, 20)),
            "image/jpeg")
        await anyio.to_thread.run_sync(
            storage.put_bytes, display_key, solid_jpeg(2000, 1333, (20, 20, 200)),
            "image/jpeg")
        db.add(Photo(id=pid, book_id=uuid.UUID(book_id),
                     status=PhotoStatus.READY.value, original_key=orig_key,
                     display_key=display_key, mime_original="image/jpeg",
                     bytes_original=1, orig_width=3000, orig_height=2000,
                     uploaded_at=T0, sha256="x"))
        book = (await db.execute(
            select(Book).where(Book.id == uuid.UUID(book_id)))).scalar_one()
        book.layout = {**book.layout,
                       "pages": [full_bleed_page(0, str(pid))]
                       + book.layout["pages"][1:]}
        await db.commit()
        with pytest.raises(RenderError):
            # pages 1..15 are empty — preflight refuses; fill them too
            await render_interior(db, uuid.UUID(book_id))

        book.layout = {**book.layout,
                       "pages": [full_bleed_page(i, str(pid)) for i in range(16)]}
        await db.commit()
        await render_interior(db, uuid.UUID(book_id))

        doc = fitz.open(stream=await fetch_pdf(book_id), filetype="pdf")
        images = doc[0].get_images(full=True)
        assert images, "page embeds an image"
        # The page raster out-resolves the display derivative's long edge.
        assert max(images[0][2], images[0][3]) > 2000
        pix = doc[0].get_pixmap(dpi=36)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        r, _g, b = img.getpixel((pix.width // 2, pix.height // 2))
        assert r > 150 and b < 100  # red original, not blue display

    async def test_text_rendered_inside_safe_area(self, client, db):
        book_id = await seed_rendered_book(db, client, 16, texts_on_first_page=TEXT)
        await render_interior(db, uuid.UUID(book_id))

        doc = fitz.open(stream=await fetch_pdf(book_id), filetype="pdf")
        words = doc[0].get_text("words")
        assert {w[4] for w in words} == {"Amalfi", "coast"}
        # Safe area in page points (bleed origin): x in [8,146]mm, y in [8,208]mm
        for x0, y0, x1, y1, *_ in words:
            assert x0 >= 8.0 * MM_TO_PT - 1
            assert x1 <= 146.0 * MM_TO_PT + 1
            assert y0 >= 8.0 * MM_TO_PT - 1
            assert y1 <= 208.0 * MM_TO_PT + 1


class TestDeterminism:
    async def test_byte_identical_across_runs(self, client, db):
        book_id = await seed_rendered_book(db, client, 16)
        first = await render_interior(db, uuid.UUID(book_id))
        second = await render_interior(db, uuid.UUID(book_id))
        assert first["sha256"] == second["sha256"]

    async def test_golden_page_raster(self, client, db):
        """Perceptual golden: catches silent layout drift invisible to unit
        tests. If this fails, LOOK AT THE IMAGE before updating the golden."""
        book_id = await seed_rendered_book(db, client, 16, texts_on_first_page=TEXT)
        await render_interior(db, uuid.UUID(book_id))
        doc = fitz.open(stream=await fetch_pdf(book_id), filetype="pdf")
        pix = doc[0].get_pixmap(dpi=72)
        rendered = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

        golden_path = GOLDEN_DIR / "interior_page1.png"
        if not golden_path.exists():
            GOLDEN_DIR.mkdir(exist_ok=True)
            rendered.save(golden_path)
            pytest.skip("golden reference created — commit it and re-run")

        golden = Image.open(golden_path).convert("RGB")
        assert golden.size == rendered.size
        diff_total = sum(
            abs(a - b)
            for a, b in zip(golden.tobytes(), rendered.tobytes(), strict=True)
        )
        mean_diff = diff_total / (golden.width * golden.height * 3)
        assert mean_diff < 8.0, f"perceptual drift: mean channel diff {mean_diff:.2f}"


class TestFailureHandling:
    async def test_empty_pages_refused(self, client, db):
        resp = await client.post("/api/v1/books", json={"page_count": 16})
        book_id = resp.json()["book_id"]
        with pytest.raises(RenderError, match="without a placement"):
            await render_interior(db, uuid.UUID(book_id))

    async def test_missing_storage_object_fails_cleanly(self, client, db):
        book_id = await seed_rendered_book(db, client, 16)
        # Delete one original out from under the render.
        book = (await db.execute(
            select(Book).where(Book.id == uuid.UUID(book_id)))).scalar_one()
        victim = book.layout["pages"][3]["placements"][0]["photo_id"]
        photo = (await db.execute(
            select(Photo).where(Photo.id == uuid.UUID(victim)))).scalar_one()
        await anyio.to_thread.run_sync(storage.delete_keys, [photo.original_key])
        with pytest.raises(Exception):  # noqa: B017 — boto error or RenderError both acceptable
            await render_interior(db, uuid.UUID(book_id))

    async def test_placement_of_unavailable_photo_refused(self, client, db):
        book_id = await seed_rendered_book(db, client, 16)
        book = (await db.execute(
            select(Book).where(Book.id == uuid.UUID(book_id)))).scalar_one()
        ghost = str(uuid.uuid4())
        pages = book.layout["pages"]
        pages[0]["placements"][0]["photo_id"] = ghost
        book.layout = {**book.layout, "pages": pages}
        await db.commit()
        with pytest.raises(RenderError, match="unavailable photos"):
            await render_interior(db, uuid.UUID(book_id))


class TestCmyk:
    @pytest.mark.skipif(not ghostscript_available(), reason="ghostscript not installed")
    async def test_cmyk_conversion_produces_valid_pdf(self, client, db):
        book_id = await seed_rendered_book(db, client, 16)
        await render_interior(db, uuid.UUID(book_id))
        rgb_pdf = await fetch_pdf(book_id)
        cmyk_pdf = await anyio.to_thread.run_sync(convert_pdf_to_cmyk, rgb_pdf, None)
        reader = PdfReader(io.BytesIO(cmyk_pdf))
        assert len(reader.pages) == 16
        assert b"DeviceCMYK" in cmyk_pdf


class TestResources:
    async def test_96_pages_within_memory_and_time_budget(self, client, db):
        """Proves the one-page-at-a-time discipline (spec: this test is the
        reason the discipline survives refactoring). The render's own memory
        growth over the pre-render baseline must stay under 512MB — measured
        as a delta because the shared pytest process carries the allocator
        high-water of every earlier test (the broken ImageReader path added
        ~1GB of delta, which this still catches)."""
        book_id = await seed_rendered_book(db, client, 96, photo_pixels=(1200, 800))

        def rss_mb() -> float:
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) / 1024
            return 0.0

        baseline = rss_mb()
        peak = {"rss_mb": baseline}
        stop = threading.Event()

        def sample():
            while not stop.is_set():
                peak["rss_mb"] = max(peak["rss_mb"], rss_mb())
                time.sleep(0.05)

        sampler = threading.Thread(target=sample, daemon=True)
        sampler.start()
        started = time.monotonic()
        meta = await render_interior(db, uuid.UUID(book_id))
        elapsed = time.monotonic() - started
        stop.set()
        sampler.join(timeout=2)

        assert meta["page_count"] == 96
        assert elapsed < 180, f"96-page render took {elapsed:.0f}s"
        delta = peak["rss_mb"] - baseline
        assert delta < 512, (f"render grew RSS by {delta:.0f}MB "
                             f"(baseline {baseline:.0f}MB, "
                             f"peak {peak['rss_mb']:.0f}MB)")
