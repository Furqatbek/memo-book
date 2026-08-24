import pytest

from app.domain.errors import InvalidPlacement
from app.domain.geometry import (
    BLEED_MM,
    CANVAS_H_PX,
    CANVAS_W_PX,
    PX_PER_MM,
    SAFE_X_MAX,
    SAFE_X_MIN,
    SAFE_Y_MAX,
    SAFE_Y_MIN,
    RectMM,
    clamp_text_box,
    mm_to_px,
    placement_to_px,
    px_to_mm,
    validate_placement,
)


class TestConversion:
    def test_mm_to_px_within_half_px_across_range(self):
        mm = 0.0
        while mm <= 300.0:
            assert abs(mm_to_px(mm) - mm * PX_PER_MM) <= 0.5
            mm += 0.1

    def test_px_roundtrip_exact(self):
        for n in range(3001):
            assert mm_to_px(px_to_mm(n)) == n


class TestPlacement:
    def test_full_bleed_maps_exactly(self):
        rect = placement_to_px(RectMM(-3, -3, 154, 216))
        assert (rect.x, rect.y, rect.w, rect.h) == (0, 0, CANVAS_W_PX, CANVAS_H_PX)

    def test_trim_origin_shift(self):
        rect = placement_to_px(RectMM(0, 0, 148, 210))
        assert rect.x == mm_to_px(BLEED_MM)
        assert rect.y == mm_to_px(BLEED_MM)

    @pytest.mark.parametrize("bad", [
        RectMM(0, -4, 10, 10),           # above bleed
        RectMM(0, 210, 10, 10),          # crosses bottom bleed edge
        RectMM(0, 0, 0, 10),             # zero width
        RectMM(0, 0, 10, -5),            # negative height
        RectMM(0, 0, 400, 10),           # wider than a whole spread
        RectMM(200, 0, 10, 10),          # entirely off this page
        RectMM(-60, 0, 10, 10),          # entirely off, past the fold side
    ])
    def test_placement_outside_canvas_rejected(self, bad):
        with pytest.raises(InvalidPlacement):
            validate_placement(bad)


class TestTextClamping:
    def test_left_edge_clamps_to_safe_margin(self):
        clamped = clamp_text_box(RectMM(1, 50, 30, 10))
        assert clamped.x == SAFE_X_MIN

    def test_right_overflow_clamps_inside(self):
        clamped = clamp_text_box(RectMM(140, 50, 20, 10))
        assert clamped.x + clamped.w <= SAFE_X_MAX
        assert clamped.w == 20  # box fits in the safe area, so size is preserved

    def test_bottom_overflow_clamps_inside(self):
        clamped = clamp_text_box(RectMM(10, 200, 30, 20))
        assert clamped.y + clamped.h <= SAFE_Y_MAX

    def test_oversized_box_shrinks_to_safe_area(self):
        clamped = clamp_text_box(RectMM(-50, -50, 500, 500))
        assert (clamped.x, clamped.y) == (SAFE_X_MIN, SAFE_Y_MIN)
        assert clamped.w == SAFE_X_MAX - SAFE_X_MIN
        assert clamped.h == SAFE_Y_MAX - SAFE_Y_MIN

    def test_already_safe_box_unchanged(self):
        rect = RectMM(12, 180, 124, 18)
        assert clamp_text_box(rect) == rect


class TestPlacementsMayCrossTheFold:
    """A65: a photo running onto the facing page is stored on both pages as
    the same rectangle shifted by one trim width, so each page legitimately
    holds a rectangle that hangs off its own edge."""

    @pytest.mark.parametrize("ok", [
        RectMM(-4, 0, 10, 10),              # hangs over the left edge
        RectMM(145, 0, 10, 10),             # hangs over the right edge
        RectMM(-3, -3, 302, 216),           # the left half of a full spread
        RectMM(-151, -3, 302, 216),         # the right half of the same photo
    ])
    def test_horizontal_overflow_is_allowed(self, ok):
        assert validate_placement(ok) is ok

    def test_both_halves_map_to_pixels_one_trim_width_apart(self):
        from app.domain.geometry import TRIM_W_MM

        left = placement_to_px(RectMM(-3, -3, 302, 216))
        right = placement_to_px(RectMM(-3 - TRIM_W_MM, -3, 302, 216))
        assert left.x - right.x == mm_to_px(TRIM_W_MM)
        assert left.w == right.w
