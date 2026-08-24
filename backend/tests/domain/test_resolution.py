import re
from pathlib import Path

from app.domain.geometry import CANVAS_H_MM, CANVAS_W_MM, SPREAD_W_MM
from app.domain.resolution import (
    DPI_OK,
    DPI_WARN,
    MIN_FULL_PAGE_SOURCE_PX,
    placement_resolution,
    resolution_status,
)

CANVAS_W = CANVAS_W_MM
CANVAS_H = CANVAS_H_MM
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


class TestZoomSpendsResolution:
    """A68: cropping in at zoom Z prints 1/Z of the photo across the same
    paper, so zoom costs exactly what enlarging the placement costs."""

    def test_zoom_is_equivalent_to_a_bigger_placement(self):
        # 2x zoom into a 40mm slot uses the same pixels as an 80mm slot.
        for px in (400, 800, 1600):
            assert (resolution_status(px, px, 40.0, 40.0, zoom=2.0)
                    == resolution_status(px, px, 80.0, 80.0))

    def test_a_sharp_photo_goes_soft_when_zoomed_in(self):
        # 1200px over 100mm is 305 DPI; at 2x it is 152 and only warns.
        assert resolution_status(1200, 1200, 100.0, 100.0) == "ok"
        assert resolution_status(1200, 1200, 100.0, 100.0, zoom=2.0) == "warn"
        assert resolution_status(1200, 1200, 100.0, 100.0, zoom=4.0) == "block"

    def test_zoom_below_one_never_flatters_a_photo(self):
        # The renderer clamps to max(1.0, zoom); so must the warning.
        assert (resolution_status(600, 850, FULL_W, FULL_H, zoom=0.25)
                == resolution_status(600, 850, FULL_W, FULL_H))

    def test_the_full_page_pixel_floor_also_counts_zoom(self):
        # 1600px clears the 800px floor — until 2x zoom halves what is used.
        assert resolution_status(1600, 1600, FULL_W, FULL_H) != "block"
        assert resolution_status(1600, 1600, FULL_W, FULL_H, zoom=2.01) == "block"

    def test_default_is_an_unzoomed_placement(self):
        assert (resolution_status(1000, 1400, FULL_W, FULL_H)
                == resolution_status(1000, 1400, FULL_W, FULL_H, zoom=1.0))


class TestFitContain:
    """'Fit' letterboxes instead of cropping, so the whole photo survives and
    prints smaller — never worse than the same photo filling the slot."""

    def test_contain_is_never_softer_than_cover(self):
        rank = {"ok": 2, "warn": 1, "block": 0}
        for w, h in ((3000, 800), (800, 3000), (1500, 1500)):
            cover = resolution_status(w, h, FULL_W, FULL_H)
            contain = resolution_status(w, h, FULL_W, FULL_H, fit="contain")
            assert rank[contain] >= rank[cover]

    def test_a_panorama_fits_a_page_it_could_not_fill(self):
        # Wide and short: filling the page would starve the vertical axis.
        assert resolution_status(4000, 700, FULL_W, FULL_H) == "block"
        assert resolution_status(4000, 700, FULL_W, FULL_H, fit="contain") == "ok"


class TestPlacementResolution:
    def test_it_reads_the_placement_document(self):
        pl = {"photo_id": "p", "x_mm": 0, "y_mm": 0, "w_mm": 40, "h_mm": 40,
              "zoom": 2.0, "fit": "cover"}
        assert placement_resolution(pl, 400, 400) == resolution_status(
            400, 400, 40.0, 40.0, zoom=2.0)

    def test_defaults_apply_when_the_document_omits_them(self):
        pl = {"photo_id": "p", "x_mm": 0, "y_mm": 0, "w_mm": 40, "h_mm": 40}
        assert placement_resolution(pl, 400, 400) == resolution_status(400, 400, 40, 40)

    def test_a_spread_placement_is_judged_at_its_full_width(self):
        # It spans two pages, so the photo really is enlarged that far even
        # though each page shows half.
        page = {"photo_id": "p", "w_mm": CANVAS_W, "h_mm": CANVAS_H}
        spread = {"photo_id": "p", "w_mm": SPREAD_W_MM, "h_mm": CANVAS_H}
        assert placement_resolution(page, 1800, 2200) == "ok"
        assert placement_resolution(spread, 1800, 2200) == "warn"


class TestEditorMirror:
    """The editor recomputes this per placement so it can warn while the
    customer can still fix it. Hand-mirrored in editor/js/app.js — if the
    thresholds move here and not there, the editor lies about the print."""

    def test_thresholds_match_the_editor_copy(self):
        src = (Path(__file__).resolve().parents[3] / "editor/js/app.js").read_text()
        for name, value in (("DPI_OK", DPI_OK), ("DPI_WARN", DPI_WARN),
                            ("MIN_FULL_PAGE_SOURCE_PX", MIN_FULL_PAGE_SOURCE_PX)):
            assert re.search(rf"\b{name}\s*=\s*{value}\b", src), \
                f"editor/js/app.js does not define {name} = {value}"

    def test_the_editor_divides_by_zoom(self):
        src = (Path(__file__).resolve().parents[3] / "editor/js/app.js").read_text()
        assert "function placementResolution" in src
        assert "/ zoom" in src
