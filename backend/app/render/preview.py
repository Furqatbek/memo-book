"""Preview page rendering (spec Part 5): 72 DPI, RGB, watermarked.

Exists to satisfy the "no going back after payment" confirmation. It must
never be reusable as the print file: it is low-resolution, JPEG-compressed,
visibly watermarked, and stored under a separate key namespace.
"""
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.render.compose import compose_page

PREVIEW_DPI = 72
PREVIEW_SCALE = PREVIEW_DPI / 300  # compose_page scale factor
PREVIEW_JPEG_QUALITY = 72

FONT_PATH = Path(__file__).parent / "fonts" / "DejaVuSans-Bold.ttf"
WATERMARK_TEXT = "PREVIEW"


def _draw_texts(img: Image.Image, page: dict) -> None:
    """Approximate the vector text of the print PDF on the raster preview.
    At 72 DPI one PDF point equals one pixel, so size_pt maps directly."""
    from app.domain.geometry import BLEED_MM, PX_PER_MM
    from app.render.interior import family_ttf

    draw = ImageDraw.Draw(img)
    for text in page.get("texts", []):
        size_px = max(6, round(float(text.get("size_pt", 11))))
        font = ImageFont.truetype(str(family_ttf(text.get("font"))), size_px)
        x = (text["x_mm"] + BLEED_MM) * PX_PER_MM * PREVIEW_SCALE
        y = (text["y_mm"] + BLEED_MM) * PX_PER_MM * PREVIEW_SCALE
        w = text["w_mm"] * PX_PER_MM * PREVIEW_SCALE
        content = text.get("content", "")
        align = text.get("align", "left")
        color = text.get("color", "#1a1a1a")
        rotation = float(text.get("rotation", 0) or 0) % 360

        if rotation:
            # PIL can't draw rotated text: render the box onto a transparent
            # layer, rotate it clockwise (negative angle in PIL terms), and
            # composite centred on the box centre — mirroring the PDF.
            h = text.get("h_mm", 10) * PX_PER_MM * PREVIEW_SCALE
            w_px, h_px = max(1, round(w)), max(size_px, round(h))
            pad = size_px
            layer = Image.new("RGBA", (w_px + 2 * pad, h_px + 2 * pad), (0, 0, 0, 0))
            ldraw = ImageDraw.Draw(layer)
            tx = pad
            if align in ("center", "right"):
                text_w = ldraw.textlength(content, font=font)
                tx = pad + ((w_px - text_w) / 2 if align == "center" else w_px - text_w)
            ldraw.text((tx, pad), content, font=font, fill=color)
            layer = layer.rotate(-rotation, expand=True, resample=Image.BICUBIC)
            cx, cy = x + w_px / 2, y + h_px / 2
            img.paste(layer, (round(cx - layer.width / 2), round(cy - layer.height / 2)),
                      layer)
            continue

        if align in ("center", "right"):
            text_w = draw.textlength(content, font=font)
            x = x + (w - text_w) / 2 if align == "center" else x + w - text_w
        draw.text((x, y), content, font=font, fill=color)


def _draw_stickers(img: Image.Image, stickers: list) -> None:
    """Composite the vendored sticker PNGs the same way the PDFs do:
    centred at (x_mm, y_mm), rotated clockwise, above the photo and below
    text. Uses the print assets downscaled, so preview and print match."""
    from app.domain.geometry import BLEED_MM, PX_PER_MM
    from app.render.interior import STICKER_DIR

    for sticker in stickers:
        path = STICKER_DIR / f"{sticker['sticker_id']}.png"
        w_px = max(1, round(float(sticker["w_mm"]) * PX_PER_MM * PREVIEW_SCALE))
        layer = Image.open(path).convert("RGBA").resize(
            (w_px, w_px), resample=Image.LANCZOS)
        rotation = float(sticker.get("rotation", 0) or 0) % 360
        if rotation:
            layer = layer.rotate(-rotation, expand=True, resample=Image.BICUBIC)
        cx = (float(sticker["x_mm"]) + BLEED_MM) * PX_PER_MM * PREVIEW_SCALE
        cy = (float(sticker["y_mm"]) + BLEED_MM) * PX_PER_MM * PREVIEW_SCALE
        img.paste(layer, (round(cx - layer.width / 2),
                          round(cy - layer.height / 2)), layer)


def _watermark(img: Image.Image) -> Image.Image:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = ImageFont.truetype(str(FONT_PATH), max(24, img.width // 8))
    step = max(80, img.height // 5)
    for y in range(0, img.height + step, step):
        draw.text((10, y), f"{WATERMARK_TEXT} · {WATERMARK_TEXT}",
                  font=font, fill=(128, 128, 128, 88))
    overlay = overlay.rotate(30, expand=False)
    combined = Image.alpha_composite(img.convert("RGBA"), overlay)
    return combined.convert("RGB")


def render_preview_page(page: dict, photo_bytes: dict[str, bytes]) -> bytes:
    """One page -> watermarked 72dpi JPEG. Empty pages render as watermarked
    blanks — the preview shows the book exactly as it would print."""
    page_jpeg = compose_page(page, photo_bytes, scale=PREVIEW_SCALE)
    img = Image.open(io.BytesIO(page_jpeg))
    img.load()
    _draw_stickers(img, page.get("stickers", []))
    _draw_texts(img, page)
    img = _watermark(img)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=PREVIEW_JPEG_QUALITY)
    return out.getvalue()


def _num(cover: dict, key: str, default: float) -> float:
    value = cover.get(key)
    return default if value is None else float(value)


def _preview_photo_box(cover: dict, w: int, h: int) -> tuple[int, int, int, int]:
    """The cover template's photo rectangle on this preview canvas.

    Same rule as the print sheet (app/render/cover.py:photo_box_px): a
    rectangle reaching a trim edge bleeds off it, and here the overhang is
    the 3mm preview bleed rather than the turn-in. The left edge bleeds too,
    because this canvas shows only the front panel — there is no spine on it
    to protect (A70).
    """
    from app.domain.cover_templates import photo_rect_for
    from app.domain.geometry import BLEED_MM, PX_PER_MM, TRIM_H_MM, TRIM_W_MM

    rect = photo_rect_for(cover)
    scale = PX_PER_MM * PREVIEW_SCALE

    def px(mm: float) -> int:
        return round((mm + BLEED_MM) * scale)

    left = 0 if rect["x_mm"] <= 0 else px(rect["x_mm"])
    top = 0 if rect["y_mm"] <= 0 else px(rect["y_mm"])
    right = (w if rect["x_mm"] + rect["w_mm"] >= TRIM_W_MM
             else px(rect["x_mm"] + rect["w_mm"]))
    bottom = (h if rect["y_mm"] + rect["h_mm"] >= TRIM_H_MM
              else px(rect["y_mm"] + rect["h_mm"]))
    return left, top, max(left + 1, right), max(top + 1, bottom)


def render_preview_cover(cover: dict, photo_bytes: bytes | None,
                        artwork_bytes: bytes | None = None) -> bytes:
    """The cover FRONT panel -> watermarked 72dpi JPEG, so the customer
    confirms the cover along with the pages. Mirrors the cover PDF's front:
    background colour, full-panel photo, title/subtitle at their chosen
    position/rotation (or the classic centred default)."""
    from app.domain.geometry import CANVAS_H_PX, CANVAS_W_PX, PX_PER_MM
    from app.render.compose import _fit_cover, hex_to_rgb
    from app.render.interior import family_ttf

    w = max(1, round(CANVAS_W_PX * PREVIEW_SCALE))
    h = max(1, round(CANVAS_H_PX * PREVIEW_SCALE))
    img = Image.new("RGB", (w, h), hex_to_rgb(cover.get("bg_color")))

    # A ready-made design's artwork sits behind everything (A71); on this
    # canvas it covers the whole front panel, bleed included.
    if artwork_bytes:
        art = Image.open(io.BytesIO(artwork_bytes))
        art.load()
        art = ImageOps.exif_transpose(art)
        if art.mode != "RGB":
            art = art.convert("RGB")
        img.paste(_fit_cover(art, w, h), (0, 0))

    if photo_bytes:
        photo = Image.open(io.BytesIO(photo_bytes))
        photo.load()
        photo = ImageOps.exif_transpose(photo)
        if photo.mode != "RGB":
            photo = photo.convert("RGB")
        left, top, right, bottom = _preview_photo_box(cover, w, h)
        img.paste(_fit_cover(photo, right - left, bottom - top,
                             zoom=_num(cover, "photo_zoom", 1.0),
                             focus_x=_num(cover, "photo_focus_x", 0.5),
                             focus_y=_num(cover, "photo_focus_y", 0.5)),
                  (left, top))

    _draw_stickers(img, cover.get("stickers", []))

    title = (cover.get("title") or "").strip()
    subtitle = (cover.get("subtitle") or "").strip()
    if title or subtitle:
        title_size = max(6, round(float(cover.get("title_size_pt") or 28)))
        family = cover.get("title_font")
        bold = ImageFont.truetype(str(family_ttf(family, bold=True)), title_size)
        regular = ImageFont.truetype(str(family_ttf(family)), max(6, title_size // 2))
        # Same defaults the editor shows when the block was never moved.
        cx_mm = cover.get("title_x_mm") if cover.get("title_x_mm") is not None else 74.0
        cy_mm = cover.get("title_y_mm") if cover.get("title_y_mm") is not None else 122.0
        rotation = float(cover.get("title_rotation", 0) or 0) % 360
        # Same rule as the print sheet: white only where the title really
        # lands on the photo, contrasting ink otherwise (A70).
        from app.domain.cover_templates import title_on_photo
        from app.render.cover import auto_title_color

        over = bool(artwork_bytes) or (
            bool(photo_bytes) and title_on_photo(cover, float(cx_mm), float(cy_mm)))
        color = cover.get("title_color") or (
            "#ffffff" if over else auto_title_color(cover.get("bg_color")))

        pad = title_size * 2
        layer = Image.new("RGBA", (w + 2 * pad, w + 2 * pad), (0, 0, 0, 0))
        ldraw = ImageDraw.Draw(layer)
        lcx, lcy = layer.width / 2, layer.height / 2
        if title:
            ldraw.text((lcx, lcy - title_size * 0.55), title, font=bold,
                       fill=color, anchor="mm")
        if subtitle:
            ldraw.text((lcx, lcy + title_size * 0.75), subtitle, font=regular,
                       fill=color, anchor="mm")
        if rotation:
            layer = layer.rotate(-rotation, expand=True, resample=Image.BICUBIC)
        from app.domain.geometry import BLEED_MM

        px = (cx_mm + BLEED_MM) * PX_PER_MM * PREVIEW_SCALE
        py = (cy_mm + BLEED_MM) * PX_PER_MM * PREVIEW_SCALE
        img.paste(layer, (round(px - layer.width / 2), round(py - layer.height / 2)),
                  layer)

    img = _watermark(img)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=PREVIEW_JPEG_QUALITY)
    return out.getvalue()
