"""Subset the customer-facing display face to the characters it can meet (A84).

`editor/fonts/EBGaramond-*.woff2` is the headline serif on the four screens
outside the editor. The full family is ~380 KB a weight; subset to the
characters the five languages actually contain it is ~23 KB, which is the
difference between a book face and a book face nobody in Tashkent waits for.

The character set is DERIVED here, from `editor/js/i18n.js` and from the
literal text in `editor/index.html`, and `tests/test_web_fonts.py` imports
`required_characters()` from this module to assert the shipped files cover
it. That is the whole point of the arrangement: a hand-kept list of glyphs
and a hand-kept test of glyphs drift apart, and the failure mode is silent —
a missing glyph falls back per character, so one word renders in two
typefaces and only a customer ever sees it.

Usage (sources are the Google Fonts TTFs for weights 500 and 600):

    python scripts/subset_web_font.py EBGaramond-Medium.ttf EBGaramond-SemiBold.ttf
"""
from __future__ import annotations

import re
import string
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EDITOR = REPO / "editor"
I18N = EDITOR / "js" / "i18n.js"
INDEX = EDITOR / "index.html"
OUT_DIR = EDITOR / "fonts"

# Weight -> output filename, matching the @font-face rules in editor.css.
WEIGHTS = {500: "EBGaramond-Regular.woff2", 600: "EBGaramond-SemiBold.woff2"}

# Characters no translation contains but the display face still has to draw:
#
#   U+00A0  `fmtAmount` formats with `toLocaleString('ru-RU')`, whose
#           thousands separator is a non-breaking space, and every price on
#           screen is set in this face.
#   A-Z 0-9 order references are `UB-` plus base32, shown in the face.
#   symbols punctuation the interface inserts itself rather than translating.
INTERFACE_ONLY = (
    set(string.digits)
    | set(string.ascii_letters)
    | {"\u00a0"}
    | set("  -–—·.,:;!?()[]{}%+*/=@#&_|<>\"'‘’“”…")
)


def i18n_strings() -> list[str]:
    """Every translated string, all five languages.

    Parsed rather than executed: it is an ES module and this is a build
    script. Every entry in the table is a single-quoted literal on one line,
    and the caller asserts the count so a reformat cannot silently halve it.
    """
    src = I18N.read_text(encoding="utf-8")
    table = src[src.index("const STRINGS = {"):src.index("export const LANG_NAMES")]
    return [v.replace("\\'", "'")
            for v in re.findall(r":\s*'((?:[^'\\]|\\.)*)'", table)]


def html_literals() -> list[str]:
    """Text typed straight into the markup rather than translated.

    Small but real: the `·` between "Travel book" and "change" lives in
    index.html, is set in the display face, and is in no translation.
    """
    html = INDEX.read_text(encoding="utf-8")
    html = re.sub(r"<(script|style|svg)\b.*?</\1>", " ", html, flags=re.S | re.I)
    return re.findall(r">([^<>]+)<", html)


def required_characters() -> set[str]:
    """The set the shipped subset must cover.

    Both cases of every letter, because `text-transform: uppercase` is
    applied in CSS and is therefore invisible to any scan of the strings —
    an uppercase `Ғ` that no translation contains can still reach the screen.
    Emoji are excluded: the system colour font draws those whatever we ship.
    """
    values = i18n_strings()
    if len(values) < 400:
        raise SystemExit(f"only {len(values)} strings parsed out of i18n.js — parser stale?")
    chars = set(INTERFACE_ONLY)
    for v in values + html_literals():
        chars |= set(v)
    for c in list(chars):
        chars |= set(c.upper()) | set(c.lower())
    return {c for c in chars if (c.isprintable() or c == " ") and not _is_emoji(c)}


def _is_emoji(c: str) -> bool:
    cp = ord(c)
    return (0x1F000 <= cp <= 0x1FAFF) or (0x2600 <= cp <= 0x27BF) or cp == 0xFE0F


def _weight_of(ttf: Path) -> int:
    from fontTools.ttLib import TTFont

    return TTFont(ttf)["OS/2"].usWeightClass


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    chars = required_characters()
    charfile = Path(sys.argv[0]).with_name("_subset-chars.txt")
    charfile.write_text("".join(sorted(chars)), encoding="utf-8")
    try:
        for src in map(Path, argv):
            weight = _weight_of(src)
            if weight not in WEIGHTS:
                raise SystemExit(f"{src} is weight {weight}; expected one of {sorted(WEIGHTS)}")
            out = OUT_DIR / WEIGHTS[weight]
            subprocess.run(
                [sys.executable, "-m", "fontTools.subset", str(src),
                 f"--text-file={charfile}", "--flavor=woff2",
                 "--layout-features=*", f"--output-file={out}"],
                check=True,
            )
            print(f"{out.relative_to(REPO)}  {out.stat().st_size / 1024:.0f} KB  "
                  f"({len(chars)} characters, weight {weight})")
    finally:
        charfile.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
