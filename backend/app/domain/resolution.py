"""Low-resolution classification (spec Part 3).

This replaces AI enhancement for MVP: it prevents printing a visibly blurry
book. Effective DPI is computed at the placed physical size; the worse axis
decides. Thresholds: >=200 ok, 100-199 warn, <100 block. Additionally, a
source narrower than 800px may never fill a full page, whatever the math says.
"""
from typing import Literal

from app.domain.geometry import MM_PER_INCH, TRIM_H_MM, TRIM_W_MM

ResolutionStatus = Literal["ok", "warn", "block"]

DPI_OK = 200
DPI_WARN = 100
MIN_FULL_PAGE_SOURCE_PX = 800


def resolution_status(px_w: int, px_h: int,
                      target_mm_w: float, target_mm_h: float) -> ResolutionStatus:
    """Return 'ok' | 'warn' | 'block' for a photo placed at a given physical size."""
    if px_w <= 0 or px_h <= 0 or target_mm_w <= 0 or target_mm_h <= 0:
        return "block"

    fills_full_page = target_mm_w >= TRIM_W_MM and target_mm_h >= TRIM_H_MM
    if fills_full_page and min(px_w, px_h) < MIN_FULL_PAGE_SOURCE_PX:
        return "block"

    dpi_w = px_w / (target_mm_w / MM_PER_INCH)
    dpi_h = px_h / (target_mm_h / MM_PER_INCH)
    effective_dpi = min(dpi_w, dpi_h)

    if effective_dpi >= DPI_OK:
        return "ok"
    if effective_dpi >= DPI_WARN:
        return "warn"
    return "block"
