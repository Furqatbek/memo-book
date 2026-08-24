"""Milestone 10: hardcover wrap geometry, art placement, determinism."""
import io

import fitz
import pytest
from PIL import Image
from pypdf import PdfReader

from app.config import get_settings
from app.domain.cover_templates import (
    COVER_TEMPLATE_IDS,
    FULL_RECT,
    apply_cover_template,
)
from app.domain.geometry import TRIM_H_MM, mm_to_px
from app.domain.tiers import page_tiers, pages_for_sheets, sides_per_sheet
from app.render.cover import (
    WRAP_MM,
    auto_title_color,
    build_cover_pdf,
    cover_geometry,
    photo_box_px,
    spine_mm_for_tier,
    title_over_photo,
)
from tests.render.helpers import solid_jpeg

MM_TO_PT = 72 / 25.4

COVER = {"photo_id": "x", "title": "Italy 2026", "subtitle": "June",
         "title_font": "Inter", "title_size_pt": 28}


def spine_for(page_count: int) -> float:
    """The rule, stated independently of the code under test: the SPINE_MM_*
    table is indexed by sheets of paper, and a sheet carries two printed
    sides, so a 32-page book is the 16-sheet entry (A63)."""
    s = get_settings()
    table = {16: s.spine_mm_16, 32: s.spine_mm_32,
             48: s.spine_mm_48, 96: s.spine_mm_96}
    return table[page_count // sides_per_sheet()]


class TestGeometry:
    @pytest.mark.parametrize("tier", page_tiers())
    def test_total_width_tracks_spine(self, tier):
        geo = cover_geometry(tier)
        expected_w = 2 * WRAP_MM + 2 * 148.0 + spine_for(tier)
        assert abs(geo.total_w_mm - expected_w) < 1e-9
        assert abs(geo.total_h_mm - (210.0 + 2 * WRAP_MM)) < 1e-9

    @pytest.mark.parametrize("tier", [page_tiers()[0], page_tiers()[-1]])
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


class TestSpineFollowsSheets:
    """A63 made the customer's tier a count of SHEETS, and sheets of paper are
    what make a spine thick. The lookup missed that: two of the four live
    tiers raised RenderError, so those books could not have a cover printed
    at all — discovered only after the customer had paid."""

    @pytest.mark.parametrize("page_count", page_tiers())
    def test_every_live_tier_has_a_spine(self, page_count):
        assert spine_mm_for_tier(page_count) > 0
        assert cover_geometry(page_count).spine_mm > 0

    @pytest.mark.parametrize("page_count", page_tiers())
    def test_every_live_tier_renders_a_cover(self, page_count):
        pdf = build_cover_pdf(COVER, page_count,
                              solid_jpeg(900, 700, (40, 90, 160)),
                              cache_tag=f"spine-{page_count}")
        assert pdf.startswith(b"%PDF-")

    def test_the_spine_is_keyed_by_sheets_not_printed_sides(self):
        s = get_settings()
        # A 16-sheet book is 32 pages; its spine is the 16-sheet figure.
        assert spine_mm_for_tier(pages_for_sheets(16)) == s.spine_mm_16
        assert spine_mm_for_tier(pages_for_sheets(96)) == s.spine_mm_96

    def test_a_thicker_book_never_gets_a_thinner_spine(self):
        spines = [spine_mm_for_tier(pc) for pc in page_tiers()]
        assert spines == sorted(spines)

    def test_an_unknown_tier_still_refuses_loudly(self):
        with pytest.raises(Exception, match="no spine width configured"):
            spine_mm_for_tier(7)


class TestTemplatesOnTheSheet:
    """A70: the template's rectangle is where the photo really lands, and a
    cover saved before templates existed renders exactly as it did."""

    TIER = 32   # the 16-sheet book

    def _front(self, cover: dict, tag: str) -> Image.Image:
        pdf = build_cover_pdf(cover, self.TIER, solid_jpeg(1400, 1000, (200, 40, 40)),
                              cache_tag=tag)
        doc = fitz.open(stream=pdf, filetype="pdf")
        pix = doc[0].get_pixmap(dpi=72)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    def _at(self, img: Image.Image, geo, x_mm: float, y_mm: float):
        """Sample the front panel at trim-origin mm."""
        return img.getpixel((
            int(img.width * (geo.front_x0_mm + x_mm) / geo.total_w_mm),
            int(img.height * (geo.wrap_mm + y_mm) / geo.total_h_mm)))

    def _is_photo(self, px) -> bool:
        r, g, b = px
        return r > 120 and g < 110 and b < 110

    @pytest.mark.parametrize("name", COVER_TEMPLATE_IDS)
    def test_the_photo_lands_inside_its_rectangle_and_not_outside(self, name):
        cover = apply_cover_template(
            {"title": "Italy 2026", "bg_color": "#ffffff"}, name)
        geo = cover_geometry(self.TIER)
        img = self._front(cover, f"tpl-{name}")
        rect = cover["photo_rect"]

        centre = self._at(img, geo, rect["x_mm"] + rect["w_mm"] / 2,
                          rect["y_mm"] + rect["h_mm"] / 2)
        assert self._is_photo(centre), f"{name}: no photo inside the frame"

        # Somewhere the template leaves bare must show the background.
        if rect["y_mm"] + rect["h_mm"] < TRIM_H_MM - 6:
            below = self._at(img, geo, 74, rect["y_mm"] + rect["h_mm"] + 5)
            assert not self._is_photo(below), f"{name}: photo spills below the frame"
        if rect["x_mm"] > 6:
            beside = self._at(img, geo, rect["x_mm"] / 2, rect["y_mm"] + 10)
            assert not self._is_photo(beside), f"{name}: photo spills left of the frame"

    def test_the_back_panel_is_never_touched(self):
        geo = cover_geometry(self.TIER)
        for name in COVER_TEMPLATE_IDS:
            cover = apply_cover_template({"bg_color": "#ffffff"}, name)
            img = self._front(cover, f"back-{name}")
            x = int(img.width * (WRAP_MM + 74) / geo.total_w_mm)
            r, g, b = img.getpixel((x, img.height // 2))
            assert r > 240 and g > 240 and b > 240, f"{name}: art crossed the spine"

    def test_a_cover_from_before_templates_is_byte_identical(self):
        """The whole compatibility promise in one assertion: no template, no
        rectangle, no framing fields — the exact document shape already in
        the database."""
        legacy = dict(COVER)
        photo = solid_jpeg(1200, 900, (180, 30, 30))
        before = build_cover_pdf(legacy, self.TIER, photo, cache_tag="legacy")
        after = build_cover_pdf({**legacy, "template": "full",
                                 "photo_rect": None}, self.TIER, photo,
                                cache_tag="legacy")
        assert before == after

    def test_full_bleed_matches_the_original_hand_written_paste(self):
        photo = solid_jpeg(1200, 900, (180, 30, 30))
        legacy = build_cover_pdf(dict(COVER), self.TIER, photo, cache_tag="fb")
        templated = build_cover_pdf(
            apply_cover_template(dict(COVER), "full"), self.TIER, photo,
            cache_tag="fb")
        # Same photo box; only the title moved to the template's position.
        assert len(legacy) > 0 and len(templated) > 0
        geo = cover_geometry(self.TIER)
        w_px, h_px = mm_to_px(geo.total_w_mm), mm_to_px(geo.total_h_mm)
        assert photo_box_px(FULL_RECT, geo, w_px, h_px) == (
            mm_to_px(geo.front_x0_mm), 0, w_px, h_px)


class TestTitleInk:
    def test_white_over_a_photo_dark_ink_beside_one(self):
        geo = cover_geometry(32)
        full = apply_cover_template({"photo_id": "p"}, "full")
        window = apply_cover_template({"photo_id": "p"}, "window")
        assert title_over_photo(full, geo, has_photo=True) is True
        assert title_over_photo(window, geo, has_photo=True) is False

    def test_no_photo_is_never_over_a_photo(self):
        geo = cover_geometry(32)
        assert title_over_photo(apply_cover_template({}, "full"), geo,
                                has_photo=False) is False

    def test_auto_ink_stays_readable_on_the_occasion_colours(self):
        # The dark cover colours the occasion themes set used to get #1a1a1a.
        for dark in ("#7a2740", "#1d4d85", "#5b2d86"):
            assert auto_title_color(dark) == "#ffffff"
        for light in ("#ffffff", "#fef3cd", "#eceff4"):
            assert auto_title_color(light) == "#1a1a1a"


class TestDesignArtwork:
    """A71: a ready-made design's artwork prints across the front panel and
    its turn-in, leaving the back panel and spine on the flat colour — which
    is what lets one artwork file serve every page tier."""

    TIER = 32

    def _front(self, cover: dict, tag: str, artwork: bytes | None,
               photo: bytes | None = None) -> Image.Image:
        pdf = build_cover_pdf(cover, self.TIER, photo, cache_tag=tag,
                              artwork_bytes=artwork)
        doc = fitz.open(stream=pdf, filetype="pdf")
        pix = doc[0].get_pixmap(dpi=72)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    def _at(self, img, geo, x_mm, y_mm):
        return img.getpixel((
            int(img.width * (geo.front_x0_mm + x_mm) / geo.total_w_mm),
            int(img.height * (geo.wrap_mm + y_mm) / geo.total_h_mm)))

    def test_artwork_covers_the_whole_front_panel(self):
        art = solid_jpeg(1937, 2858, (20, 160, 60))
        cover = {"title": "", "bg_color": "#ffffff"}
        geo = cover_geometry(self.TIER)
        img = self._front(cover, "art-front", art)
        for x, y in ((10, 10), (74, 105), (140, 200)):
            r, g, b = self._at(img, geo, x, y)
            assert g > 120 and r < 110, f"artwork missing at {x},{y}mm"

    def test_the_back_panel_and_spine_keep_the_flat_colour(self):
        art = solid_jpeg(1937, 2858, (20, 160, 60))
        geo = cover_geometry(self.TIER)
        img = self._front({"bg_color": "#ffffff"}, "art-back", art)
        back_x = int(img.width * (WRAP_MM + 74) / geo.total_w_mm)
        r, g, b = img.getpixel((back_x, img.height // 2))
        assert r > 240 and g > 240 and b > 240, "artwork crossed onto the back"

    def test_one_artwork_file_serves_every_page_tier(self):
        """The spine grows with the tier; the artwork must not be stretched
        or shifted onto the wrong panel because of it."""
        art = solid_jpeg(1937, 2858, (20, 160, 60))
        for tier in page_tiers():
            geo = cover_geometry(tier)
            pdf = build_cover_pdf({"bg_color": "#ffffff"}, tier, None,
                                  cache_tag=f"art-tier-{tier}", artwork_bytes=art)
            doc = fitz.open(stream=pdf, filetype="pdf")
            pix = doc[0].get_pixmap(dpi=48)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            r, g, b = self._at(img, geo, 74, 105)
            assert g > 120 and r < 110, f"tier {tier}: artwork off the front"
            back = img.getpixel((int(img.width * (WRAP_MM + 74) / geo.total_w_mm),
                                 img.height // 2))
            assert min(back) > 240, f"tier {tier}: artwork crossed the spine"

    def test_the_customers_photo_sits_on_top_of_the_artwork(self):
        art = solid_jpeg(1937, 2858, (20, 160, 60))
        photo = solid_jpeg(1400, 1000, (200, 40, 40))
        cover = apply_cover_template({"bg_color": "#ffffff"}, "polaroid")
        geo = cover_geometry(self.TIER)
        img = self._front(cover, "art-photo", art, photo)
        rect = cover["photo_rect"]
        inside = self._at(img, geo, rect["x_mm"] + rect["w_mm"] / 2,
                          rect["y_mm"] + rect["h_mm"] / 2)
        assert inside[0] > 120 and inside[1] < 110, "photo not drawn over artwork"
        outside = self._at(img, geo, 74, 195)
        assert outside[1] > 120, "artwork missing where the photo does not reach"

    def test_no_artwork_renders_exactly_as_before(self):
        photo = solid_jpeg(1200, 900, (180, 30, 30))
        plain = build_cover_pdf(dict(COVER), self.TIER, photo, cache_tag="noart")
        explicit = build_cover_pdf(dict(COVER), self.TIER, photo,
                                   cache_tag="noart", artwork_bytes=None)
        assert plain == explicit

    def test_unreadable_artwork_fails_loudly_rather_than_printing_blank(self):
        with pytest.raises(Exception, match="unreadable cover artwork"):
            build_cover_pdf({"bg_color": "#ffffff"}, self.TIER, None,
                            cache_tag="art-bad", artwork_bytes=b"not an image")

    def test_a_title_over_artwork_gets_the_white_treatment(self):
        """Artwork fills the front, so a title anywhere on it is over a
        picture — dark ink chosen from the background colour would be a
        coincidence, not a decision."""
        art = solid_jpeg(1937, 2858, (10, 20, 30))
        cover = apply_cover_template({"title": "Our travels",
                                      "bg_color": "#ffffff"}, "window")
        geo = cover_geometry(self.TIER)
        img = self._front(cover, "art-title", art)
        # Scan the block, not one row: text is drawn from a baseline, so the
        # glyphs sit above the centre the template names.
        cy = cover["title_y_mm"]
        band = [self._at(img, geo, x, y)
                for x in range(35, 115, 3)
                for y in range(int(cy) - 9, int(cy) + 3)]
        assert any(min(px) > 150 for px in band), "no light title over dark artwork"
