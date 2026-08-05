# Bundled fonts

Three DejaVu families (regular + bold each) — Sans, Serif, Mono — pinned in
the repo per the build spec: the render must never depend on system fonts,
and captions need full Latin + Cyrillic coverage
(English/Russian/Uzbek/Karakalpak). These are the user-selectable text
fonts in the editor ("sans" / "serif" / "mono").

DejaVu fonts are free to use and redistribute under the DejaVu Fonts License
(a Bitstream Vera derivative): https://dejavu-fonts.github.io/License.html

All user-selected font names map to these files until brand fonts are pinned
(see ASSUMPTIONS.md).
