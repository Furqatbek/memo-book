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
