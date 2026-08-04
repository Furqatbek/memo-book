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
from app.render.preview import render_preview_page
from app.services.books import get_book_authed
from app.services.placement import USABLE_STATUSES

log = structlog.get_logger()

PREVIEW_PROCESSING = "processing"
PREVIEW_READY = "ready"
PREVIEW_FAILED = "failed"


def _page_key(book_id: uuid.UUID, index: int) -> str:
    return f"books/{book_id}/preview/page-{index}.jpg"


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
    if status == PREVIEW_READY:
        page_urls = [
            storage.presign_get(_page_key(book_id, i))
            for i in range(book.page_count)
        ]
    return {
        "status": status,
        "page_urls": page_urls,
        "stale": stale,
        "page_count": book.page_count,
        "layout_version": book.layout_version,
    }
