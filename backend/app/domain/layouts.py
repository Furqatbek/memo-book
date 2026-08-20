"""Page layout presets — the slot grids a page can hold.

The seam was always here: `PageDoc.placements` is a list (spec Part 12), and
the renderer has always drawn every entry. A preset is just a named set of
rectangles the editor snaps photos into, stored on the page so the editor
knows how many slots to draw — including the empty ones a page may still
have. Geometry is trim-origin mm, matching placements; outer edges sit at
-BLEED so multi-photo pages bleed off the trimmed edge like a magazine.

Generated for the editor by scripts/gen_layouts.py; tests/domain/test_layouts
fails if the two copies ever drift.
"""
from app.domain.geometry import (
    BLEED_MM,
    CANVAS_H_MM,
    CANVAS_W_MM,
    TRIM_H_MM,
    TRIM_W_MM,
)

# Space between neighbouring photos. Deliberately small: the printer's
# trimming tolerance is ±1mm, and a wide gutter reads as a mistake.
GUTTER_MM = 2.0

_X0 = -BLEED_MM
_Y0 = -BLEED_MM
_W = CANVAS_W_MM
_H = CANVAS_H_MM
_HALF_W = (_W - GUTTER_MM) / 2
_HALF_H = (_H - GUTTER_MM) / 2
_THIRD_H = (_H - 2 * GUTTER_MM) / 3
_BIG_H = _H * 0.62
_REST_H = _H - _BIG_H - GUTTER_MM


def _slot(x: float, y: float, w: float, h: float) -> dict:
    return {"x_mm": round(x, 2), "y_mm": round(y, 2),
            "w_mm": round(w, 2), "h_mm": round(h, 2)}


LAYOUTS: dict[str, list[dict]] = {
    # One photo, edge to edge — the classic single-image page.
    "full": [_slot(_X0, _Y0, _W, _H)],
    # One photo floating inside a border of page colour.
    "inset": [_slot(12, 12, TRIM_W_MM - 24, TRIM_H_MM - 24)],
    "two-h": [
        _slot(_X0, _Y0, _HALF_W, _H),
        _slot(_X0 + _HALF_W + GUTTER_MM, _Y0, _HALF_W, _H),
    ],
    "two-v": [
        _slot(_X0, _Y0, _W, _HALF_H),
        _slot(_X0, _Y0 + _HALF_H + GUTTER_MM, _W, _HALF_H),
    ],
    "three-v": [
        _slot(_X0, _Y0, _W, _THIRD_H),
        _slot(_X0, _Y0 + _THIRD_H + GUTTER_MM, _W, _THIRD_H),
        _slot(_X0, _Y0 + 2 * (_THIRD_H + GUTTER_MM), _W, _THIRD_H),
    ],
    "four": [
        _slot(_X0, _Y0, _HALF_W, _HALF_H),
        _slot(_X0 + _HALF_W + GUTTER_MM, _Y0, _HALF_W, _HALF_H),
        _slot(_X0, _Y0 + _HALF_H + GUTTER_MM, _HALF_W, _HALF_H),
        _slot(_X0 + _HALF_W + GUTTER_MM, _Y0 + _HALF_H + GUTTER_MM,
              _HALF_W, _HALF_H),
    ],
    # A hero image with two supporting photos underneath.
    "big-top": [
        _slot(_X0, _Y0, _W, _BIG_H),
        _slot(_X0, _Y0 + _BIG_H + GUTTER_MM, _HALF_W, _REST_H),
        _slot(_X0 + _HALF_W + GUTTER_MM, _Y0 + _BIG_H + GUTTER_MM,
              _HALF_W, _REST_H),
    ],
}

DEFAULT_LAYOUT = "full"
LAYOUT_IDS = frozenset(LAYOUTS)
MAX_PLACEMENTS_PER_PAGE = max(len(slots) for slots in LAYOUTS.values())


def slots_for(layout_id: str | None) -> list[dict]:
    """Slots of a layout; unknown/missing ids fall back to the single
    full-bleed slot so older stored pages keep working."""
    return LAYOUTS.get(layout_id or DEFAULT_LAYOUT, LAYOUTS[DEFAULT_LAYOUT])
