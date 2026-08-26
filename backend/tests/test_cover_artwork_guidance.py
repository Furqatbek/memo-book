"""A88: what we tell a designer to draw must match where the renderer puts it.

The guidance said "16 mm all round folds out of sight" and "only the middle
148 x 210 mm is seen". Both were wrong on one edge: the LEFT edge of the
artwork is the spine fold, where nothing is trimmed, so the visible panel
sits flush left rather than centred. A designer following the old text lost
16 mm of usable width and placed their subject 8 mm off-centre — and would
have found out from a printed book, which is the most expensive place to
find out.

This is prose about geometry, so it is checked against the geometry: the
per-edge margins come from the renderer's own paste box, and both the
document and `cover_design.py spec` must state them.
"""
import re
import subprocess
import sys
from pathlib import Path

from app.domain.cover_templates import FULL_RECT
from app.domain.geometry import TRIM_H_MM, TRIM_W_MM, mm_to_px
from app.render.cover import WRAP_MM, cover_geometry, photo_box_px
from app.services.cover_designs import (
    ARTWORK_H_MM,
    ARTWORK_H_PX,
    ARTWORK_W_MM,
    ARTWORK_W_PX,
)

BACKEND = Path(__file__).resolve().parents[1]
DOC = BACKEND.parent / "docs" / "cover-designs.md"
PX_PER_MM = 300 / 25.4


def spec_output() -> str:
    return subprocess.run([sys.executable, "scripts/cover_design.py", "spec"],
                          cwd=BACKEND, capture_output=True, text=True,
                          check=True).stdout


def lost_per_edge() -> dict[str, float]:
    """How much of the artwork file each edge loses, straight from the renderer.

    Rounded to whole millimetres: the paste box is computed in whole pixels,
    so the arithmetic comes back a fiftieth of a millimetre short of the real
    figure. That is a third of one pixel at 300 dpi — noise from the
    measurement, not a property of the geometry, and rounding it away is what
    lets this compare against the numbers a person is told to draw against.
    """
    geo = cover_geometry(32)
    w_px, h_px = mm_to_px(geo.total_w_mm), mm_to_px(geo.total_h_mm)
    left, top, right, bottom = photo_box_px(FULL_RECT, geo, w_px, h_px)
    raw = {
        "left": geo.front_x0_mm - left / PX_PER_MM,
        "right": right / PX_PER_MM - (geo.front_x0_mm + TRIM_W_MM),
        "top": WRAP_MM - top / PX_PER_MM,
        "bottom": bottom / PX_PER_MM - (WRAP_MM + TRIM_H_MM),
    }
    for edge, value in raw.items():
        assert abs(value - round(value)) < 0.085, (
            f"{edge} margin is {value:.3f} mm — more than a pixel away from a "
            f"whole millimetre, so this is not rounding noise")
    return {edge: float(round(value)) for edge, value in raw.items()}


def test_the_artwork_size_matches_the_region_the_renderer_pastes_it_into():
    """If these drift apart the file is silently scaled, and a 16 mm turn-in
    stops being 16 mm."""
    lost = lost_per_edge()
    assert TRIM_W_MM + lost["left"] + lost["right"] == ARTWORK_W_MM
    assert TRIM_H_MM + lost["top"] + lost["bottom"] == ARTWORK_H_MM
    assert round(ARTWORK_W_MM * PX_PER_MM) == ARTWORK_W_PX
    assert round(ARTWORK_H_MM * PX_PER_MM) == ARTWORK_H_PX


def test_the_spine_edge_loses_nothing():
    """The property both documents got wrong. Art at the left edge is
    printed: it is the spine fold, not a turn-in."""
    lost = lost_per_edge()
    assert lost["left"] == 0.0
    for edge in ("right", "top", "bottom"):
        assert lost[edge] == WRAP_MM, edge


def test_the_documentation_does_not_claim_a_turn_in_on_all_four_sides():
    """The exact wording that was wrong, in both places it was written."""
    for name, text in (("docs/cover-designs.md", DOC.read_text(encoding="utf-8")),
                       ("cover_design.py spec", spec_output())):
        low = text.lower()
        assert "all round" not in low, (
            f"{name} still says the turn-in is 'all round'; the left edge has none")
        assert "middle 148" not in low, (
            f"{name} still calls the visible panel the 'middle' of the file; "
            f"it is flush against the left edge")
        assert "three sides" in low or "not four" in low, (
            f"{name} must say the turn-in is on three sides")


def test_both_documents_state_the_real_numbers():
    lost = lost_per_edge()
    safe = int(WRAP_MM + 5)          # turn-in plus the 5 mm safe margin
    for name, text in (("docs/cover-designs.md", DOC.read_text(encoding="utf-8")),
                       ("cover_design.py spec", spec_output())):
        assert (f"{ARTWORK_W_PX} × {ARTWORK_H_PX}" in text
                or f"{ARTWORK_W_PX} x {ARTWORK_H_PX}" in text), f"{name}: pixel size"
        assert f"{int(lost['right'])} mm" in text, f"{name}: turn-in width"
        assert f"{safe} mm" in text, f"{name}: safe margin on the trimmed edges"


def test_the_doc_tells_you_where_to_centre_a_subject():
    """Centring in the file puts the subject 8 mm off-centre on the book,
    which is the practical consequence of the flush-left panel."""
    offset = (ARTWORK_W_MM - TRIM_W_MM) / 2
    doc = DOC.read_text(encoding="utf-8")
    assert re.search(rf"{int(offset)}\s*mm off-centre", doc), (
        "the doc should warn that centring in the file is off-centre on the "
        f"printed cover, by {offset:.0f} mm")
    assert f"x = {TRIM_W_MM / 2:.0f} mm" in doc, "and give the real centre"
