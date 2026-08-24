"""The ready-made cover catalogue (A71).

Designs are content, not code: uploaded, renamed and retired without a
deploy. This module owns three jobs — what the customer is offered, what
the renderer needs, and what the admin script writes.

Artwork covers exactly the region a full-bleed cover photo covers: the front
panel plus the turn-in above, below and to its right. The back panel and the
spine take the design's own `bg_color`, so one file serves every page tier —
the spine width changes with the tier, and a fixed-width wrap image would
have to be redrawn for each one.
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import storage
from app.domain.book_types import normalize_book_type
from app.models.cover_design import CoverDesign

# What the founder draws against: the front panel (148x210) plus the 16mm
# turn-in on three sides, at 300 dpi. Stated in one place so the admin
# script, the tests and the guidance in docs/ cannot disagree.
ARTWORK_W_MM = 164.0            # TRIM_W + WRAP
ARTWORK_H_MM = 242.0            # TRIM_H + 2 * WRAP
ARTWORK_W_PX = 1937
ARTWORK_H_PX = 2858
# Refuse art that would print soft. Below this the customer sees a blurry
# cover and we only find out when the book arrives.
MIN_ARTWORK_W_PX = 1600
MIN_ARTWORK_H_PX = 2360

DISPLAY_W_PX = 1200
THUMB_W_PX = 400

DESIGN_PREFIX = "cover-designs"


def _now() -> datetime:
    return datetime.now(UTC)


def artwork_key(slug: str) -> str:
    return f"{DESIGN_PREFIX}/{slug}/artwork.jpg"


def display_key(slug: str) -> str:
    return f"{DESIGN_PREFIX}/{slug}/display.jpg"


def thumb_key(slug: str) -> str:
    return f"{DESIGN_PREFIX}/{slug}/thumb.jpg"


def parse_book_types(raw: str | None) -> list[str]:
    """"love, travel" -> ["love", "travel"]. Unknown names are dropped rather
    than stored, so a typo in an admin command cannot hide a design from
    every customer without saying so."""
    if not raw:
        return []
    out = []
    for part in raw.replace(";", ",").split(","):
        slug = normalize_book_type(part)
        if slug and slug not in out:
            out.append(slug)
    return out


def suits(design: CoverDesign, book_type: str) -> bool:
    """A design with no occasions listed suits every book — that is the point
    of leaving it blank, not an accident to be filtered out."""
    wanted = parse_book_types(design.book_types)
    if not wanted:
        return True
    return normalize_book_type(book_type) in wanted


def serialize(design: CoverDesign) -> dict:
    """What the editor is told. The print-resolution artwork is deliberately
    absent: the customer needs to see the design, not to hold the file."""
    payload = {
        "design_id": str(design.id),
        "slug": design.slug,
        "name": design.name,
        "book_types": parse_book_types(design.book_types),
        "thumb_url": storage.presign_get(design.thumb_key),
        "display_url": storage.presign_get(design.display_key),
        "photo_rect": design.photo_rect,
        "bg_color": design.bg_color,
    }
    if design.title_x_mm is not None and design.title_y_mm is not None:
        payload["title"] = {"x_mm": design.title_x_mm, "y_mm": design.title_y_mm,
                            "size_pt": design.title_size_pt}
    if design.title_color:
        payload["title_color"] = design.title_color
    return payload


async def list_designs(session: AsyncSession, book_type: str | None = None,
                       include_inactive: bool = False) -> list[CoverDesign]:
    stmt = select(CoverDesign).order_by(CoverDesign.sort_order, CoverDesign.slug)
    if not include_inactive:
        stmt = stmt.where(CoverDesign.active.is_(True))
    designs = list((await session.execute(stmt)).scalars())
    # No occasion asked for means no filter — the whole shelf. The editor
    # always knows the occasion by this point, so this is the browsing and
    # admin case, where hiding most of the catalogue would only confuse.
    if not book_type:
        return designs
    return [d for d in designs if suits(d, book_type)]


async def get_design(session: AsyncSession,
                     design_id: str | uuid.UUID | None) -> CoverDesign | None:
    """Fetch by id, tolerating rubbish. A cover naming a design that has been
    retired — or a malformed id from a hand-edited document — must not stop
    the book rendering; it simply has no artwork."""
    if not design_id:
        return None
    try:
        key = uuid.UUID(str(design_id))
    except (ValueError, AttributeError, TypeError):
        return None
    return (await session.execute(
        select(CoverDesign).where(CoverDesign.id == key)
    )).scalar_one_or_none()


async def design_artwork_bytes(session: AsyncSession,
                               design_id: str | None) -> bytes | None:
    design = await get_design(session, design_id)
    if design is None:
        return None
    try:
        return storage.get_bytes(design.artwork_key)
    except Exception:
        # A missing object must not sink an order that is already paid for:
        # the cover renders on its background colour instead.
        return None


async def upsert_design(session: AsyncSession, *, slug: str, name: str,
                        book_types: str, artwork: bytes, display: bytes,
                        thumb: bytes, width: int, height: int,
                        photo_rect: dict | None, title: dict | None,
                        title_color: str | None, bg_color: str,
                        sort_order: int) -> CoverDesign:
    """Add a design, or replace the artwork and settings of one with the same
    slug. Re-running the admin command is how a design gets corrected, so it
    must not leave a second copy behind."""
    storage.put_bytes(artwork_key(slug), artwork, "image/jpeg")
    storage.put_bytes(display_key(slug), display, "image/jpeg")
    storage.put_bytes(thumb_key(slug), thumb, "image/jpeg")

    design = (await session.execute(
        select(CoverDesign).where(CoverDesign.slug == slug)
    )).scalar_one_or_none()
    if design is None:
        design = CoverDesign(id=uuid.uuid4(), slug=slug, created_at=_now())
        session.add(design)

    design.name = name or slug
    design.book_types = ",".join(parse_book_types(book_types))
    design.artwork_key = artwork_key(slug)
    design.display_key = display_key(slug)
    design.thumb_key = thumb_key(slug)
    design.artwork_width = width
    design.artwork_height = height
    design.photo_rect = photo_rect
    design.title_x_mm = title["x_mm"] if title else None
    design.title_y_mm = title["y_mm"] if title else None
    design.title_size_pt = title.get("size_pt") if title else None
    design.title_color = title_color
    design.bg_color = bg_color
    design.sort_order = sort_order
    design.active = True
    await session.commit()
    await session.refresh(design)
    return design
