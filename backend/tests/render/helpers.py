"""Deterministic fixtures for render tests: reproducible photos and books."""
import io
import uuid
from datetime import UTC, datetime, timedelta

import anyio
from PIL import Image
from sqlalchemy import select

from app import storage
from app.models.book import Book
from app.models.photo import Photo, PhotoStatus
from app.schemas.layout import LayoutDoc

T0 = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)


def fixture_photo_bytes(w: int, h: int, seed: int) -> bytes:
    """Deterministic gradient image — no randomness, stable across runs."""
    base = Image.linear_gradient("L")
    r = base.resize((w, h))
    g = base.transpose(Image.ROTATE_90).resize((w, h))
    b = Image.new("L", (w, h), (seed * 37) % 256)
    img = Image.merge("RGB", (r, g, b))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=90)
    return out.getvalue()


def solid_jpeg(w: int, h: int, color: tuple[int, int, int]) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), color).save(out, format="JPEG", quality=90)
    return out.getvalue()


def full_bleed_page(index: int, photo_id: str, texts: list | None = None) -> dict:
    return {
        "index": index,
        "placements": [{
            "photo_id": photo_id,
            "x_mm": -3.0, "y_mm": -3.0, "w_mm": 154.0, "h_mm": 216.0,
            "rotation": 0, "fit": "cover",
        }],
        "texts": texts or [],
    }


async def seed_rendered_book(db, client, page_count: int,
                             photo_pixels: tuple[int, int] = (1600, 1100),
                             texts_on_first_page: list | None = None) -> str:
    """Create a book whose every page holds a distinct ready photo backed by a
    real (deterministic) storage object; returns book_id."""
    resp = await client.post("/api/v1/books", json={"page_count": page_count})
    book_id = resp.json()["book_id"]

    pages = []
    for i in range(page_count):
        pid = uuid.uuid4()
        key = f"books/{book_id}/orig/{pid}"
        data = fixture_photo_bytes(*photo_pixels, seed=i)
        await anyio.to_thread.run_sync(storage.put_bytes, key, data, "image/jpeg")
        db.add(Photo(
            id=pid, book_id=uuid.UUID(book_id), status=PhotoStatus.READY.value,
            original_key=key, mime_original="image/jpeg", bytes_original=len(data),
            orig_width=photo_pixels[0], orig_height=photo_pixels[1],
            taken_at=T0 + timedelta(hours=i), uploaded_at=T0 + timedelta(seconds=i),
            sha256=f"seed{i:04d}",
        ))
        pages.append(full_bleed_page(
            i, str(pid), texts_on_first_page if i == 0 else None
        ))

    book = (await db.execute(
        select(Book).where(Book.id == uuid.UUID(book_id))
    )).scalar_one()
    book.layout = LayoutDoc.model_validate(
        {"version": 1, "cover": {}, "pages": pages}
    ).model_dump()
    book.layout_version += 1
    await db.commit()
    return book_id
