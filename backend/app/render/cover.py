"""Hardcover wrap render (spec Part 7): one wide sheet —
[wrap][back 148mm][spine][front 148mm][wrap], full height = wrap + 210 + wrap.

Spine width comes from config per page tier and is a PLACEHOLDER until the
printer supplies real values: a wrong spine wraps the cover art onto the
wrong face and wastes the whole print run. The wrap (turn-in) margin is
likewise a placeholder to confirm with the printer.

Front art extends through the right/top/bottom wrap so the turned-in edges
match the front design. Title/subtitle are vector text on the front panel.
"""
import io
import os
import shutil
import tempfile
from dataclasses import dataclass

from PIL import Image, ImageOps
from reportlab.lib.colors import Color, HexColor
from reportlab.pdfgen import canvas as pdfcanvas

from app.config import get_settings
from app.domain.geometry import TRIM_H_MM, TRIM_W_MM, mm_to_px
from app.domain.cover_templates import photo_rect_for, title_on_photo
from app.domain.tiers import sides_per_sheet
from app.render.compose import RenderError, _fit_cover, hex_to_rgb
from app.render.interior import (
    MM_TO_PT,
    _register_fonts,
    draw_sticker,
    font_name,
)

WRAP_MM = 16.0  # PLACEHOLDER turn-in margin — confirm with the printer

COVER_JPEG_QUALITY = 95


def spine_mm_for_tier(page_count: int) -> float:
    """Spine width for a book of this many printed sides.

    Keyed by SHEET tier, like prices (A63): SPINE_MM_16 is the 16-sheet book,
    because sheets of paper are what actually make a spine thick and what the
    customer picks. Books created before sheet-counting stored a page count
    straight from those same numbers, so they fall back to a lookup by page
    count and keep their original spine.
    """
    settings = get_settings()
    spines = {16: settings.spine_mm_16, 32: settings.spine_mm_32,
              48: settings.spine_mm_48, 96: settings.spine_mm_96}
    sheets = page_count // sides_per_sheet()
    spine = spines.get(sheets) or spines.get(page_count)
    if spine is None:
        raise RenderError(f"no spine width configured for tier {page_count}")
    return spine


@dataclass(frozen=True)
class CoverGeometry:
    total_w_mm: float
    total_h_mm: float
    wrap_mm: float
    spine_mm: float
    front_x0_mm: float  # left edge of the front panel


def cover_geometry(page_count: int) -> CoverGeometry:
    spine = spine_mm_for_tier(page_count)
    return CoverGeometry(
        total_w_mm=2 * WRAP_MM + 2 * TRIM_W_MM + spine,
        total_h_mm=2 * WRAP_MM + TRIM_H_MM,
        wrap_mm=WRAP_MM,
        spine_mm=spine,
        front_x0_mm=WRAP_MM + TRIM_W_MM + spine,
    )


def _num(cover: dict, key: str, default: float) -> float:
    """A stored 0.0 is a real value, not a missing one — `or` would eat it."""
    value = cover.get(key)
    return default if value is None else float(value)


def photo_box_px(rect: dict, geo: CoverGeometry,
                 w_px: int, h_px: int) -> tuple[int, int, int, int]:
    """A front-panel trim rectangle -> a pixel box on the wrap sheet.

    Reaching a trim edge means "bleed off it", so the box is extended to the
    sheet edge there — into the turn-in, which is exactly why the turn-in is
    printed. The left edge is never extended: the spine is there, not a
    turn-in, and art crossing it would appear on the closed book's back.

    The default full-panel rectangle therefore reproduces the original
    "front panel plus the right wrap, full height" paste exactly (A70).
    """
    left = mm_to_px(geo.front_x0_mm + max(0.0, rect["x_mm"]))
    right = (w_px if rect["x_mm"] + rect["w_mm"] >= TRIM_W_MM
             else mm_to_px(geo.front_x0_mm + rect["x_mm"] + rect["w_mm"]))
    top = 0 if rect["y_mm"] <= 0 else mm_to_px(geo.wrap_mm + rect["y_mm"])
    bottom = (h_px if rect["y_mm"] + rect["h_mm"] >= TRIM_H_MM
              else mm_to_px(geo.wrap_mm + rect["y_mm"] + rect["h_mm"]))
    return left, top, max(left + 1, right), max(top + 1, bottom)


def _compose_cover_raster(cover: dict, geo: CoverGeometry,
                          photo_bytes: bytes | None) -> bytes:
    w_px = mm_to_px(geo.total_w_mm)
    h_px = mm_to_px(geo.total_h_mm)
    canvas = Image.new("RGB", (w_px, h_px), hex_to_rgb(cover.get("bg_color")))

    if photo_bytes is not None:
        try:
            img = Image.open(io.BytesIO(photo_bytes))
            img.load()
        except Exception as exc:
            raise RenderError("unreadable cover photo") from exc
        img = ImageOps.exif_transpose(img)
        if img.mode != "RGB":
            img = img.convert("RGB")
        left, top, right, bottom = photo_box_px(photo_rect_for(cover), geo,
                                                w_px, h_px)
        fitted = _fit_cover(img, right - left, bottom - top,
                            zoom=_num(cover, "photo_zoom", 1.0),
                            focus_x=_num(cover, "photo_focus_x", 0.5),
                            focus_y=_num(cover, "photo_focus_y", 0.5))
        canvas.paste(fitted, (left, top))

    out = io.BytesIO()
    canvas.save(out, format="JPEG", quality=COVER_JPEG_QUALITY, optimize=True)
    return out.getvalue()


# Where the title block sits when the customer has never moved it. The
# renderer's own legacy default, expressed in front-panel trim mm.
def _legacy_title_centre(geo: CoverGeometry) -> tuple[float, float]:
    return TRIM_W_MM / 2, geo.total_h_mm * 0.60 - geo.wrap_mm


def title_over_photo(cover: dict, geo: CoverGeometry,
                     has_photo: bool) -> bool:
    """Is the title actually printed on top of the photo?

    It used to be "is there a photo at all", which was the same question
    while every photo filled the whole front. With a framed template the
    title sits on the background beside the photo, where white-on-white
    would vanish, so ask the geometry instead — and it keeps answering
    correctly when the customer drags the title somewhere else (A70).
    """
    if not has_photo:
        return False
    tx, ty = cover.get("title_x_mm"), cover.get("title_y_mm")
    if tx is None or ty is None:
        tx, ty = _legacy_title_centre(geo)
    return title_on_photo(cover, float(tx), float(ty))


def auto_title_color(bg_color: str | None) -> str:
    """Readable ink for a background the customer chose. The old rule was a
    flat dark grey, which disappeared on the dark cover colours the occasion
    themes set."""
    r, g, b = hex_to_rgb(bg_color)
    # Rec. 601 luma — good enough to pick black or white, and cheap.
    return "#1a1a1a" if (0.299 * r + 0.587 * g + 0.114 * b) > 140 else "#ffffff"


def _draw_cover_text(c: pdfcanvas.Canvas, cover: dict, geo: CoverGeometry,
                     over_photo: bool) -> None:
    title = (cover.get("title") or "").strip()
    subtitle = (cover.get("subtitle") or "").strip()
    if not title and not subtitle:
        return

    center_x_pt = (geo.front_x0_mm + TRIM_W_MM / 2) * MM_TO_PT
    total_h_pt = geo.total_h_mm * MM_TO_PT
    title_size = float(cover.get("title_size_pt") or 28)
    subtitle_size = max(10.0, title_size * 0.5)

    # Explicit title_color wins; otherwise automatic per background.
    custom = cover.get("title_color")
    if custom:
        main = HexColor(custom)
    elif over_photo:
        main = Color(1, 1, 1)
    else:
        main = HexColor(auto_title_color(cover.get("bg_color")))
    shadow = Color(0, 0, 0, alpha=0.55)

    def centred(text: str, font: str, size: float, x_pt: float, y_pt: float) -> None:
        c.setFont(font, size)
        if over_photo:  # offset shadow keeps white text legible on any photo
            c.setFillColor(shadow)
            c.drawCentredString(x_pt + size * 0.04 + 0.6,
                                y_pt - size * 0.04 - 0.6, text)
        c.setFillColor(main)
        c.drawCentredString(x_pt, y_pt, text)

    family = cover.get("title_font")
    tx, ty = cover.get("title_x_mm"), cover.get("title_y_mm")
    rotation = float(cover.get("title_rotation", 0) or 0) % 360

    if tx is not None and ty is not None:
        # User-positioned block: centre in front-panel trim mm, rotation
        # clockwise about that centre (same conventions as text boxes).
        centre_x = (geo.front_x0_mm + float(tx)) * MM_TO_PT
        centre_y = total_h_pt - (geo.wrap_mm + float(ty)) * MM_TO_PT
        c.saveState()
        c.translate(centre_x, centre_y)
        if rotation:
            c.rotate(-rotation)
        if title:
            centred(title, font_name(family, bold=True), title_size, 0,
                    title_size * 0.25)
        if subtitle:
            centred(subtitle, font_name(family), subtitle_size, 0,
                    title_size * 0.25 - title_size * 1.5)
        c.restoreState()
        return

    # Legacy fixed layout — byte-identical for existing covers.
    if title:
        centred(title, font_name(family, bold=True), title_size,
                center_x_pt, total_h_pt * 0.40)
    if subtitle:
        centred(subtitle, font_name(family), subtitle_size,
                center_x_pt, total_h_pt * 0.40 - title_size * 1.5)


def build_cover_pdf(cover: dict, page_count: int,
                    photo_bytes: bytes | None,
                    cache_tag: str = "cover") -> bytes:
    _register_fonts()
    geo = cover_geometry(page_count)
    raster = _compose_cover_raster(cover, geo, photo_bytes)

    page_w_pt = geo.total_w_mm * MM_TO_PT
    page_h_pt = geo.total_h_mm * MM_TO_PT
    buf = io.BytesIO()
    c = pdfcanvas.Canvas(buf, pagesize=(page_w_pt, page_h_pt), invariant=1)
    c.setTitle("memo-book cover")

    # Same stable-path DCT-passthrough technique as the interior (A28):
    # deterministic bytes, no decoded-RGB retention.
    tmp = os.path.join(tempfile.gettempdir(), f"memobook-render-{cache_tag}")
    os.makedirs(tmp, exist_ok=True)
    try:
        path = os.path.join(tmp, "cover.jpg")
        with open(path, "wb") as f:
            f.write(raster)
        c.drawImage(path, 0, 0, width=page_w_pt, height=page_h_pt)
        stickers = cover.get("stickers", [])
        if stickers:
            # Front-panel coordinates like the title block. Clipped to the
            # front panel + its right wrap: what hangs off the right edge
            # wraps around the board (like the front art), and nothing can
            # spill across the spine onto the back.
            c.saveState()
            clip = c.beginPath()
            clip.rect(geo.front_x0_mm * MM_TO_PT, 0,
                      (TRIM_W_MM + geo.wrap_mm) * MM_TO_PT, page_h_pt)
            c.clipPath(clip, stroke=0, fill=0)
            for sticker in stickers:
                draw_sticker(c, sticker,
                             x_offset_mm=geo.front_x0_mm,
                             y_offset_mm=geo.wrap_mm,
                             page_h_pt=page_h_pt)
            c.restoreState()
        _draw_cover_text(c, cover, geo,
                         over_photo=title_over_photo(cover, geo,
                                                     photo_bytes is not None))
        c.showPage()
        c.save()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return buf.getvalue()
