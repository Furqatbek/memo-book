"""A79: the editor's copy of the resolution rules must agree with this one.

`editor/js/app.js` reimplements `app/domain/resolution.py` in JavaScript,
under a comment calling itself "the mirror of app/domain/resolution.py,
thresholds and all". Nothing checked that. Two independent implementations of
the same arithmetic, in two languages, with a promise instead of a test — and
the promise is exactly the kind this codebase has already seen go quietly
false twice (the admin route list, the browser-check README).

Drift here is not cosmetic. The editor's numbers decide which pages a
customer is warned about before they pay; the Python decides what the printer
is told afterwards. If they disagree, someone is told the wrong thing, and
the disagreement is invisible until a book comes back.

Parsing the JS rather than running it: pulling a JS engine into the backend
test suite to check four constants and one formula would cost more than it
protects. The constants are asserted exactly; the formula is asserted by
shape, which catches the realistic edit (a threshold nudged, an axis flipped,
zoom dropped) without pretending to be an interpreter.
"""
import re
from pathlib import Path

import pytest

from app.domain import resolution

EDITOR = Path(__file__).resolve().parents[3] / "editor" / "js" / "app.js"


@pytest.fixture(scope="module")
def js() -> str:
    assert EDITOR.exists(), f"the editor moved: {EDITOR}"
    return EDITOR.read_text(encoding="utf-8")


class TestTheThresholdsMatch:
    @pytest.mark.parametrize("name,value", [
        ("DPI_OK", resolution.DPI_OK),
        ("DPI_WARN", resolution.DPI_WARN),
        ("MIN_FULL_PAGE_SOURCE_PX", resolution.MIN_FULL_PAGE_SOURCE_PX),
    ])
    def test_constant(self, js, name, value):
        found = re.search(rf"\b{name}\s*=\s*(\d+)", js)
        assert found, f"{name} is not in the editor any more"
        assert int(found.group(1)) == value, (
            f"the editor uses {name}={found.group(1)}, Python uses {value} — "
            "the customer and the printer are being told different things")

    def test_the_page_size_matches(self, js):
        """The full-page rule turns on trim size; a different A5 in the
        editor would arm it on the wrong placements."""
        from app.domain.geometry import TRIM_H_MM, TRIM_W_MM

        for name, value in (("TRIM_W", TRIM_W_MM), ("TRIM_H", TRIM_H_MM)):
            found = re.search(rf"\b{name}\s*=\s*([\d.]+)", js)
            assert found, f"{name} is not in the editor"
            assert float(found.group(1)) == pytest.approx(float(value))


class TestTheRuleMatches:
    """Shape, not simulation. Each of these is a real way the two could
    drift apart while both still look plausible."""

    def test_the_editor_still_divides_by_zoom(self, js):
        """A68: zooming in spends pixels. Dropping this makes a 4x crop look
        fine in the editor and print at a quarter of the DPI."""
        body = self._placement_fn(js)
        assert "/ zoom" in body, "the editor stopped accounting for zoom"

    def test_contain_takes_the_better_axis_and_cover_the_worse(self, js):
        """Backwards here means letterboxed photos get warned about and
        full-bleed ones do not — precisely inverted."""
        body = self._placement_fn(js)
        assert re.search(r"'contain'\s*\?\s*Math\.max\(dpiW,\s*dpiH\)\s*:\s*"
                         r"Math\.min\(dpiW,\s*dpiH\)", body), (
            "the editor's contain/cover axis choice no longer matches "
            "effective_dpi()")

    def test_contain_is_exempt_from_the_full_page_floor(self, js):
        """The Python exempts it because letterboxing never asks the photo to
        fill the page. A tested asymmetry, easy to lose in a tidy-up."""
        body = self._placement_fn(js)
        assert "!== 'contain'" in body

    def test_an_unmeasured_photo_is_not_condemned(self, js):
        """Both sides skip a photo with no dimensions yet rather than calling
        it blocked — an ingest still in flight must not flash a warning."""
        body = self._placement_fn(js)
        assert re.search(r"if \(!photo \|\| !photo\.width", body)

    @staticmethod
    def _placement_fn(js: str) -> str:
        start = js.index("function placementResolution")
        end = js.index("\n}", start)
        return js[start:end]


class TestBothSidesAgreeOnRealCases:
    """The cases that matter, each computed here and asserted against the
    number the editor's formula produces for the same input. Written out so a
    failure names the disagreement rather than a diff of source text."""

    @pytest.mark.parametrize("px,mm,zoom,fit,expected", [
        # A phone photo across a full page: 474 dpi, comfortable.
        ((3024, 4032), (154.0, 216.0), 1.0, "cover", "ok"),
        # The same photo zoomed 4x. 118 dpi would only be a warning — but
        # 3024/4 = 756 source pixels is under the 800 floor, so the floor
        # decides and it is a block. The two rules disagreeing here is why
        # both are worth a case (A68).
        ((3024, 4032), (154.0, 216.0), 4.0, "cover", "block"),
        # A small web image full-bleed: 56 dpi, and under the floor twice
        # over.
        ((640, 480), (154.0, 216.0), 1.0, "cover", "block"),
        # The same small image in a stamp-sized slot: 406 dpi, fine.
        ((640, 480), (40.0, 30.0), 1.0, "cover", "ok"),
        # Letterboxed. Exempt from the 800px floor — it is never asked to
        # fill the page — but 105 dpi still earns a warning, which is the
        # part of the exemption that is easy to over-apply.
        ((640, 480), (154.0, 216.0), 1.0, "contain", "warn"),
    ])
    def test_case(self, px, mm, zoom, fit, expected):
        assert resolution.resolution_status(
            px[0], px[1], mm[0], mm[1], zoom=zoom, fit=fit) == expected
