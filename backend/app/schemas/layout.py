"""The layout document schema (spec Part 3), stored as one JSONB column.

Seam for multi-photo pages (spec Part 12): `page.placements` is a LIST from
day one, with a validator enforcing at most one entry in MVP. Changing a
scalar to a list later would mean migrating every stored layout.
"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.geometry import RectMM, clamp_text_box, validate_placement
from app.domain.stickers import sticker_ids

LAYOUT_SCHEMA_VERSION = 1

MAX_PLACEMENTS_PER_PAGE_MVP = 1


class PlacementDoc(BaseModel):
    model_config = ConfigDict(extra="forbid")

    photo_id: str
    x_mm: float
    y_mm: float
    w_mm: float
    h_mm: float
    rotation: float = Field(default=0, ge=-360, le=360)
    fit: Literal["cover", "contain"] = "cover"

    @model_validator(mode="after")
    def _inside_canvas(self):
        # Raises InvalidPlacement (a DomainError) -> 422 with a structured code.
        validate_placement(RectMM(self.x_mm, self.y_mm, self.w_mm, self.h_mm))
        return self


class TextBoxDoc(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=64)
    x_mm: float
    y_mm: float
    w_mm: float = Field(gt=0)
    h_mm: float = Field(gt=0)
    content: str = Field(max_length=1000)
    font: str = Field(default="Inter", max_length=64)
    size_pt: float = Field(default=11, ge=4, le=144)
    align: Literal["left", "center", "right"] = "left"
    color: str = Field(default="#1a1a1a", pattern=r"^#[0-9a-fA-F]{6}$")
    # Degrees, clockwise, about the box centre (matches CSS rotate()).
    # The safe-area clamp applies to the unrotated box; a rotated box's
    # corners may extend slightly past it — accepted for MVP.
    rotation: float = Field(default=0, ge=-360, le=360)

    @model_validator(mode="after")
    def _clamp_to_safe_area(self):
        # Server-side clamping (spec Part 3): never reject, silently clamp and
        # return the clamped value so the editor can reflect it.
        clamped = clamp_text_box(RectMM(self.x_mm, self.y_mm, self.w_mm, self.h_mm))
        object.__setattr__(self, "x_mm", clamped.x)
        object.__setattr__(self, "y_mm", clamped.y)
        object.__setattr__(self, "w_mm", clamped.w)
        object.__setattr__(self, "h_mm", clamped.h)
        return self


HEX_COLOR = r"^#[0-9a-fA-F]{6}$"


class StickerDoc(BaseModel):
    """A vendored decorative sticker (square asset, aspect fixed at 1:1).
    Position is the CENTRE in canvas mm — stickers may deliberately hang off
    the page edge (classic scrapbook look); the renderer clips at bleed."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(max_length=64)
    sticker_id: str = Field(max_length=64)
    x_mm: float = Field(ge=-40, le=194)   # canvas 154mm wide + overhang room
    y_mm: float = Field(ge=-40, le=256)   # canvas 216mm tall + overhang room
    w_mm: float = Field(ge=5, le=120)
    # Degrees, clockwise, about the centre (matches CSS rotate()).
    rotation: float = Field(default=0, ge=-360, le=360)

    @field_validator("sticker_id")
    @classmethod
    def _known_sticker(cls, v):
        if v not in sticker_ids():
            raise ValueError(f"unknown sticker {v!r}")
        return v


class CoverDoc(BaseModel):
    model_config = ConfigDict(extra="forbid")

    photo_id: str | None = None
    title: str = Field(default="", max_length=200)
    subtitle: str = Field(default="", max_length=200)
    title_font: str = Field(default="Inter", max_length=64)
    title_size_pt: float = Field(default=28, ge=4, le=144)
    # None = automatic (white with shadow over a photo, dark ink otherwise).
    title_color: str | None = Field(default=None, pattern=HEX_COLOR)
    bg_color: str = Field(default="#ffffff", pattern=HEX_COLOR)
    # Centre of the title block on the front panel, trim-origin mm.
    # None = the classic fixed position (kept for existing covers).
    title_x_mm: float | None = Field(default=None, ge=0, le=148)
    title_y_mm: float | None = Field(default=None, ge=0, le=210)
    # Clockwise degrees about the block centre, like text boxes.
    title_rotation: float = Field(default=0, ge=-360, le=360)
    stickers: list[StickerDoc] = Field(default_factory=list, max_length=20)


class PageDoc(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    bg_color: str = Field(default="#ffffff", pattern=HEX_COLOR)
    placements: list[PlacementDoc] = Field(default_factory=list)
    texts: list[TextBoxDoc] = Field(default_factory=list, max_length=20)
    stickers: list[StickerDoc] = Field(default_factory=list, max_length=20)

    @field_validator("placements")
    @classmethod
    def _mvp_single_placement(cls, v):
        if len(v) > MAX_PLACEMENTS_PER_PAGE_MVP:
            raise ValueError(
                f"MVP allows at most {MAX_PLACEMENTS_PER_PAGE_MVP} placement per page"
            )
        return v


class LayoutDoc(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = LAYOUT_SCHEMA_VERSION
    cover: CoverDoc = Field(default_factory=CoverDoc)
    pages: list[PageDoc] = Field(default_factory=list)

    @model_validator(mode="after")
    def _indices_match_positions(self):
        for pos, page in enumerate(self.pages):
            if page.index != pos:
                raise ValueError(f"page at position {pos} has index {page.index}")
        return self


def empty_layout(page_count: int) -> dict:
    doc = LayoutDoc(pages=[PageDoc(index=i) for i in range(page_count)])
    return doc.model_dump()


def reflow_layout(current: dict, new_page_count: int) -> tuple[dict, list[str]]:
    """Re-flow an existing layout to a new page count.

    Shrinking truncates trailing pages (warning lists what was dropped —
    the API warns, it never silently drops content). Growing appends empty
    pages. Indices are renumbered to stay contiguous.
    """
    doc = LayoutDoc.model_validate(current)
    warnings: list[str] = []

    if new_page_count < len(doc.pages):
        dropped = doc.pages[new_page_count:]
        dropped_photos = sum(len(p.placements) for p in dropped)
        dropped_texts = sum(len(p.texts) for p in dropped)
        dropped_stickers = sum(len(p.stickers) for p in dropped)
        if dropped_photos or dropped_texts or dropped_stickers:
            warnings.append(
                f"truncated {len(dropped)} pages containing {dropped_photos} "
                f"placed photos, {dropped_texts} text boxes and "
                f"{dropped_stickers} stickers"
            )
        doc.pages = doc.pages[:new_page_count]
    elif new_page_count > len(doc.pages):
        doc.pages = doc.pages + [
            PageDoc(index=i) for i in range(len(doc.pages), new_page_count)
        ]

    for pos, page in enumerate(doc.pages):
        page.index = pos

    return doc.model_dump(), warnings
