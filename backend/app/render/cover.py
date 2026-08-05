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
from app.render.compose import RenderError, _fit_cover
from app.render.interior import (
    FONT_BOLD,
    FONT_REGULAR,
    MM_TO_PT,
    _register_fonts,
)

WRAP_MM = 16.0  # PLACEHOLDER turn-in margin — confirm with the printer

COVER_JPEG_QUALITY = 95


def spine_mm_for_tier(page_count: int) -> float:
    settings = get_settings()
    spines = {16: settings.spine_mm_16, 32: settings.spine_mm_32,
              48: settings.spine_mm_48, 96: settings.spine_mm_96}
    if page_count not in spines:
        raise RenderError(f"no spine width configured for tier {page_count}")
    return spines[page_count]


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


def _compose_cover_raster(cover: dict, geo: CoverGeometry,
                          photo_bytes: bytes | None) -> bytes:
    w_px = mm_to_px(geo.total_w_mm)
    h_px = mm_to_px(geo.total_h_mm)
    canvas = Image.new("RGB", (w_px, h_px), (255, 255, 255))

    if photo_bytes is not None:
        try:
            img = Image.open(io.BytesIO(photo_bytes))
            img.load()
        except Exception as exc:
            raise RenderError("unreadable cover photo") from exc
        img = ImageOps.exif_transpose(img)
        if img.mode != "RGB":
            img = img.convert("RGB")
        # Front art fills the front panel plus the right wrap, full height,
        # so the turned-in edges continue the front design.
        x0 = mm_to_px(geo.front_x0_mm)
        target_w = w_px - x0
        fitted = _fit_cover(img, target_w, h_px)
        canvas.paste(fitted, (x0, 0))

    out = io.BytesIO()
    canvas.save(out, format="JPEG", quality=COVER_JPEG_QUALITY, optimize=True)
    return out.getvalue()


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

    main = Color(1, 1, 1) if over_photo else HexColor("#1a1a1a")
    shadow = Color(0, 0, 0, alpha=0.55)

    def centred(text: str, font: str, size: float, y_pt: float) -> None:
        c.setFont(font, size)
        if over_photo:  # offset shadow keeps white text legible on any photo
            c.setFillColor(shadow)
            c.drawCentredString(center_x_pt + size * 0.04 + 0.6,
                                y_pt - size * 0.04 - 0.6, text)
        c.setFillColor(main)
        c.drawCentredString(center_x_pt, y_pt, text)

    if title:
        centred(title, FONT_BOLD, title_size, total_h_pt * 0.40)
    if subtitle:
        centred(subtitle, FONT_REGULAR, subtitle_size,
                total_h_pt * 0.40 - title_size * 1.5)


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
        _draw_cover_text(c, cover, geo, over_photo=photo_bytes is not None)
        c.showPage()
        c.save()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return buf.getvalue()
