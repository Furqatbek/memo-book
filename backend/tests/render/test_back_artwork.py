"""A95: a cover design may carry artwork for the BACK panel too.

Until now a design was one file — the front — and the back printed in a flat
colour. A design can now carry a second file, and the thing that can go wrong
is the same thing that could go wrong in A91: the back is the *mirror* of the
front, and a mirror written from memory comes out backwards.

Backwards here is not a cosmetic bug. Art that runs past the spine fold is
printed on the wrong face of the closed book: it appears on the front, over
the design, on every copy — and it looks perfectly fine on screen right up
until someone folds one.

So these tests assert where the ink lands, in pixels, on the real sheet.
"""
import io

import pytest
from PIL import Image

from app.domain.cover_templates import FULL_RECT
from app.domain.geometry import TRIM_W_MM, mm_to_px
from app.domain.layouts import LAYOUTS
from app.render.cover import WRAP_MM, _compose_cover_raster, cover_geometry

PAGES = 32
FULL_SLOT = LAYOUTS["full"][0]

FRONT = (255, 0, 0)      # red
BACK = (0, 0, 255)       # blue
SPINE = (0, 255, 0)      # green — the design's bg_color, which nothing covers
PHOTO = (255, 255, 0)    # yellow


def art(colour, size=(1937, 2858)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, "JPEG", quality=95)
    return buf.getvalue()


def close(got, want, tol=6) -> bool:
    """JPEG does not round-trip exactly; a channel within a few counts of the
    intended value is that colour and not a neighbouring panel's."""
    return all(abs(a - b) <= tol for a, b in zip(got, want))


@pytest.fixture
def geo():
    return cover_geometry(PAGES)


@pytest.fixture
def sheet(geo):
    """The whole wrap, front art and back art both present."""
    raster = _compose_cover_raster(
        {"bg_color": "#00ff00"}, geo, None,
        artwork_bytes=art(FRONT), back_artwork_bytes=art(BACK))
    img = Image.open(io.BytesIO(raster))
    img.load()
    return img.convert("RGB")


class TestWhereTheBackArtworkLands:
    def test_it_bleeds_off_the_left_edge_of_the_sheet(self, sheet):
        """The back's outer edge is a turn-in: it folds around the board, so
        the art has to run into it or a white line shows on the fold."""
        mid = sheet.height // 2
        assert close(sheet.getpixel((1, mid)), BACK)

    def test_it_bleeds_off_the_head_and_the_foot(self, sheet):
        x = mm_to_px(WRAP_MM + TRIM_W_MM / 2)
        assert close(sheet.getpixel((x, 1)), BACK)
        assert close(sheet.getpixel((x, sheet.height - 2)), BACK)

    def test_it_stops_dead_at_the_spine_fold(self, sheet):
        """The one that matters. A pixel of back art on the spine side of
        this line is a pixel printed on the front of the closed book."""
        mid = sheet.height // 2
        fold = mm_to_px(WRAP_MM + TRIM_W_MM)
        assert close(sheet.getpixel((fold - 3, mid)), BACK), "back panel"
        assert close(sheet.getpixel((fold + 3, mid)), SPINE), (
            "the back artwork crossed the spine fold")

    def test_the_spine_keeps_the_design_colour(self, sheet, geo):
        """The spine is in neither file, by design — that is what lets one
        pair of files serve all four book sizes."""
        mid = sheet.height // 2
        x = mm_to_px(WRAP_MM + TRIM_W_MM + geo.spine_mm / 2)
        assert close(sheet.getpixel((x, mid)), SPINE)

    def test_the_front_artwork_is_untouched(self, sheet, geo):
        mid = sheet.height // 2
        assert close(sheet.getpixel((mm_to_px(geo.front_x0_mm) + 3, mid)), FRONT)
        assert close(sheet.getpixel((sheet.width - 2, mid)), FRONT), (
            "the front still bleeds into its own turn-in")

    def test_the_two_panels_meet_only_at_the_spine(self, sheet, geo):
        """Sweep the whole width at mid-height: back, then spine, then front,
        in that order and with no stray band of the wrong colour."""
        mid = sheet.height // 2
        fold = mm_to_px(WRAP_MM + TRIM_W_MM)
        front0 = mm_to_px(geo.front_x0_mm)
        for x in range(0, fold - 2, 40):
            assert close(sheet.getpixel((x, mid)), BACK), f"x={x} is not back"
        for x in range(fold + 3, front0 - 2):
            assert close(sheet.getpixel((x, mid)), SPINE), f"x={x} is not spine"
        for x in range(front0 + 3, sheet.width, 40):
            assert close(sheet.getpixel((x, mid)), FRONT), f"x={x} is not front"


class TestItStaysOptional:
    def test_a_design_without_back_artwork_prints_a_flat_back(self, geo):
        """Every design that exists today. The back must look exactly as it
        did before this feature was written."""
        raster = _compose_cover_raster(
            {"bg_color": "#00ff00"}, geo, None, artwork_bytes=art(FRONT))
        img = Image.open(io.BytesIO(raster))
        img.load()
        img = img.convert("RGB")
        mid = img.height // 2
        assert close(img.getpixel((1, mid)), SPINE)
        assert close(img.getpixel((mm_to_px(WRAP_MM + TRIM_W_MM / 2), mid)), SPINE)


class TestTheCustomersPhotosSitOnTop:
    def test_a_back_photo_covers_the_back_artwork(self, geo):
        """Artwork is a backdrop, not a lid: a design can carry a decorated
        back AND a window for the customer's own photo."""
        cover = {"bg_color": "#00ff00",
                 "back": {"layout": "full",
                          "placements": [dict(FULL_SLOT, photo_id="p1")]}}
        raster = _compose_cover_raster(
            cover, geo, None, artwork_bytes=art(FRONT),
            back_photo_bytes={"p1": art(PHOTO, (900, 1200))},
            back_artwork_bytes=art(BACK))
        img = Image.open(io.BytesIO(raster))
        img.load()
        img = img.convert("RGB")
        mid = img.height // 2
        assert close(img.getpixel((mm_to_px(WRAP_MM + TRIM_W_MM / 2), mid)), PHOTO)

    def test_an_inset_photo_leaves_the_artwork_showing_around_it(self, geo):
        """The case the feature is actually for: a designed back with a
        framed photo on it, artwork visible in the margin."""
        inset = LAYOUTS["inset"][0]
        cover = {"bg_color": "#00ff00",
                 "back": {"layout": "inset",
                          "placements": [dict(inset, photo_id="p1")]}}
        raster = _compose_cover_raster(
            cover, geo, None, artwork_bytes=art(FRONT),
            back_photo_bytes={"p1": art(PHOTO, (900, 1200))},
            back_artwork_bytes=art(BACK))
        img = Image.open(io.BytesIO(raster))
        img.load()
        img = img.convert("RGB")
        mid = img.height // 2
        inside = mm_to_px(WRAP_MM + inset["x_mm"] + inset["w_mm"] / 2)
        margin = mm_to_px(WRAP_MM + inset["x_mm"] / 2)
        assert close(img.getpixel((inside, mid)), PHOTO), "the photo"
        assert close(img.getpixel((margin, mid)), BACK), (
            "the artwork, not the flat colour, fills the margin")


class TestTheRectItUses:
    def test_the_back_artwork_uses_the_whole_panel(self, geo):
        """It is pasted with FULL_RECT through `back_box_px`, the same
        rectangle a full-bleed back photo uses — so if that geometry is ever
        corrected, the artwork is corrected with it rather than left behind.
        """
        from app.render.cover import back_box_px

        w, h = mm_to_px(geo.total_w_mm), mm_to_px(geo.total_h_mm)
        assert back_box_px(FULL_RECT, geo, w, h) == back_box_px(FULL_SLOT, geo, w, h)
