"""Interior PDF builder (spec Part 7). Streams strictly one page at a time
into a ReportLab canvas — never a list of page images — and produces
byte-identical output for identical input (invariant mode + repo-pinned
fonts + deterministic JPEG encoding)."""
import io
import os
import shutil
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as pdfcanvas

from app.domain.geometry import (
    BLEED_MM,
    CANVAS_H_MM,
    CANVAS_W_MM,
)
from app.render.compose import RenderError, compose_page

MM_TO_PT = 72 / 25.4
PAGE_W_PT = CANVAS_W_MM * MM_TO_PT
PAGE_H_PT = CANVAS_H_MM * MM_TO_PT

FONT_DIR = Path(__file__).parent / "fonts"
STICKER_DIR = Path(__file__).parent / "stickers"

# User-selectable families. Every file is repo-pinned and verified to cover
# ALL site scripts (Latin + Uzbek okina, Cyrillic incl. қ/ғ/ҳ/ў, Karakalpak
# á/ǵ/ı/ń) — see tests/render/test_fonts.py. Unknown names normalize to
# sans; "Inter" (the historical default) resolves to the real Inter family.
# Registered PDF font names stay stable (they are embedded in the output
# bytes, which must be deterministic).
FAMILIES = {
    "sans": ("MemoBookSans", "DejaVuSans.ttf",
             "MemoBookSans-Bold", "DejaVuSans-Bold.ttf"),
    "serif": ("MemoBookSerif", "DejaVuSerif.ttf",
              "MemoBookSerif-Bold", "DejaVuSerif-Bold.ttf"),
    "mono": ("MemoBookMono", "DejaVuSansMono.ttf",
             "MemoBookMono-Bold", "DejaVuSansMono-Bold.ttf"),
    "inter": ("MemoBookInter", "Inter-Regular.ttf",
              "MemoBookInter-Bold", "Inter-Bold.ttf"),
    "montserrat": ("MemoBookMontserrat", "Montserrat-Regular.ttf",
                   "MemoBookMontserrat-Bold", "Montserrat-Bold.ttf"),
    "notoserif": ("MemoBookNotoSerif", "NotoSerif-Regular.ttf",
                  "MemoBookNotoSerif-Bold", "NotoSerif-Bold.ttf"),
}
FONT_REGULAR = "MemoBookSans"
FONT_BOLD = "MemoBookSans-Bold"

_fonts_registered = False


def normalize_family(name: str | None) -> str:
    key = str(name or "").strip().lower()
    return key if key in FAMILIES else "sans"


def font_name(family: str | None, bold: bool = False) -> str:
    fam = FAMILIES[normalize_family(family)]
    return fam[2] if bold else fam[0]


def family_ttf(family: str | None, bold: bool = False) -> Path:
    fam = FAMILIES[normalize_family(family)]
    return FONT_DIR / (fam[3] if bold else fam[1])


def _register_fonts() -> None:
    global _fonts_registered
    if not _fonts_registered:
        for regular, regular_ttf, bold, bold_ttf in FAMILIES.values():
            pdfmetrics.registerFont(TTFont(regular, str(FONT_DIR / regular_ttf)))
            pdfmetrics.registerFont(TTFont(bold, str(FONT_DIR / bold_ttf)))
        _fonts_registered = True


def _draw_text(c: pdfcanvas.Canvas, text: dict) -> None:
    """Text boxes are vector (never rasterised) and were clamped to the safe
    area on save; coordinates are trim-origin mm, PDF space is bleed-origin
    points with a bottom-left origin. Rotation is clockwise degrees about
    the box centre (the editor's CSS convention); the unrotated path is
    left byte-identical to keep existing renders deterministic."""
    font_size = float(text.get("size_pt", 11))
    c.setFont(font_name(text.get("font")), font_size)
    c.setFillColor(HexColor(text.get("color", "#1a1a1a")))

    x_pt = (text["x_mm"] + BLEED_MM) * MM_TO_PT
    box_w_pt = text["w_mm"] * MM_TO_PT
    # First baseline sits one em below the box top.
    y_pt = PAGE_H_PT - ((text["y_mm"] + BLEED_MM) * MM_TO_PT) - font_size

    content = text.get("content", "")
    align = text.get("align", "left")
    rotation = float(text.get("rotation", 0) or 0) % 360

    if rotation:
        box_h_pt = float(text.get("h_mm", 10)) * MM_TO_PT
        centre_x = x_pt + box_w_pt / 2
        centre_y = PAGE_H_PT - ((text["y_mm"] + BLEED_MM) * MM_TO_PT) - box_h_pt / 2
        rel_y = box_h_pt / 2 - font_size   # same baseline, box-local
        c.saveState()
        c.translate(centre_x, centre_y)
        c.rotate(-rotation)   # PDF rotates counter-clockwise; editor clockwise
        if align == "center":
            c.drawCentredString(0, rel_y, content)
        elif align == "right":
            c.drawRightString(box_w_pt / 2, rel_y, content)
        else:
            c.drawString(-box_w_pt / 2, rel_y, content)
        c.restoreState()
        return

    if align == "center":
        c.drawCentredString(x_pt + box_w_pt / 2, y_pt, content)
    elif align == "right":
        c.drawRightString(x_pt + box_w_pt, y_pt, content)
    else:
        c.drawString(x_pt, y_pt, content)


def draw_sticker(c: pdfcanvas.Canvas, sticker: dict,
                 x_offset_mm: float = BLEED_MM,
                 y_offset_mm: float = BLEED_MM,
                 page_h_pt: float = PAGE_H_PT) -> None:
    """Vendored sticker PNG (square, alpha), centred at (x_mm, y_mm) in
    trim-origin mm, rotated clockwise like text boxes. Asset paths are
    repo-pinned and stable, so the embedded object names — which ReportLab
    derives from the path — keep renders byte-deterministic. Also used by
    the cover builder with the front-panel offset."""
    path = STICKER_DIR / f"{sticker['sticker_id']}.png"
    w_pt = float(sticker["w_mm"]) * MM_TO_PT
    centre_x = (float(sticker["x_mm"]) + x_offset_mm) * MM_TO_PT
    centre_y = page_h_pt - ((float(sticker["y_mm"]) + y_offset_mm) * MM_TO_PT)
    rotation = float(sticker.get("rotation", 0) or 0) % 360
    c.saveState()
    c.translate(centre_x, centre_y)
    if rotation:
        c.rotate(-rotation)   # PDF rotates counter-clockwise; editor clockwise
    c.drawImage(str(path), -w_pt / 2, -w_pt / 2, width=w_pt, height=w_pt,
                mask="auto")
    c.restoreState()


def build_pdf(pages: Iterable[dict],
              fetch_photo_bytes: Callable[[str], bytes],
              scale: float = 1.0,
              cache_tag: str = "default") -> bytes:
    """Build the PDF, fetching photos per page via `fetch_photo_bytes` so at
    most one page's worth of image data is alive at any moment.

    Page rasters are spooled to per-page temp FILES and drawn by path:
    ReportLab embeds JPEG files via direct DCT passthrough, while
    drawImage(ImageReader) decodes to raw RGB and retains ~17MB per page —
    measured 1027MB vs 62MB peak RSS for a 96-page book.

    ReportLab also derives the embedded object's internal name from the file
    PATH, and that name ends up in the PDF bytes — so paths must be stable
    across runs for determinism. `cache_tag` (e.g. the book id) namespaces a
    fixed directory under the system temp dir; page filenames are indexed,
    which is deterministic because the same book renders the same pages.
    """
    _register_fonts()
    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=(PAGE_W_PT, PAGE_H_PT), invariant=1)
    c.setTitle("memo-book interior")

    tmp = os.path.join(tempfile.gettempdir(), f"memobook-render-{cache_tag}")
    os.makedirs(tmp, exist_ok=True)
    page_count = 0
    try:
        for page in pages:
            photo_bytes: dict[str, bytes] = {}
            for placement in page.get("placements", []):
                pid = placement["photo_id"]
                photo_bytes[pid] = fetch_photo_bytes(pid)

            page_jpeg = compose_page(page, photo_bytes, scale=scale)
            del photo_bytes
            page_path = os.path.join(tmp, f"page-{page_count}.jpg")
            with open(page_path, "wb") as f:
                f.write(page_jpeg)
            del page_jpeg
            c.drawImage(page_path, 0, 0, width=PAGE_W_PT, height=PAGE_H_PT)

            # Stickers sit above the photo, below text — same stacking as
            # the editor and the preview.
            for sticker in page.get("stickers", []):
                draw_sticker(c, sticker)
            for text in page.get("texts", []):
                _draw_text(c, text)

            c.showPage()
            page_count += 1

        if page_count == 0:
            raise RenderError("no pages to render")
        c.save()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return buf.getvalue()
