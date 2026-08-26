# Bundled fonts

The user-selectable print families, repo-pinned per the build spec (the
render must never depend on system fonts):

| Family key | Files | License |
|---|---|---|
| `sans` | DejaVuSans (+Bold) | DejaVu Fonts License |
| `serif` | DejaVuSerif (+Bold) | DejaVu Fonts License |
| `mono` | DejaVuSansMono (+Bold) | DejaVu Fonts License |
| `inter` | Inter (+Bold) | SIL OFL 1.1 (`OFL-inter.txt`) |
| `montserrat` | Montserrat (+Bold) | SIL OFL 1.1 (`OFL-montserrat.txt`) |
| `notoserif` | NotoSerif (+Bold) | SIL OFL 1.1 (`OFL-notoserif.txt`) |

Every family is verified (tests/render/test_fonts.py) to cover ALL site
scripts: Latin, Russian Cyrillic, Uzbek Latin (okina ʻ), Uzbek Cyrillic
(қ ғ ҳ ў) and Karakalpak (á ǵ ı ń ó ú). Candidates that miss any of those
glyphs are rejected — a missing glyph prints as an empty box in a real
customer's book. (Rejected on those grounds: Playfair Display, Lora,
Caveat, Comfortaa, PT Serif, Nunito, Rubik.)

The Inter/Montserrat/NotoSerif TTFs are static instances (wght 400/700)
generated from the Google Fonts variable sources with fonttools. The same
files, converted to woff2, are served by the editor (`editor/fonts/`) so
the canvas shows the true print fonts.

DejaVu license: https://dejavu-fonts.github.io/License.html

## Web-only: the display face

`editor/fonts/EBGaramond-*.woff2` (SIL OFL 1.1, `OFL-ebgaramond.txt`) is the
headline face for the customer-facing screens (A84). It is **not** a print
family and is not selectable in the editor — the print families above are
unchanged.

It is subset to the characters those screens can actually render — all five
languages, both cases, digits, currency and punctuation — which is why each
weight is 23 KB rather than ~380 KB. Regenerate from the Google Fonts TTFs
for weights 500 and 600:

```bash
python scripts/subset_web_font.py EBGaramond-Medium.ttf EBGaramond-SemiBold.ttf
```

That script *derives* the character set from `editor/js/i18n.js` and
`editor/index.html` rather than keeping a list, and
`backend/tests/test_web_fonts.py` imports the same function to assert the
shipped files cover it. Two inventories would drift; one cannot.

It is not a formality. The first run of that test found two characters the
hand-built subset had missed and the screens were already showing: the
non-breaking space `toLocaleString('ru-RU')` puts inside every price, and
the `·` between the book type and the "change" link. Of the display serifs
considered, Playfair Display lacks the Uzbek Cyrillic `Ҳ/ҳ`, and Cormorant,
Spectral, Bitter, Alegreya and Source Serif 4 all lack the Karakalpak `ǵ`.
A missing glyph falls back per character, so one word renders in two
different typefaces.
