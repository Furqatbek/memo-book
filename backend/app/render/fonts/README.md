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
