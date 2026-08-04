"""Print geometry: the single module every other module imports (spec Part 3).

All stored coordinates are millimetres, origin at the top-left of the TRIM box.
The bleed box extends 3mm beyond trim on every side; pixel space has its origin
at the top-left of the BLEED box.
"""
from dataclasses import dataclass

from app.domain.errors import InvalidPlacement

DPI = 300
MM_PER_INCH = 25.4
PX_PER_MM = DPI / MM_PER_INCH  # 11.8110236...

TRIM_W_MM = 148.0  # A5
TRIM_H_MM = 210.0
BLEED_MM = 3.0

CANVAS_W_MM = TRIM_W_MM + 2 * BLEED_MM  # 154.0
CANVAS_H_MM = TRIM_H_MM + 2 * BLEED_MM  # 216.0

CANVAS_W_PX = 1819  # round(154 * 11.811)
CANVAS_H_PX = 2551  # round(216 * 11.811)

SAFE_MARGIN_MM = 5.0  # text must stay this far inside TRIM


def mm_to_px(mm: float) -> int:
    return round(mm * PX_PER_MM)


def px_to_mm(px: int) -> float:
    return px / PX_PER_MM


@dataclass(frozen=True)
class RectMM:
    """A rectangle in millimetres, trim-box origin."""

    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class RectPX:
    """A rectangle in pixels, bleed-box origin."""

    x: int
    y: int
    w: int
    h: int


def validate_placement(rect: RectMM) -> RectMM:
    """A placement must lie fully inside the bleed canvas. Raises InvalidPlacement."""
    if rect.w <= 0 or rect.h <= 0:
        raise InvalidPlacement("placement has non-positive size",
                               {"w_mm": rect.w, "h_mm": rect.h})
    if (rect.x < -BLEED_MM or rect.y < -BLEED_MM
            or rect.x + rect.w > TRIM_W_MM + BLEED_MM
            or rect.y + rect.h > TRIM_H_MM + BLEED_MM):
        raise InvalidPlacement("placement outside the canvas",
                               {"x_mm": rect.x, "y_mm": rect.y,
                                "w_mm": rect.w, "h_mm": rect.h})
    return rect


def placement_to_px(rect: RectMM) -> RectPX:
    """Map a validated trim-origin mm rect to a bleed-origin pixel rect.

    Edges are rounded, not width/height: rounding position and size
    independently can overflow the canvas by 1px, while rounded edges are
    monotonic, so a rect inside the mm canvas is always inside the px canvas.
    Full-bleed (-3,-3,154,216) maps exactly to (0,0,1819,2551).
    """
    validate_placement(rect)
    x1 = mm_to_px(rect.x + BLEED_MM)
    y1 = mm_to_px(rect.y + BLEED_MM)
    x2 = mm_to_px(rect.x + BLEED_MM + rect.w)
    y2 = mm_to_px(rect.y + BLEED_MM + rect.h)
    return RectPX(x=x1, y=y1, w=x2 - x1, h=y2 - y1)


# Safe area for text, in trim-origin mm (spec: x>=5, y>=5, x+w<=143, y+h<=205).
SAFE_X_MIN = SAFE_MARGIN_MM
SAFE_Y_MIN = SAFE_MARGIN_MM
SAFE_X_MAX = TRIM_W_MM - SAFE_MARGIN_MM  # 143.0
SAFE_Y_MAX = TRIM_H_MM - SAFE_MARGIN_MM  # 205.0


def clamp_text_box(rect: RectMM) -> RectMM:
    """Clamp a text box into the safe area. Never rejects — silently clamps
    and returns the result so the editor can reflect it (spec Part 3).

    Oversized boxes are first shrunk to the safe area's size, then shifted
    fully inside it.
    """
    w = min(rect.w, SAFE_X_MAX - SAFE_X_MIN)
    h = min(rect.h, SAFE_Y_MAX - SAFE_Y_MIN)
    x = min(max(rect.x, SAFE_X_MIN), SAFE_X_MAX - w)
    y = min(max(rect.y, SAFE_Y_MIN), SAFE_Y_MAX - h)
    return RectMM(x=x, y=y, w=w, h=h)
