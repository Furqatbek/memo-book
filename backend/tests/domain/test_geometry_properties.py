"""Property tests (hypothesis) — spec Part 9.1."""
from hypothesis import given
from hypothesis import strategies as st

from app.domain.geometry import (
    BLEED_MM,
    CANVAS_H_PX,
    CANVAS_W_PX,
    SAFE_X_MAX,
    SAFE_X_MIN,
    SAFE_Y_MAX,
    SAFE_Y_MIN,
    TRIM_H_MM,
    TRIM_W_MM,
    RectMM,
    clamp_text_box,
    mm_to_px,
    placement_to_px,
    px_to_mm,
)

finite = {"allow_nan": False, "allow_infinity": False}


@st.composite
def valid_placements(draw):
    # Draw size first, then position within the remaining room — this keeps
    # every bound pair non-empty under float rounding.
    w = draw(st.floats(min_value=0.1, max_value=TRIM_W_MM + 2 * BLEED_MM, **finite))
    h = draw(st.floats(min_value=0.1, max_value=TRIM_H_MM + 2 * BLEED_MM, **finite))
    x = draw(st.floats(min_value=-BLEED_MM, max_value=TRIM_W_MM + BLEED_MM - w, **finite))
    y = draw(st.floats(min_value=-BLEED_MM, max_value=TRIM_H_MM + BLEED_MM - h, **finite))
    return RectMM(x, y, w, h)


@given(valid_placements())
def test_rendered_rect_fully_inside_canvas(rect):
    px = placement_to_px(rect)
    assert px.x >= 0
    assert px.y >= 0
    assert px.x + px.w <= CANVAS_W_PX
    assert px.y + px.h <= CANVAS_H_PX
    assert px.w >= 0
    assert px.h >= 0


@given(
    st.floats(min_value=-500, max_value=500, **finite),
    st.floats(min_value=-500, max_value=500, **finite),
    st.floats(min_value=0.1, max_value=500, **finite),
    st.floats(min_value=0.1, max_value=500, **finite),
)
def test_clamped_text_box_inside_safe_area(x, y, w, h):
    clamped = clamp_text_box(RectMM(x, y, w, h))
    assert clamped.x >= SAFE_X_MIN
    assert clamped.y >= SAFE_Y_MIN
    assert clamped.x + clamped.w <= SAFE_X_MAX
    assert clamped.y + clamped.h <= SAFE_Y_MAX


@given(st.integers(min_value=0, max_value=3000))
def test_px_mm_roundtrip(n):
    assert mm_to_px(px_to_mm(n)) == n
