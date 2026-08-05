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
        if align in ("center", "right"):
            text_w = draw.textlength(content, font=font)
            x = x + (w - text_w) / 2 if align == "center" else x + w - text_w
        draw.text((x, y), content, font=font, fill=text.get("color", "#1a1a1a"))


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
