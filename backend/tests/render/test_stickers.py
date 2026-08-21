"""Stickers: registry-validated in layouts, deterministic in print PDFs,
present in previews."""
import io

import pytest
from PIL import Image
from pydantic import ValidationError

from app.render.cover import build_cover_pdf
from app.render.interior import STICKER_DIR, build_pdf
from app.render.preview import render_preview_cover, render_preview_page
from app.schemas.layout import LayoutDoc, PageDoc, StickerDoc


def sticker(sticker_id="heart", **over):
    doc = {"id": "s1", "sticker_id": sticker_id,
           "x_mm": 74, "y_mm": 105, "w_mm": 40, "rotation": 0}
    doc.update(over)
    return doc


def page_with(stickers):
    return {"index": 0, "bg_color": "#ffffff", "placements": [],
            "texts": [], "stickers": stickers}


class TestSchema:
    def test_known_sticker_accepted(self):
        StickerDoc.model_validate(sticker())

    def test_unknown_sticker_rejected(self):
        with pytest.raises(ValidationError, match="unknown sticker"):
            StickerDoc.model_validate(sticker("giphy-cat"))

    def test_layout_roundtrip_keeps_stickers(self):
        doc = LayoutDoc(pages=[PageDoc(index=0)])
        doc.pages[0].stickers = [StickerDoc.model_validate(sticker())]
        doc.cover.stickers = [StickerDoc.model_validate(sticker("airplane"))]
        dumped = doc.model_dump()
        again = LayoutDoc.model_validate(dumped)
        assert again.pages[0].stickers[0].sticker_id == "heart"
        assert again.cover.stickers[0].sticker_id == "airplane"

    def test_every_registry_asset_exists(self):
        from app.domain.stickers import STICKERS

        for sticker_id in STICKERS:
            assert (STICKER_DIR / f"{sticker_id}.png").is_file(), sticker_id


class TestInteriorPdf:
    def test_sticker_changes_output_and_stays_deterministic(self):
        plain = build_pdf([page_with([])], lambda pid: b"")
        once = build_pdf([page_with([sticker()])], lambda pid: b"")
        twice = build_pdf([page_with([sticker()])], lambda pid: b"")
        assert once != plain
        assert once == twice
        assert len(once) > len(plain)  # embedded PNG with alpha

    def test_rotated_and_offpage_stickers_render(self):
        stickers = [sticker(rotation=33.5),
                    sticker("star", id="s2", x_mm=-10, y_mm=2, w_mm=25)]
        pdf = build_pdf([page_with(stickers)], lambda pid: b"")
        assert pdf.startswith(b"%PDF")


class TestCoverPdf:
    def test_cover_sticker_renders(self):
        cover = {"title": "T", "bg_color": "#ffffff",
                 "stickers": [sticker("balloon")]}
        plain = build_cover_pdf({"title": "T", "bg_color": "#ffffff"}, 16, None)
        with_sticker = build_cover_pdf(cover, 16, None)
        assert with_sticker.startswith(b"%PDF")
        assert with_sticker != plain


class TestPreview:
    def test_page_preview_shows_sticker(self):
        plain = render_preview_page(page_with([]), {})
        with_sticker = render_preview_page(page_with([sticker(w_mm=80)]), {})
        assert with_sticker != plain
        Image.open(io.BytesIO(with_sticker)).load()  # valid JPEG

    def test_cover_preview_shows_sticker(self):
        plain = render_preview_cover({"bg_color": "#ffffff"}, None)
        with_sticker = render_preview_cover(
            {"bg_color": "#ffffff", "stickers": [sticker("sun", w_mm=60)]},
            None)
        assert with_sticker != plain


class TestMultiPhotoPages:
    """Layout slots reach the print PDF: the renderer has always looped over
    `placements`, so a grid page needs no renderer change — lock that in."""

    def test_grid_page_renders_every_slot(self):
        from app.domain.layouts import LAYOUTS
        from app.render.compose import compose_page
        from tests.services.test_image_processing import jpeg_bytes

        photos = {f"p{i}": jpeg_bytes(900, 700) for i in range(4)}
        grid = {"index": 0, "bg_color": "#ffffff", "texts": [], "stickers": [],
                "placements": [{"photo_id": f"p{i}", **slot, "rotation": 0,
                                "fit": "cover"}
                               for i, slot in enumerate(LAYOUTS["four"])]}
        single = {"index": 0, "bg_color": "#ffffff", "texts": [], "stickers": [],
                  "placements": [{"photo_id": "p0", **LAYOUTS["full"][0],
                                  "rotation": 0, "fit": "cover"}]}
        four_up = compose_page(grid, photos, scale=0.25)
        one_up = compose_page(single, photos, scale=0.25)
        assert four_up != one_up
        assert compose_page(grid, photos, scale=0.25) == four_up   # deterministic

    def test_partially_filled_grid_leaves_page_colour(self):
        from app.domain.layouts import LAYOUTS
        from app.render.compose import compose_page
        from tests.services.test_image_processing import jpeg_bytes

        page = {"index": 0, "bg_color": "#1d4d85", "texts": [], "stickers": [],
                "placements": [{"photo_id": "p0", **LAYOUTS["four"][0],
                                "rotation": 0, "fit": "cover"}]}
        out = compose_page(page, {"p0": jpeg_bytes(900, 700)}, scale=0.25)
        assert out.startswith(b"\xff\xd8")     # a valid JPEG, empty slots and all


def gradient_jpeg(w: int, h: int) -> bytes:
    """A photo that actually varies across both axes — a flat colour would
    make every crop look identical and prove nothing."""
    from PIL import Image

    img = Image.new("RGB", (w, h))
    img.putdata([(x * 255 // max(1, w - 1), y * 255 // max(1, h - 1),
                  (x + y) % 256) for y in range(h) for x in range(w)])
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=95)
    return out.getvalue()


class TestCropControl:
    """zoom/focus give the customer the crop; defaults must not disturb any
    book laid out before the fields existed."""

    def _page(self, **crop):
        from app.domain.layouts import LAYOUTS
        return {"index": 0, "bg_color": "#ffffff", "texts": [], "stickers": [],
                "placements": [{"photo_id": "p0", **LAYOUTS["four"][0],
                                "rotation": 0, "fit": "cover", **crop}]}

    def test_defaults_match_a_plain_centred_crop(self):
        from app.render.compose import compose_page

        photos = {"p0": gradient_jpeg(1600, 900)}   # wide photo, tall slot
        bare = compose_page(self._page(), photos, scale=0.25)
        explicit = compose_page(
            self._page(zoom=1.0, focus_x=0.5, focus_y=0.5), photos, scale=0.25)
        assert bare == explicit

    def test_focus_and_zoom_change_the_printed_crop(self):
        from app.render.compose import compose_page

        photos = {"p0": gradient_jpeg(1600, 900)}
        centre = compose_page(self._page(), photos, scale=0.25)
        left = compose_page(self._page(focus_x=0.0), photos, scale=0.25)
        right = compose_page(self._page(focus_x=1.0), photos, scale=0.25)
        zoomed = compose_page(self._page(zoom=2.0), photos, scale=0.25)
        assert len({centre, left, right, zoomed}) == 4
        # Deterministic: the same crop renders the same bytes.
        assert compose_page(self._page(focus_x=0.0), photos, scale=0.25) == left

    def test_crop_never_leaves_a_gap(self):
        from PIL import Image

        from app.render.compose import _fit_cover

        img = Image.open(io.BytesIO(gradient_jpeg(1600, 900))).convert("RGB")
        for zoom in (1.0, 1.37, 4.0):
            for fx, fy in ((0.0, 0.0), (0.5, 0.5), (1.0, 1.0)):
                out = _fit_cover(img, 301, 407, zoom=zoom, focus_x=fx, focus_y=fy)
                assert out.size == (301, 407), (zoom, fx, fy)
