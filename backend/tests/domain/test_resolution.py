from app.domain.geometry import CANVAS_H_MM, CANVAS_W_MM
from app.domain.resolution import resolution_status

FULL_W = CANVAS_W_MM  # 154mm — a full-bleed A5 page
FULL_H = CANVAS_H_MM  # 216mm


class TestResolutionThresholds:
    def test_4000px_on_full_page_ok(self):
        assert resolution_status(4000, 5600, FULL_W, FULL_H) == "ok"

    def test_1000px_on_full_page_warn(self):
        assert resolution_status(1000, 1400, FULL_W, FULL_H) == "warn"

    def test_600px_on_full_page_block(self):
        assert resolution_status(600, 850, FULL_W, FULL_H) == "block"

    def test_600px_on_small_placement_ok(self):
        # 600px across 40mm ≈ 381 DPI — small placement, high effective DPI
        assert resolution_status(600, 600, 40.0, 40.0) == "ok"

    def test_boundary_exactly_200_dpi_is_ok(self):
        # 200px over 25.4mm (1 inch) = exactly 200 DPI
        assert resolution_status(200, 200, 25.4, 25.4) == "ok"

    def test_boundary_exactly_100_dpi_is_warn(self):
        assert resolution_status(100, 100, 25.4, 25.4) == "warn"

    def test_just_below_100_dpi_blocks(self):
        assert resolution_status(99, 99, 25.4, 25.4) == "block"

    def test_worst_axis_decides(self):
        # Width is fine, height is catastrophic
        assert resolution_status(4000, 300, FULL_W, FULL_H) == "block"


class TestAbsoluteFloor:
    def test_narrow_source_never_fills_full_page(self):
        # 799px source: even placed small enough that DPI math would pass,
        # a full-page placement is blocked by the 800px floor.
        assert resolution_status(799, 5000, FULL_W, FULL_H) == "block"

    def test_narrow_source_allowed_on_partial_page(self):
        assert resolution_status(799, 799, 50.0, 50.0) == "ok"

    def test_800px_source_not_floored(self):
        # At exactly 800px the floor no longer applies; DPI rules decide.
        assert resolution_status(800, 1200, FULL_W, FULL_H) == "warn"


class TestDegenerateInput:
    def test_zero_dimensions_block(self):
        assert resolution_status(0, 100, 40, 40) == "block"
        assert resolution_status(100, 100, 0, 40) == "block"
