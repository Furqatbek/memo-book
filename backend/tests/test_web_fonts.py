"""A84: the display face can render every word the five languages contain.

`editor/fonts/EBGaramond-*.woff2` is a subset — a few hundred characters
instead of the full family — which is the only reason a book serif costs
23 KB per weight over a Tashkent connection. A subset is a promise about
coverage, and a promise about coverage is exactly the kind of thing that
quietly stops being true: someone adds a Karakalpak string containing `ǵ`,
the subset does not have it, and the browser falls back *per character*, so
one word renders in two different typefaces and nobody notices until a
customer sends a screenshot.

The survey behind the choice is in `app/render/fonts/README.md`: of the
display serifs considered, Playfair Display has no `Ҳ/ҳ` and Cormorant,
Spectral, Bitter and Alegreya have no `ǵ`. Whichever face is shipped, this
test is what keeps that from being a footnote nobody re-checks.

Derived, not declared, and derived ONCE: the character set comes from
`scripts/subset_web_font.py` — the same function that built the files — and
the file list comes from the `@font-face` rules in `editor/editor.css`. A
test with its own private idea of the required characters is a second
inventory to keep in step, which is the bug it is meant to catch.
"""
import re
from pathlib import Path

import pytest

from scripts.subset_web_font import WEIGHTS, required_characters

fontTools_ttLib = pytest.importorskip("fontTools.ttLib")
pytest.importorskip("brotli", reason="decoding woff2 needs brotli")

REPO = Path(__file__).resolve().parents[2]
EDITOR = REPO / "editor"
CSS = EDITOR / "editor.css"


def font_faces() -> list[tuple[int, Path]]:
    """(weight, file) for every EB Garamond @font-face the stylesheet declares."""
    css = CSS.read_text(encoding="utf-8")
    faces = []
    for block in re.findall(r"@font-face\s*\{([^}]*)\}", css):
        if "'EB Garamond'" not in block:
            continue
        src = re.search(r"url\('([^']+)'\)", block)
        weight = re.search(r"font-weight:\s*(\d+)", block)
        assert src and weight, f"unreadable @font-face block: {block!r}"
        faces.append((int(weight.group(1)), EDITOR / src.group(1)))
    assert faces, "editor.css declares no EB Garamond @font-face"
    return faces


FACES = font_faces()


def test_stylesheet_and_subset_script_agree_on_the_weights():
    """A weight the CSS asks for and the script does not build is a font the
    browser synthesises — a smeared fake bold instead of the real cut."""
    assert sorted(w for w, _ in FACES) == sorted(WEIGHTS)


def test_stylesheet_and_subset_script_agree_on_the_filenames():
    assert {p.name for _, p in FACES} == set(WEIGHTS.values())


@pytest.mark.parametrize("weight,path", FACES, ids=lambda v: str(v))
def test_display_face_covers_every_language(weight, path):
    assert path.is_file(), f"{path} is referenced by editor.css but not shipped"
    have = {chr(cp) for cp in fontTools_ttLib.TTFont(path).getBestCmap()}
    missing = sorted(required_characters() - have)
    assert not missing, (
        f"EB Garamond {weight} cannot render {missing!r}. Re-run "
        f"`python scripts/subset_web_font.py <ttf> <ttf>` — a missing glyph "
        f"falls back per character, so one word renders in two typefaces."
    )


@pytest.mark.parametrize("weight,path", FACES, ids=lambda v: str(v))
def test_display_face_is_still_subset(weight, path):
    """The whole point of subsetting is the size; a full weight is ~380 KB.

    A generous ceiling: this guards against someone dropping the unsubset
    family in, it is not a byte budget.
    """
    kb = path.stat().st_size / 1024
    assert kb < 90, f"EB Garamond {weight} is {kb:.0f} KB — was it subset?"


def test_open_font_licence_ships_with_the_font():
    """SIL OFL 1.1 requires the licence to travel with the files."""
    licence = EDITOR / "fonts" / "OFL-ebgaramond.txt"
    assert licence.is_file()
    assert "SIL OPEN FONT LICENSE" in licence.read_text(encoding="utf-8").upper()
