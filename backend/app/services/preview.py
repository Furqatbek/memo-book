"""Preview orchestration: request -> job -> per-page watermarked JPEGs in
storage under books/{id}/preview/. Status and the source layout version live
on the Book row so staleness is detectable."""
import uuid

import anyio
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import storage
from app.models.book import Book
from app.models.photo import Photo
from app.render.preview import render_preview_cover, render_preview_page
from app.services.books import get_book_authed
from app.services.placement import USABLE_STATUSES

log = structlog.get_logger()

PREVIEW_PROCESSING = "processing"
PREVIEW_READY = "ready"
PREVIEW_FAILED = "failed"


def _page_key(book_id: uuid.UUID, index: int) -> str:
    return f"books/{book_id}/preview/page-{index}.jpg"


def _cover_key(book_id: uuid.UUID) -> str:
    return f"books/{book_id}/preview/cover.jpg"


def _back_key(book_id: uuid.UUID) -> str:
    return f"books/{book_id}/preview/back.jpg"


def _back_as_page(cover: dict) -> dict | None:
    """The back panel expressed as a page, or None when it is blank (A91).

    It is 148x210 with a slot grid and placements — an interior page in
    every respect the preview cares about — so it renders through the same
    function rather than a near-copy that could drift from it.
    """
    back = (cover.get("back") or {})
    if not back.get("placements"):
        return None
    return {
        "index": -1,
        "bg_color": cover.get("bg_color", "#ffffff"),
        "layout": back.get("layout", "full"),
        "placements": back["placements"],
        "texts": [],
        "stickers": [],
    }


async def request_preview(session: AsyncSession, book_id: uuid.UUID,
                          edit_token: str) -> Book:
    book = await get_book_authed(session, book_id, edit_token)
    book.preview_status = PREVIEW_PROCESSING
    await session.commit()
    return book


async def run_preview(session: AsyncSession, book_id: uuid.UUID) -> None:
    """The preview job body. Renders every page — including empty ones — at
    72dpi with the watermark. Failures land in preview_status=failed."""
    book = (await session.execute(
        select(Book).where(Book.id == book_id)
    )).scalar_one()
    photos = {
        str(p.id): p
        for p in (await session.execute(
            select(Photo).where(Photo.book_id == book_id,
                                Photo.status.in_(USABLE_STATUSES))
        )).scalars()
    }
    layout_version = book.layout_version

    try:
        cover = book.layout.get("cover", {})
        cover_photo = photos.get(cover.get("photo_id") or "")
        cover_bytes = None
        if cover_photo is not None:
            cover_bytes = await anyio.to_thread.run_sync(
                storage.get_bytes, cover_photo.original_key
            )
        from app.services.cover_designs import design_artwork_bytes

        artwork = await design_artwork_bytes(session, cover.get("design_id"))
        cover_jpeg = await anyio.to_thread.run_sync(
            render_preview_cover, cover, cover_bytes, artwork
        )
        del artwork
        del cover_bytes
        await anyio.to_thread.run_sync(
            storage.put_bytes, _cover_key(book_id), cover_jpeg, "image/jpeg"
        )
        del cover_jpeg

        # The back panel, when the customer has put something there. No tile
        # when it is blank: a preview of a flat rectangle tells nobody
        # anything, and its absence is what `back_url: null` means.
        back_page = _back_as_page(cover)
        if back_page is not None:
            back_bytes: dict[str, bytes] = {}
            for placement in back_page["placements"]:
                photo = photos.get(placement["photo_id"])
                if photo is not None:
                    back_bytes[placement["photo_id"]] = await anyio.to_thread.run_sync(
                        storage.get_bytes, photo.original_key
                    )
            back_jpeg = await anyio.to_thread.run_sync(
                render_preview_page, back_page, back_bytes
            )
            del back_bytes
            await anyio.to_thread.run_sync(
                storage.put_bytes, _back_key(book_id), back_jpeg, "image/jpeg"
            )
            del back_jpeg

        for page in book.layout["pages"]:
            photo_bytes: dict[str, bytes] = {}
            for placement in page.get("placements", []):
                photo = photos.get(placement["photo_id"])
                if photo is not None:
                    photo_bytes[placement["photo_id"]] = await anyio.to_thread.run_sync(
                        storage.get_bytes, photo.original_key
                    )
            jpeg = await anyio.to_thread.run_sync(
                render_preview_page, page, photo_bytes
            )
            del photo_bytes
            await anyio.to_thread.run_sync(
                storage.put_bytes, _page_key(book_id, page["index"]), jpeg, "image/jpeg"
            )
            del jpeg

        book.preview_status = PREVIEW_READY
        book.preview_layout_version = layout_version
        await session.commit()
        log.info("preview.ready", book_id=str(book_id), layout_version=layout_version)
    except Exception as exc:  # noqa: BLE001 — job boundary: report, never raise
        book.preview_status = PREVIEW_FAILED
        await session.commit()
        log.warning("preview.failed", book_id=str(book_id), error=str(exc))


async def preview_state(session: AsyncSession, book_id: uuid.UUID,
                        edit_token: str) -> dict:
    book = await get_book_authed(session, book_id, edit_token)
    status = book.preview_status or "none"
    stale = (
        status == PREVIEW_READY
        and book.preview_layout_version != book.layout_version
    )
    page_urls: list[str] = []
    cover_url: str | None = None
    back_url: str | None = None
    if status == PREVIEW_READY:
        page_urls = [
            storage.presign_get(_page_key(book_id, i))
            for i in range(book.page_count)
        ]
        if storage.object_exists(_cover_key(book_id)):   # previews from before
            cover_url = storage.presign_get(_cover_key(book_id))
        # Absent for a blank back, and for every preview rendered before the
        # back panel could hold anything.
        if storage.object_exists(_back_key(book_id)):
            back_url = storage.presign_get(_back_key(book_id))
    return {
        "status": status,
        "cover_url": cover_url,
        "back_url": back_url,
        "page_urls": page_urls,
        "stale": stale,
        "page_count": book.page_count,
        "layout_version": book.layout_version,
    }
