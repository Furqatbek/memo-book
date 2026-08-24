"""A70: cover templates — geometry sanity, the editor mirror, and the
promise that applying one never destroys what the customer wrote."""
import json
import re
from pathlib import Path

import pytest

from app.domain.cover_templates import (
    COVER_TEMPLATE_IDS,
    COVER_TEMPLATES,
    DEFAULT_COVER_TEMPLATE,
    FULL_RECT,
    apply_cover_template,
    cover_template,
    photo_rect_for,
    title_on_photo,
)
from app.domain.geometry import SAFE_MARGIN_MM, TRIM_H_MM, TRIM_W_MM
from app.schemas.layout import CoverDoc

EDITOR_JS = Path(__file__).resolve().parents[3] / "editor/js/cover-templates.js"


class TestGeometry:
    @pytest.mark.parametrize("name", COVER_TEMPLATE_IDS)
    def test_the_photo_rectangle_is_on_the_front_panel(self, name):
        rect = COVER_TEMPLATES[name]["photo_rect"]
        assert rect["w_mm"] > 0 and rect["h_mm"] > 0
        assert rect["x_mm"] >= 0 and rect["y_mm"] >= 0
        assert rect["x_mm"] + rect["w_mm"] <= TRIM_W_MM + 0.01
        assert rect["y_mm"] + rect["h_mm"] <= TRIM_H_MM + 0.01

    @pytest.mark.parametrize("name", COVER_TEMPLATE_IDS)
    def test_the_photo_is_worth_printing(self, name):
        """A template that shrank the photo to a stamp would defeat the
        point of a photo book."""
        rect = COVER_TEMPLATES[name]["photo_rect"]
        share = (rect["w_mm"] * rect["h_mm"]) / (TRIM_W_MM * TRIM_H_MM)
        assert share > 0.25, f"{name}: photo is only {share:.0%} of the cover"

    @pytest.mark.parametrize("name", COVER_TEMPLATE_IDS)
    def test_the_title_sits_inside_the_safe_area(self, name):
        """Text near the trim is text the guillotine may take."""
        title = COVER_TEMPLATES[name]["title"]
        assert SAFE_MARGIN_MM <= title["x_mm"] <= TRIM_W_MM - SAFE_MARGIN_MM
        assert SAFE_MARGIN_MM <= title["y_mm"] <= TRIM_H_MM - SAFE_MARGIN_MM

    @pytest.mark.parametrize("name", COVER_TEMPLATE_IDS)
    def test_the_title_never_lands_on_a_photo_edge(self, name):
        """Either fully on the photo (white with a shadow) or clear of it
        (ink on the background) — straddling the boundary is the one place
        no colour choice reads well."""
        tpl = COVER_TEMPLATES[name]
        cover = {"photo_rect": tpl["photo_rect"]}
        rect = tpl["photo_rect"]
        cx, cy = tpl["title"]["x_mm"], tpl["title"]["y_mm"]
        band = tpl["title"]["size_pt"] * 25.4 / 72        # title height in mm
        on_photo = title_on_photo(cover, cx, cy)
        edge = rect["y_mm"] + rect["h_mm"]
        if not on_photo:
            assert cy - band > edge or cy + band < rect["y_mm"], (
                f"{name}: title clips the photo edge")

    def test_full_is_the_whole_front_panel(self):
        assert COVER_TEMPLATES["full"]["photo_rect"] == FULL_RECT


class TestDefaults:
    def test_a_cover_with_no_rectangle_means_the_whole_panel(self):
        # Every cover saved before templates existed looks like this.
        assert photo_rect_for({}) == FULL_RECT
        assert photo_rect_for({"photo_rect": None}) == FULL_RECT

    def test_an_unknown_template_falls_back_rather_than_failing(self):
        assert cover_template("no-such-design") is COVER_TEMPLATES[DEFAULT_COVER_TEMPLATE]
        assert cover_template(None) is COVER_TEMPLATES[DEFAULT_COVER_TEMPLATE]
        assert CoverDoc.model_validate({"template": "no-such-design"}).template \
            == DEFAULT_COVER_TEMPLATE

    def test_a_fresh_cover_is_the_full_bleed_design(self):
        cover = CoverDoc()
        assert cover.template == DEFAULT_COVER_TEMPLATE
        assert cover.photo_rect is None      # i.e. exactly what it always was
        assert (cover.photo_zoom, cover.photo_focus_x, cover.photo_focus_y) \
            == (1.0, 0.5, 0.5)


class TestApplying:
    def _cover(self) -> dict:
        return {"photo_id": "p1", "title": "Our travels", "subtitle": "2026",
                "title_font": "Playfair", "title_color": "#ffd700",
                "bg_color": "#1d4d85", "title_rotation": 4,
                "stickers": [{"id": "s1", "sticker_id": "flag-uz",
                              "x_mm": 40, "y_mm": 40, "w_mm": 24}]}

    @pytest.mark.parametrize("name", COVER_TEMPLATE_IDS)
    def test_it_keeps_everything_the_customer_wrote(self, name):
        cover = apply_cover_template(self._cover(), name)
        assert cover["photo_id"] == "p1"
        assert cover["title"] == "Our travels"
        assert cover["subtitle"] == "2026"
        assert cover["title_font"] == "Playfair"
        assert cover["title_color"] == "#ffd700"
        assert cover["title_rotation"] == 4
        assert len(cover["stickers"]) == 1

    @pytest.mark.parametrize("name", COVER_TEMPLATE_IDS)
    def test_it_writes_a_document_the_schema_accepts(self, name):
        doc = CoverDoc.model_validate(apply_cover_template(self._cover(), name))
        assert doc.template == name
        assert doc.photo_rect is not None

    @pytest.mark.parametrize("name", COVER_TEMPLATE_IDS)
    def test_switching_templates_is_reversible(self, name):
        """Nothing accumulates: going away and back gives the same cover, so
        a customer can try all five and lose nothing by it."""
        start = apply_cover_template(self._cover(), DEFAULT_COVER_TEMPLATE)
        before = json.dumps(start, sort_keys=True)
        there = apply_cover_template(json.loads(before), name)
        back = apply_cover_template(there, DEFAULT_COVER_TEMPLATE)
        assert json.dumps(back, sort_keys=True) == before

    @pytest.mark.parametrize("name", COVER_TEMPLATE_IDS)
    def test_no_template_touches_a_colour(self, name):
        """Colour belongs to the customer and to the occasion theme; a
        template that swapped it would undo their choice silently."""
        cover = apply_cover_template(self._cover(), name)
        assert cover["bg_color"] == "#1d4d85"
        assert cover["title_color"] == "#ffd700"


class TestTitleOnPhoto:
    def test_full_bleed_puts_the_title_on_the_photo(self):
        assert title_on_photo({}, 74, 168) is True

    def test_a_framed_template_puts_it_on_the_background(self):
        cover = apply_cover_template({}, "window")
        assert title_on_photo(cover, cover["title_x_mm"], cover["title_y_mm"]) is False

    def test_it_follows_the_title_rather_than_the_template(self):
        # Drag the title up onto the picture and it is over the photo again.
        cover = apply_cover_template({}, "window")
        assert title_on_photo(cover, 74, 80) is True


class TestEditorMirror:
    def test_editor_copy_matches_the_registry(self):
        """editor/js/cover-templates.js is generated; regenerate with
        `python scripts/gen_cover_templates.py` when the registry changes."""
        src = EDITOR_JS.read_text()
        body = re.search(r"export const COVER_TEMPLATES = (\{.*?\});\n", src, re.DOTALL)
        assert body, "cover-templates.js has no COVER_TEMPLATES object"
        assert json.loads(body.group(1)) == COVER_TEMPLATES

    def test_the_default_matches_too(self):
        src = EDITOR_JS.read_text()
        assert f'DEFAULT_COVER_TEMPLATE = "{DEFAULT_COVER_TEMPLATE}"' in src

    def test_the_picker_shows_them_in_registry_order(self):
        """Alphabetical would bury the default design in the middle."""
        src = EDITOR_JS.read_text()
        ids = re.search(r"COVER_TEMPLATE_IDS = (\[.*?\]);", src, re.DOTALL)
        assert ids and json.loads(ids.group(1)) == list(COVER_TEMPLATES)
        assert list(COVER_TEMPLATES)[0] == DEFAULT_COVER_TEMPLATE
