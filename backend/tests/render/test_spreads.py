"""A photo across the fold (A62).

Pages are rendered one at a time, so such a photo lives on both pages as the
same rectangle shifted by one trim width. What matters is that the two
printed halves meet at the fold with nothing repeated and nothing missing.
"""
import io

import pytest
from PIL import Image

from app.domain.geometry import (
    BLEED_MM,
    SPREAD_W_MM,
    TRIM_H_MM,
    TRIM_W_MM,
    RectMM,
    mm_to_px,
    validate_placement,
)
from app.render.compose import compose_page
from app.schemas.layout import PlacementDoc

# Full-spread photo: from the left page's bleed edge to the right page's.
LEFT = {"x_mm": -BLEED_MM, "y_mm": -BLEED_MM,
        "w_mm": SPREAD_W_MM, "h_mm": TRIM_H_MM + 2 * BLEED_MM}
RIGHT = {**LEFT, "x_mm": -BLEED_MM - TRIM_W_MM}


def ramp_jpeg(w: int, h: int) -> bytes:
    """A left-to-right ramp: any duplicated or dropped column at the fold
    shows up as a break in an otherwise steady climb."""
    img = Image.new("RGB", (w, h))
    img.putdata([(x * 255 // max(1, w - 1), 128, 128)
                 for _ in range(h) for x in range(w)])
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=100, subsampling=0)
    return out.getvalue()


def page_with(rect: dict) -> dict:
    return {"index": 0, "bg_color": "#ffffff", "texts": [], "stickers": [],
            "placements": [{"photo_id": "p", **rect, "rotation": 0,
                            "fit": "cover", "spread_id": "s1"}]}


class TestGeometry:
    def test_a_photo_may_hang_over_the_fold(self):
        for rect in (LEFT, RIGHT):
            validate_placement(RectMM(x=rect["x_mm"], y=rect["y_mm"],
                                      w=rect["w_mm"], h=rect["h_mm"]))

    def test_a_photo_entirely_off_the_page_is_rejected(self):
        with pytest.raises(Exception, match="does not touch this page"):
            validate_placement(RectMM(x=TRIM_W_MM + 50, y=0, w=100, h=100))

    def test_nothing_may_be_wider_than_a_spread(self):
        with pytest.raises(Exception, match="larger than a spread"):
            validate_placement(RectMM(x=-BLEED_MM, y=-BLEED_MM,
                                      w=SPREAD_W_MM + 1, h=TRIM_H_MM))

    def test_a_page_still_cannot_run_off_the_top_or_bottom(self):
        with pytest.raises(Exception, match="outside the canvas"):
            validate_placement(RectMM(x=0, y=-BLEED_MM - 1, w=50, h=50))

    def test_both_halves_validate_through_the_schema(self):
        for rect in (LEFT, RIGHT):
            PlacementDoc.model_validate({"photo_id": "p", **rect,
                                         "spread_id": "s1"})

    def test_spread_id_is_optional_and_absent_by_default(self):
        doc = PlacementDoc.model_validate(
            {"photo_id": "p", "x_mm": 0, "y_mm": 0, "w_mm": 50, "h_mm": 50})
        assert doc.spread_id is None


class TestTheFoldJoins:
    def _raster(self, page: dict, photo: bytes) -> Image.Image:
        img = Image.open(io.BytesIO(compose_page(page, {"p": photo}, scale=1.0)))
        img.load()
        return img

    def test_the_two_halves_meet_with_no_seam(self):
        """The right page must continue the left one exactly one trim width
        along: where the two rasters overlap they have to show the same
        pixels, which is precisely what makes the fold invisible."""
        photo = ramp_jpeg(3600, 2600)
        left = self._raster(page_with(LEFT), photo)
        right = self._raster(page_with(RIGHT), photo)
        shift = mm_to_px(TRIM_W_MM)
        assert shift == 1748

        overlap = left.width - shift          # columns present on both pages
        assert overlap > 0
        for row in (left.height // 4, left.height // 2, 3 * left.height // 4):
            for x in range(0, overlap, 7):
                got = right.getpixel((x, row))
                want = left.getpixel((x + shift, row))
                # Each page is JPEG-encoded separately, so allow codec noise.
                assert all(abs(a - b) <= 4 for a, b in zip(got, want)), (
                    f"fold breaks at column {x}, row {row}: {got} vs {want}")

        # And the photo really does travel across the spread, rather than
        # each page quietly showing the same crop.
        row = left.height // 2
        left_trim = left.getpixel((mm_to_px(BLEED_MM) + 20, row))[0]
        right_trim = right.getpixel((mm_to_px(BLEED_MM + TRIM_W_MM) - 20, row))[0]
        assert right_trim - left_trim > 180

    def test_each_half_still_renders_deterministically(self):
        photo = ramp_jpeg(1200, 900)
        once = compose_page(page_with(LEFT), {"p": photo}, scale=0.25)
        twice = compose_page(page_with(LEFT), {"p": photo}, scale=0.25)
        assert once == twice
        assert once != compose_page(page_with(RIGHT), {"p": photo}, scale=0.25)
