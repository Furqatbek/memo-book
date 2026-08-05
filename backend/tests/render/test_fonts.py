"""Font families: user choice flows into the print PDF, preview, and cover;
unknown names fall back to sans; every shipped file covers every site script."""
from app.render.cover import build_cover_pdf
from app.render.interior import (
    FAMILIES,
    FONT_DIR,
    build_pdf,
    family_ttf,
    font_name,
    normalize_family,
)
from app.render.preview import render_preview_page

# Every script a customer can type in: base Latin, Russian Cyrillic, Uzbek
# Latin (okina U+02BB/02BC), Uzbek Cyrillic ext (қ ғ ҳ ў), Karakalpak
# (á ǵ ı ń ó ú). A font missing ANY of these prints tofu boxes in a real
# customer's book and must not ship.
SCRIPT_SAMPLE = (
    "The quick brown fox 0123456789 «»—·"
    "Съешь же ещё этих мягких булок, да выпей чаю. Ёё Йй"
    "Oʻzbekiston gʻishti choʼqqi ʻʼ"
    "Ўзбекистон қаҳрамони ғишт ҳосил Ққ Ғғ Ҳҳ Ўў"
    "Qaraqalpaqstan sayaxatı Áá Ǵǵ ı Ńń Óó Úú Íí"
)


def test_normalize_family():
    assert normalize_family("serif") == "serif"
    assert normalize_family("MONO") == "mono"
    assert normalize_family("Inter") == "inter"     # the historical default name
    assert normalize_family("Montserrat") == "montserrat"
    assert normalize_family(None) == "sans"
    assert normalize_family("comic sans") == "sans"


def test_font_name_and_ttf_resolution():
    assert font_name("serif") == "MemoBookSerif"
    assert font_name("serif", bold=True) == "MemoBookSerif-Bold"
    assert font_name("Inter") == "MemoBookInter"
    assert font_name("notoserif", bold=True) == "MemoBookNotoSerif-Bold"
    for fam in FAMILIES:
        assert family_ttf(fam).exists()
        assert family_ttf(fam, bold=True).exists()


def test_every_family_covers_every_script():
    from fontTools.ttLib import TTFont

    chars = sorted({c for c in SCRIPT_SAMPLE if not c.isspace()})
    for fam in FAMILIES:
        for bold in (False, True):
            path = family_ttf(fam, bold=bold)
            cmap = TTFont(str(path)).getBestCmap()
            missing = [c for c in chars if ord(c) not in cmap]
            assert not missing, f"{path.name} is missing glyphs: {missing}"


def test_license_files_ship_with_the_ofl_fonts():
    for stem in ("OFL-inter", "OFL-montserrat", "OFL-notoserif"):
        assert (FONT_DIR / f"{stem}.txt").exists()


def page_with(font: str) -> dict:
    return {"index": 0, "placements": [],
            "texts": [{"id": "t", "x_mm": 20, "y_mm": 20, "w_mm": 100, "h_mm": 10,
                       "content": "Salom dunyo", "font": font, "size_pt": 14,
                       "align": "left", "color": "#1a1a1a"}]}


def test_interior_embeds_chosen_family():
    # ReportLab embeds the subset under the font's PostScript name.
    pdf = build_pdf([page_with("serif")], lambda pid: b"", cache_tag="fonts-serif")
    assert b"DejaVuSerif" in pdf
    pdf = build_pdf([page_with("montserrat")], lambda pid: b"", cache_tag="fonts-mont")
    assert b"Montserrat" in pdf
    pdf = build_pdf([page_with("unknown-font")], lambda pid: b"", cache_tag="fonts-fb")
    assert b"DejaVuSans" in pdf
    assert b"DejaVuSerif" not in pdf


def test_preview_renders_each_family():
    for fam in FAMILIES:
        jpeg = render_preview_page(page_with(fam), {})
        assert jpeg[:2] == b"\xff\xd8"


def test_cover_title_uses_family():
    cover = {"title": "Bizning Sayohat", "subtitle": "2026",
             "title_size_pt": 28, "title_font": "mono"}
    pdf = build_cover_pdf(cover, 16, None, cache_tag="fonts-cover")
    assert b"DejaVuSansMono-Bold" in pdf


def rotated_page(rotation: float) -> dict:
    return {"index": 0, "placements": [],
            "texts": [{"id": "t", "x_mm": 40, "y_mm": 90, "w_mm": 70, "h_mm": 12,
                       "content": "Aylantirilgan matn", "font": "sans",
                       "size_pt": 14, "align": "center", "color": "#1a1a1a",
                       "rotation": rotation}]}


def test_rotated_text_renders_and_differs():
    import fitz

    straight = build_pdf([rotated_page(0)], lambda pid: b"", cache_tag="rot-0")
    rotated = build_pdf([rotated_page(37.5)], lambda pid: b"", cache_tag="rot-37")
    assert rotated != straight
    doc = fitz.open(stream=rotated, filetype="pdf")
    words = {w[4] for w in doc[0].get_text("words")}
    assert "Aylantirilgan" in words          # still real vector text


def test_rotated_text_preview_renders():
    for rot in (0, 37.5, -90, 180):
        jpeg = render_preview_page(rotated_page(rot), {})
        assert jpeg[:2] == b"\xff\xd8"
