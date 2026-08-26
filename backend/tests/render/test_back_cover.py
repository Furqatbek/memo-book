"""A91: photos on the back cover panel.

The back was a flat colour and nothing else. It now takes the same slot grid
an interior page uses, which means the only genuinely new thing is geometry:
where a back-panel rectangle lands on the wrap sheet.

That geometry is the *mirror* of the front's, and mirrors are exactly the
kind of thing that gets written once and reflected wrong. The front bleeds
right (into the turn-in) and stops left (at the spine fold); the back must
bleed left and stop right. Get it backwards and art crosses the spine onto
the other face of the closed book — visible on every copy, invisible on
screen until someone folds one.
"""
import io

import pytest
from PIL import Image

from app.render.cover import (
    WRAP_MM,
    back_box_px,
    cover_geometry,
    photo_box_px,
    _compose_cover_raster,
)
from app.domain.geometry import TRIM_H_MM, TRIM_W_MM, mm_to_px
from app.domain.layouts import LAYOUTS
from app.schemas.layout import CoverDoc, LayoutDoc

PAGES = 32
FULL_SLOT = LAYOUTS["full"][0]          # the bleed-off-every-edge slot


@pytest.fixture
def geo():
    return cover_geometry(PAGES)


def _sheet(geo):
    return mm_to_px(geo.total_w_mm), mm_to_px(geo.total_h_mm)


def photo(color, size=(900, 1200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG", quality=90)
    return buf.getvalue()


class TestTheMirror:
    def test_a_full_bleed_slot_reaches_the_left_edge_of_the_sheet(self, geo):
        w, h = _sheet(geo)
        left, top, right, bottom = back_box_px(FULL_SLOT, geo, w, h)
        assert left == 0, "the back's outer edge is a turn-in; art bleeds into it"
        assert top == 0 and bottom == h, "head and foot turn in on both panels"

    def test_and_stops_dead_at_the_spine_fold(self, geo):
        w, h = _sheet(geo)
        _, _, right, _ = back_box_px(FULL_SLOT, geo, w, h)
        spine_fold = mm_to_px(WRAP_MM + TRIM_W_MM)
        assert right == spine_fold, (
            "art past the spine fold appears on the front of the closed book")
        assert right < mm_to_px(geo.front_x0_mm), "and never reaches the front panel"

    def test_it_is_the_exact_mirror_of_the_front(self, geo):
        """What the front loses on the left, the back loses on the right."""
        w, h = _sheet(geo)
        fl, _, fr, _ = photo_box_px(FULL_SLOT, geo, w, h)
        bl, _, br, _ = back_box_px(FULL_SLOT, geo, w, h)
        front_bleeds_right = w - fr
        back_bleeds_left = bl
        front_stops_left = fl - mm_to_px(geo.front_x0_mm)
        back_stops_right = mm_to_px(WRAP_MM + TRIM_W_MM) - br
        assert front_bleeds_right == back_bleeds_left == 0
        assert front_stops_left == back_stops_right == 0

    def test_an_inset_slot_is_placed_inside_the_back_panel(self, geo):
        w, h = _sheet(geo)
        inset = LAYOUTS["inset"][0]
        left, top, right, bottom = back_box_px(inset, geo, w, h)
        assert left == mm_to_px(WRAP_MM + inset["x_mm"])
        assert right == mm_to_px(WRAP_MM + inset["x_mm"] + inset["w_mm"])
        assert top == mm_to_px(WRAP_MM + inset["y_mm"])
        assert bottom == mm_to_px(WRAP_MM + inset["y_mm"] + inset["h_mm"])


class TestWhatActuallyPrints:
    def _raster(self, cover, back_bytes=None):
        geo = cover_geometry(PAGES)
        return Image.open(io.BytesIO(
            _compose_cover_raster(cover, geo, None, None, back_bytes)))

    def test_a_back_photo_paints_the_back_panel_and_nothing_else(self):
        geo = cover_geometry(PAGES)
        cover = {"bg_color": "#ffffff", "title": "",
                 "back": {"layout": "full",
                          "placements": [dict(FULL_SLOT, photo_id="p1")]}}
        im = self._raster(cover, {"p1": photo((255, 0, 0))}).convert("RGB")

        back_mid = (mm_to_px(WRAP_MM + TRIM_W_MM / 2), im.height // 2)
        spine_mid = (mm_to_px(WRAP_MM + TRIM_W_MM + geo.spine_mm / 2), im.height // 2)
        front_mid = (mm_to_px(geo.front_x0_mm + TRIM_W_MM / 2), im.height // 2)

        assert im.getpixel(back_mid)[0] > 200 and im.getpixel(back_mid)[1] < 60, \
            "the back panel should carry the photo"
        assert im.getpixel(spine_mid) == (255, 255, 255), "the spine stays flat colour"
        assert im.getpixel(front_mid) == (255, 255, 255), "and so does the front"

    def test_an_empty_back_changes_nothing_at_all(self):
        """Every book made before this existed has no `back` key. Rendering
        must be byte-identical, not merely similar."""
        base = {"bg_color": "#123456", "title": ""}
        without = _compose_cover_raster(base, cover_geometry(PAGES), None, None)
        with_empty = _compose_cover_raster(
            dict(base, back={"layout": "full", "placements": []}),
            cover_geometry(PAGES), None, None, {})
        assert without == with_empty

    def test_a_missing_photo_is_refused_rather_than_silently_skipped(self):
        from app.render.compose import RenderError
        cover = {"bg_color": "#ffffff", "title": "",
                 "back": {"layout": "full",
                          "placements": [dict(FULL_SLOT, photo_id="gone")]}}
        with pytest.raises(RenderError, match="gone"):
            _compose_cover_raster(cover, cover_geometry(PAGES), None, None, {})


class TestTheSchema:
    def test_a_layout_without_a_back_key_still_validates(self):
        doc = LayoutDoc.model_validate({"version": 1, "cover": {}, "pages": []})
        assert doc.cover.back.placements == []
        assert doc.cover.back.layout == "full"

    def test_the_back_accepts_the_same_slots_a_page_does(self):
        cover = CoverDoc.model_validate({
            "back": {"layout": "four",
                     "placements": [dict(s, photo_id=f"p{i}")
                                    for i, s in enumerate(LAYOUTS["four"])]}})
        assert len(cover.back.placements) == 4

    def test_an_unknown_layout_is_refused(self):
        with pytest.raises(ValueError, match="unknown back cover layout"):
            CoverDoc.model_validate({"back": {"layout": "not-a-grid"}})

    def test_too_many_photos_is_refused(self):
        from app.domain.layouts import MAX_PLACEMENTS_PER_PAGE
        too_many = [dict(LAYOUTS["full"][0], photo_id=f"p{i}")
                    for i in range(MAX_PLACEMENTS_PER_PAGE + 1)]
        with pytest.raises(ValueError, match="at most"):
            CoverDoc.model_validate({"back": {"placements": too_many}})

    def test_the_back_survives_a_round_trip(self):
        src = {"version": 1, "pages": [],
               "cover": {"bg_color": "#101010",
                         "back": {"layout": "two-h",
                                  "placements": [dict(LAYOUTS["two-h"][0],
                                                      photo_id="p1")]}}}
        out = LayoutDoc.model_validate(src).model_dump()
        assert out["cover"]["back"]["layout"] == "two-h"
        assert out["cover"]["back"]["placements"][0]["photo_id"] == "p1"
