"""Preview page rendering (spec Part 5): 72 DPI, RGB, watermarked.

Exists to satisfy the "no going back after payment" confirmation. It must
never be reusable as the print file: it is low-resolution, JPEG-compressed,
visibly watermarked, and stored under a separate key namespace.
"""
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

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
    _draw_texts(img, page)
    img = _watermark(img)
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=PREVIEW_JPEG_QUALITY)
    return out.getvalue()
