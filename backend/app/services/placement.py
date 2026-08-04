"""Auto-place (R2) and checkout eligibility (R1/R3) wired to real data.

The ordering and gating rules themselves live in app.domain — this module
only feeds them photos from the database and writes the resulting layout.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.geometry import BLEED_MM, CANVAS_H_MM, CANVAS_W_MM
from app.domain.ordering import PhotoForOrdering, auto_place_order
from app.domain.tiers import CheckoutEligibility, checkout_eligibility
from app.models.book import Book
from app.models.photo import Photo, PhotoStatus
from app.schemas.layout import LayoutDoc
from app.services.books import (
    _require_mutable,
    _require_version,
    _touch,
    get_book_authed,
)

# Photos that can appear on a page. Duplicates are placeable — the user chose
# to keep them — they are only *flagged* so the editor can surface them (A21).
USABLE_STATUSES = (PhotoStatus.READY.value, PhotoStatus.DUPLICATE.value)


async def _usable_photos(session: AsyncSession, book_id: uuid.UUID) -> list[Photo]:
    result = await session.execute(
        select(Photo).where(Photo.book_id == book_id, Photo.status.in_(USABLE_STATUSES))
    )
    return list(result.scalars())


def _full_bleed_placement(photo_id: uuid.UUID) -> dict:
    return {
        "photo_id": str(photo_id),
        "x_mm": -BLEED_MM,
        "y_mm": -BLEED_MM,
        "w_mm": CANVAS_W_MM,
        "h_mm": CANVAS_H_MM,
        "rotation": 0,
        "fit": "cover",
    }


async def auto_place(session: AsyncSession, book_id: uuid.UUID, edit_token: str,
                     if_match: int | None) -> tuple[Book, int, list[str]]:
    """Fill pages chronologically (R2), one photo per page, full-bleed.
    Existing texts and the cover are preserved; only placements are rewritten.
    Surplus photos are returned, never silently dropped (R3)."""
    book = await get_book_authed(session, book_id, edit_token)
    _require_mutable(book)
    _require_version(book, if_match)

    photos = await _usable_photos(session, book_id)
    ordered_ids = auto_place_order([
        PhotoForOrdering(id=str(p.id), taken_at=p.taken_at, uploaded_at=p.uploaded_at)
        for p in photos
    ])
    placed = ordered_ids[: book.page_count]

    # Rewrite placements only; texts and cover survive untouched.
    layout = LayoutDoc.model_validate(book.layout).model_dump()
    for page in layout["pages"]:
        idx = page["index"]
        if idx < len(placed):
            page["placements"] = [_full_bleed_placement(uuid.UUID(placed[idx]))]
        else:
            page["placements"] = []

    book.layout = LayoutDoc.model_validate(layout).model_dump()
    book.layout_version += 1
    _touch(book)
    await session.commit()
    await session.refresh(book)

    unplaced = ordered_ids[book.page_count:]
    return book, len(placed), unplaced


async def eligibility(session: AsyncSession, book_id: uuid.UUID,
                      edit_token: str) -> CheckoutEligibility:
    book = await get_book_authed(session, book_id, edit_token)
    photos = await _usable_photos(session, book_id)
    return checkout_eligibility(photo_count=len(photos), page_count=book.page_count)
