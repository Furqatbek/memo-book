"""Milestone 10: hardcover wrap geometry, art placement, determinism."""
import io

import fitz
import pytest
from PIL import Image
from pypdf import PdfReader

from app.config import get_settings
from app.render.cover import WRAP_MM, build_cover_pdf, cover_geometry
from tests.render.helpers import solid_jpeg

MM_TO_PT = 72 / 25.4

COVER = {"photo_id": "x", "title": "Italy 2026", "subtitle": "June",
         "title_font": "Inter", "title_size_pt": 28}


def spine_for(tier: int) -> float:
    s = get_settings()
    return {16: s.spine_mm_16, 32: s.spine_mm_32,
            48: s.spine_mm_48, 96: s.spine_mm_96}[tier]


class TestGeometry:
    @pytest.mark.parametrize("tier", [16, 32, 48, 96])
    def test_total_width_tracks_spine(self, tier):
        geo = cover_geometry(tier)
        expected_w = 2 * WRAP_MM + 2 * 148.0 + spine_for(tier)
        assert abs(geo.total_w_mm - expected_w) < 1e-9
        assert abs(geo.total_h_mm - (210.0 + 2 * WRAP_MM)) < 1e-9

    @pytest.mark.parametrize("tier", [16, 96])
    def test_pdf_page_matches_geometry(self, tier):
        pdf = build_cover_pdf(COVER, tier, solid_jpeg(1200, 900, (180, 30, 30)),
                              cache_tag=f"test-{tier}")
        reader = PdfReader(io.BytesIO(pdf))
        assert len(reader.pages) == 1
        page = reader.pages[0]
        geo = cover_geometry(tier)
        assert abs(float(page.mediabox.width) / MM_TO_PT - geo.total_w_mm) < 0.1
        assert abs(float(page.mediabox.height) / MM_TO_PT - geo.total_h_mm) < 0.1


class TestArtPlacement:
    def test_photo_on_front_panel_back_stays_white(self):
        pdf = build_cover_pdf(COVER, 16, solid_jpeg(1200, 900, (180, 30, 30)),
                              cache_tag="test-art")
        doc = fitz.open(stream=pdf, filetype="pdf")
        pix = doc[0].get_pixmap(dpi=36)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        geo = cover_geometry(16)

        front_x = int(img.width * (geo.front_x0_mm + 74) / geo.total_w_mm)
        back_x = int(img.width * (WRAP_MM + 74) / geo.total_w_mm)
        y = img.height // 2
        fr, _, fb = img.getpixel((front_x, y))
        br, bg, bb = img.getpixel((back_x, y))
        assert fr > 120 and fb < 90        # front shows the red photo
        assert br > 240 and bg > 240 and bb > 240  # back panel stays white

    def test_title_text_present(self):
        pdf = build_cover_pdf(COVER, 16, solid_jpeg(1200, 900, (180, 30, 30)),
                              cache_tag="test-text")
        doc = fitz.open(stream=pdf, filetype="pdf")
        text = doc[0].get_text()
        assert "Italy 2026" in text
        assert "June" in text

    def test_no_photo_renders_dark_text_on_white(self):
        pdf = build_cover_pdf(COVER, 16, None, cache_tag="test-nophoto")
        doc = fitz.open(stream=pdf, filetype="pdf")
        assert "Italy 2026" in doc[0].get_text()


class TestDeterminism:
    def test_byte_identical_across_runs(self):
        photo = solid_jpeg(1200, 900, (180, 30, 30))
        first = build_cover_pdf(COVER, 32, photo, cache_tag="det")
        second = build_cover_pdf(COVER, 32, photo, cache_tag="det")
        assert first == second
