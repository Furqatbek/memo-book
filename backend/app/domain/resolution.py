"""Low-resolution classification (spec Part 3).

This module CLASSIFIES; it does not refuse. That distinction was wrong here
for a long time — the docstring used to claim it "prevents printing a visibly
blurry book", and nothing in the system prevented anything (A79).

Where the judgement is actually used:

* the photo list, so the tray can badge a photo the moment it is uploaded;
* the editor's preview screen, which names the pages that will print soft
  before the customer confirms — the one defect a preview structurally
  cannot show, because a 90-DPI photo looks perfect on a phone;
* the production notification and the admin order detail, so the operator
  sees it before the book is printed rather than after it is returned.

Refusing outright is deliberately NOT done. The threshold cannot tell a
careless crop from the only surviving photograph of someone's grandmother,
and the customer is told clearly, twice, before they pay. What the system
owes them is that nobody is surprised — not that the choice is taken away.

Effective DPI is computed at the placed physical size; the worse axis
decides. Thresholds: >=200 ok, 100-199 warn, <100 block. Additionally, a
source narrower than 800px may never fill a full page, whatever the math says.

Zoom matters as much as size (A68). Cropping into a photo at zoom Z prints
only 1/Z of it across the same paper, so a 4x zoom costs exactly as much
sharpness as making the placement four times wider.
"""
from typing import Literal

from app.domain.geometry import MM_PER_INCH, TRIM_H_MM, TRIM_W_MM

ResolutionStatus = Literal["ok", "warn", "block"]

DPI_OK = 200
DPI_WARN = 100
MIN_FULL_PAGE_SOURCE_PX = 800


def effective_dpi(px_w: int, px_h: int, target_mm_w: float, target_mm_h: float,
                  zoom: float = 1.0, fit: str = "cover") -> float:
    """Source pixels per printed inch, along whichever axis fares worse.

    Mirrors the renderer: "cover" scales by the LARGER of the two ratios
    (filling the slot and discarding the overflow), "contain" by the smaller
    (letterboxing, so the whole photo survives and prints smaller — always at
    least as sharp). Zoom multiplies the scale, and divides the result.
    """
    if px_w <= 0 or px_h <= 0 or target_mm_w <= 0 or target_mm_h <= 0:
        return 0.0
    dpi_w = px_w / (target_mm_w / MM_PER_INCH)
    dpi_h = px_h / (target_mm_h / MM_PER_INCH)
    axis = min(dpi_w, dpi_h) if fit != "contain" else max(dpi_w, dpi_h)
    return axis / max(1.0, zoom)


def resolution_status(px_w: int, px_h: int,
                      target_mm_w: float, target_mm_h: float,
                      zoom: float = 1.0, fit: str = "cover") -> ResolutionStatus:
    """Return 'ok' | 'warn' | 'block' for a photo placed at a given physical
    size and crop. The defaults describe an uncropped, unzoomed placement."""
    if px_w <= 0 or px_h <= 0 or target_mm_w <= 0 or target_mm_h <= 0:
        return "block"

    # A tiny source cannot carry a whole page however the numbers land — and
    # zooming into it only spends the pixels faster. "contain" is exempt: it
    # letterboxes, so the photo is never asked to fill the page at all.
    fills_full_page = (fit != "contain"
                       and target_mm_w >= TRIM_W_MM and target_mm_h >= TRIM_H_MM)
    if fills_full_page and min(px_w, px_h) / max(1.0, zoom) < MIN_FULL_PAGE_SOURCE_PX:
        return "block"

    dpi = effective_dpi(px_w, px_h, target_mm_w, target_mm_h, zoom, fit)
    if dpi >= DPI_OK:
        return "ok"
    if dpi >= DPI_WARN:
        return "warn"
    return "block"


def placement_resolution(placement: dict, px_w: int, px_h: int) -> ResolutionStatus:
    """How a specific placement will print. A placement across the fold keeps
    its full spread width here: the photo really is enlarged that far, even
    though each page shows only half of it."""
    return resolution_status(
        px_w, px_h,
        float(placement.get("w_mm") or 0), float(placement.get("h_mm") or 0),
        zoom=float(placement.get("zoom") or 1.0),
        fit=str(placement.get("fit") or "cover"),
    )


# The cover's page number, for a list that otherwise holds real page indexes.
COVER_PAGE = -1


def soft_placements(layout: dict,
                    photo_px: dict[str, tuple[int, int]]) -> list[dict]:
    """Everything in this book that will print softer than `ok`, worst first.

    `photo_px` maps photo id to (width, height) in source pixels; a photo
    missing from it is skipped rather than assumed bad — an un-ingested photo
    has no dimensions yet, and guessing "block" would cry wolf.

    Pages are reported 1-based, as the customer and the printer count them.
    The cover is reported as `page: null`, since it has no number.
    """
    from app.domain.cover_templates import photo_rect_for

    found: list[dict] = []

    cover = layout.get("cover") or {}
    cover_photo = cover.get("photo_id")
    if cover_photo and cover_photo in photo_px:
        rect = photo_rect_for(cover)
        status = placement_resolution(
            {"w_mm": rect["w_mm"], "h_mm": rect["h_mm"],
             "zoom": cover.get("photo_zoom") or 1.0, "fit": "cover"},
            *photo_px[cover_photo])
        if status != "ok":
            found.append({"page": None, "where": "cover", "status": status})

    for page in layout.get("pages") or []:
        for placement in page.get("placements") or []:
            photo_id = placement.get("photo_id")
            if photo_id not in photo_px:
                continue
            status = placement_resolution(placement, *photo_px[photo_id])
            if status != "ok":
                number = int(page.get("index", 0)) + 1
                found.append({"page": number, "where": f"page {number}",
                              "status": status})

    # Worst first, then in reading order: the operator reads the top of the
    # list and needs the unprintable ones there.
    found.sort(key=lambda f: (f["status"] != "block", f["page"] or 0))
    return found
