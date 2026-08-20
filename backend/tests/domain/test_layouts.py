"""Page layouts: geometry sanity, the editor mirror staying in sync, and
what the schema accepts."""
import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.geometry import BLEED_MM, CANVAS_H_MM, CANVAS_W_MM
from app.domain.layouts import (
    DEFAULT_LAYOUT,
    LAYOUTS,
    MAX_PLACEMENTS_PER_PAGE,
    slots_for,
)
from app.schemas.layout import PageDoc

EDITOR_JS = Path(__file__).resolve().parents[3] / "editor/js/layouts.js"


class TestGeometry:
    def test_every_slot_sits_inside_the_canvas(self):
        for name, slots in LAYOUTS.items():
            for slot in slots:
                assert slot["x_mm"] >= -BLEED_MM - 0.01, name
                assert slot["y_mm"] >= -BLEED_MM - 0.01, name
                assert slot["x_mm"] + slot["w_mm"] <= CANVAS_W_MM - BLEED_MM + 0.01, name
                assert slot["y_mm"] + slot["h_mm"] <= CANVAS_H_MM - BLEED_MM + 0.01, name

    def test_slots_never_overlap(self):
        for name, slots in LAYOUTS.items():
            for i, a in enumerate(slots):
                for b in slots[i + 1:]:
                    apart = (a["x_mm"] + a["w_mm"] <= b["x_mm"] + 0.01
                             or b["x_mm"] + b["w_mm"] <= a["x_mm"] + 0.01
                             or a["y_mm"] + a["h_mm"] <= b["y_mm"] + 0.01
                             or b["y_mm"] + b["h_mm"] <= a["y_mm"] + 0.01)
                    assert apart, f"{name}: slots overlap"

    def test_every_slot_is_a_valid_placement(self):
        # The same validator the API applies to what the editor sends.
        for name, slots in LAYOUTS.items():
            for slot in slots:
                PageDoc.model_validate({
                    "index": 0, "layout": name,
                    "placements": [{"photo_id": "p", **slot}],
                })

    def test_unknown_layout_falls_back_to_full_bleed(self):
        assert slots_for(None) == LAYOUTS[DEFAULT_LAYOUT]
        assert slots_for("no-such-layout") == LAYOUTS[DEFAULT_LAYOUT]


class TestEditorMirror:
    def test_editor_copy_matches_the_registry(self):
        """editor/js/layouts.js is generated; regenerate with
        `python scripts/gen_layouts.py` when the registry changes."""
        src = EDITOR_JS.read_text()
        body = re.search(r"export const LAYOUTS = (\{.*?\});\n", src, re.DOTALL)
        assert body, "layouts.js has no LAYOUTS object"
        assert json.loads(body.group(1)) == LAYOUTS


class TestSchema:
    def test_layout_id_validated(self):
        with pytest.raises(ValidationError, match="unknown page layout"):
            PageDoc.model_validate({"index": 0, "layout": "collage-9000"})

    def test_pages_default_to_full_bleed(self):
        assert PageDoc(index=0).layout == DEFAULT_LAYOUT

    def test_placement_cap_enforced(self):
        slot = LAYOUTS["four"][0]
        too_many = [{"photo_id": f"p{i}", **slot}
                    for i in range(MAX_PLACEMENTS_PER_PAGE + 1)]
        with pytest.raises(ValidationError, match="at most"):
            PageDoc.model_validate({"index": 0, "layout": "four",
                                    "placements": too_many})

    def test_multi_photo_page_accepted(self):
        page = PageDoc.model_validate({
            "index": 0, "layout": "four",
            "placements": [{"photo_id": f"p{i}", **slot}
                           for i, slot in enumerate(LAYOUTS["four"])],
        })
        assert len(page.placements) == 4
