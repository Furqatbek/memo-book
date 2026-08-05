"""Font families: user choice flows into the print PDF, preview, and cover;
legacy names fall back to sans."""
from app.render.cover import build_cover_pdf
from app.render.interior import build_pdf, family_ttf, font_name, normalize_family
from app.render.preview import render_preview_page


def test_normalize_family():
    assert normalize_family("serif") == "serif"
    assert normalize_family("MONO") == "mono"
    assert normalize_family("Inter") == "sans"      # legacy stored value
    assert normalize_family(None) == "sans"
    assert normalize_family("comic sans") == "sans"


def test_font_name_and_ttf_resolution():
    assert font_name("serif") == "MemoBookSerif"
    assert font_name("serif", bold=True) == "MemoBookSerif-Bold"
    assert font_name("Inter") == "MemoBookSans"
    assert family_ttf("mono").name == "DejaVuSansMono.ttf"
    assert family_ttf("mono").exists()


def page_with(font: str) -> dict:
    return {"index": 0, "placements": [],
            "texts": [{"id": "t", "x_mm": 20, "y_mm": 20, "w_mm": 100, "h_mm": 10,
                       "content": "Salom dunyo", "font": font, "size_pt": 14,
                       "align": "left", "color": "#1a1a1a"}]}


def test_interior_embeds_chosen_family():
    # ReportLab embeds the subset under the font's PostScript name.
    pdf = build_pdf([page_with("serif")], lambda pid: b"", cache_tag="fonts-serif")
    assert b"DejaVuSerif" in pdf
    pdf = build_pdf([page_with("Inter")], lambda pid: b"", cache_tag="fonts-legacy")
    assert b"DejaVuSans" in pdf
    assert b"DejaVuSerif" not in pdf


def test_preview_renders_each_family():
    for fam in ("sans", "serif", "mono"):
        jpeg = render_preview_page(page_with(fam), {})
        assert jpeg[:2] == b"\xff\xd8"


def test_cover_title_uses_family():
    cover = {"title": "Bizning Sayohat", "subtitle": "2026",
             "title_size_pt": 28, "title_font": "mono"}
    pdf = build_cover_pdf(cover, 16, None, cache_tag="fonts-cover")
    assert b"DejaVuSansMono-Bold" in pdf
