"""Render orchestration: load a book, preflight it, stream pages through the
PDF builder, store the artifact. Triggering stays payment-only (R8) — this
service is called by the order pipeline (M8/M9), never by a user-facing
endpoint."""
import hashlib
import time
import uuid

import anyio
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import storage
from app.config import get_settings
from app.models.book import Book
from app.models.photo import Photo
from app.render.color import convert_pdf_to_cmyk
from app.render.compose import RenderError
from app.render.interior import build_pdf
from app.services.placement import USABLE_STATUSES

log = structlog.get_logger()


async def _load_book_and_photos(session: AsyncSession,
                                book_id: uuid.UUID) -> tuple[Book, dict[str, Photo]]:
    book = (await session.execute(
        select(Book).where(Book.id == book_id)
    )).scalar_one_or_none()
    if book is None:
        raise RenderError("book not found")
    photos = (await session.execute(
        select(Photo).where(Photo.book_id == book_id,
                            Photo.status.in_(USABLE_STATUSES))
    )).scalars()
    return book, {str(p.id): p for p in photos}


def preflight(book: Book, photos: dict[str, Photo]) -> None:
    """Refuse to render anything that would print wrong. Blank pages are a
    guaranteed refund; a missing photo is a broken book."""
    pages = book.layout.get("pages", [])
    if len(pages) != book.page_count:
        raise RenderError(
            f"layout has {len(pages)} pages but the tier is {book.page_count}"
        )
    empty = [p["index"] for p in pages if not p.get("placements")]
    if empty:
        raise RenderError(f"pages without a placement: {empty}")
    missing = [
        pl["photo_id"]
        for p in pages for pl in p.get("placements", [])
        if pl["photo_id"] not in photos
    ]
    if missing:
        raise RenderError(f"placements reference unavailable photos: {missing}")


async def render_interior(session: AsyncSession, book_id: uuid.UUID) -> dict:
    """Render the print interior from ORIGINAL photo files, one page at a
    time, and upload it. Returns artifact metadata. Idempotent: re-rendering
    overwrites the same storage key with identical bytes (RGB mode)."""
    book, photos = await _load_book_and_photos(session, book_id)
    preflight(book, photos)

    started = time.monotonic()

    def fetch_original(photo_id: str) -> bytes:
        return storage.get_bytes(photos[photo_id].original_key)

    def build() -> bytes:
        return build_pdf(book.layout["pages"], fetch_original,
                         cache_tag=str(book_id))

    pdf_bytes = await anyio.to_thread.run_sync(build)

    settings = get_settings()
    color_mode = settings.render_color_mode
    if color_mode == "cmyk":
        pdf_bytes = await anyio.to_thread.run_sync(
            convert_pdf_to_cmyk, pdf_bytes, settings.icc_profile_path or None
        )

    render_ms = int((time.monotonic() - started) * 1000)
    key = f"books/{book_id}/render/interior.pdf"
    await anyio.to_thread.run_sync(storage.put_bytes, key, pdf_bytes, "application/pdf")

    meta = {
        "storage_key": key,
        "kind": "interior",
        "page_count": book.page_count,
        "bytes": len(pdf_bytes),
        "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "render_ms": render_ms,
        "color_mode": color_mode,
    }
    log.info("render.interior_done", book_id=str(book_id), **meta)
    return meta


async def render_cover(session: AsyncSession, book_id: uuid.UUID) -> dict:
    """Render the hardcover wrap as its own artifact (spec Part 7 step 7)."""
    from app.render.cover import build_cover_pdf

    book, photos = await _load_book_and_photos(session, book_id)
    cover = book.layout.get("cover", {}) or {}
    photo_id = cover.get("photo_id")
    photo_bytes = None
    if photo_id:
        photo = photos.get(photo_id)
        if photo is None:
            raise RenderError(f"cover references unavailable photo {photo_id}")
        photo_bytes = await anyio.to_thread.run_sync(
            storage.get_bytes, photo.original_key
        )

    started = time.monotonic()

    def build() -> bytes:
        return build_cover_pdf(cover, book.page_count, photo_bytes,
                               cache_tag=f"{book_id}-cover")

    pdf_bytes = await anyio.to_thread.run_sync(build)

    settings = get_settings()
    if settings.render_color_mode == "cmyk":
        pdf_bytes = await anyio.to_thread.run_sync(
            convert_pdf_to_cmyk, pdf_bytes, settings.icc_profile_path or None
        )

    render_ms = int((time.monotonic() - started) * 1000)
    key = f"books/{book_id}/render/cover.pdf"
    await anyio.to_thread.run_sync(storage.put_bytes, key, pdf_bytes, "application/pdf")
    meta = {
        "storage_key": key,
        "kind": "cover",
        "page_count": 1,
        "bytes": len(pdf_bytes),
        "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "render_ms": render_ms,
        "color_mode": settings.render_color_mode,
    }
    log.info("render.cover_done", book_id=str(book_id), **meta)
    return meta
