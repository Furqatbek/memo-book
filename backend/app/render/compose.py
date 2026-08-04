"""Page composition: one layout page + original photo bytes -> one 300dpi
page raster. Pure — no DB, no storage. The caller feeds photos one page at a
time and must let each result go out of scope before the next page (memory
discipline, spec Part 7)."""
import io

from PIL import Image, ImageOps

from app.domain.geometry import CANVAS_H_PX, CANVAS_W_PX, RectMM, placement_to_px

PAGE_JPEG_QUALITY = 95


class RenderError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _fit_cover(img: Image.Image, tw: int, th: int) -> Image.Image:
    scale = max(tw / img.width, th / img.height)
    resized = img.resize((max(1, round(img.width * scale)),
                          max(1, round(img.height * scale))), Image.LANCZOS)
    left = (resized.width - tw) // 2
    top = (resized.height - th) // 2
    return resized.crop((left, top, left + tw, top + th))


def _fit_contain(img: Image.Image, tw: int, th: int) -> Image.Image:
    scale = min(tw / img.width, th / img.height)
    resized = img.resize((max(1, round(img.width * scale)),
                          max(1, round(img.height * scale))), Image.LANCZOS)
    background = Image.new("RGB", (tw, th), (255, 255, 255))
    background.paste(resized, ((tw - resized.width) // 2, (th - resized.height) // 2))
    return background


def compose_page(page: dict, photo_bytes: dict[str, bytes],
                 scale: float = 1.0) -> bytes:
    """Render one page's placements onto a white canvas; returns JPEG bytes.

    `scale` < 1 renders a proportionally smaller raster (used by the preview
    pipeline); 1.0 is full 300dpi print resolution. Photos are opened from
    ORIGINAL bytes — EXIF orientation is re-applied here because originals
    are stored untouched.
    """
    cw = max(1, round(CANVAS_W_PX * scale))
    ch = max(1, round(CANVAS_H_PX * scale))
    canvas = Image.new("RGB", (cw, ch), (255, 255, 255))

    for placement in page.get("placements", []):
        pid = placement["photo_id"]
        data = photo_bytes.get(pid)
        if data is None:
            raise RenderError(f"missing photo bytes for {pid}")
        try:
            img = Image.open(io.BytesIO(data))
            img.load()
        except Exception as exc:
            raise RenderError(f"unreadable photo {pid}") from exc

        img = ImageOps.exif_transpose(img)
        if img.mode != "RGB":
            img = img.convert("RGB")

        rotation = float(placement.get("rotation", 0)) % 360
        if rotation:
            img = img.rotate(-rotation, expand=True, fillcolor=(255, 255, 255))

        rect = placement_to_px(RectMM(placement["x_mm"], placement["y_mm"],
                                      placement["w_mm"], placement["h_mm"]))
        tw = max(1, round(rect.w * scale))
        th = max(1, round(rect.h * scale))
        if placement.get("fit", "cover") == "contain":
            fitted = _fit_contain(img, tw, th)
        else:
            fitted = _fit_cover(img, tw, th)
        canvas.paste(fitted, (round(rect.x * scale), round(rect.y * scale)))
        del img, fitted  # free before the next placement

    out = io.BytesIO()
    canvas.save(out, format="JPEG", quality=PAGE_JPEG_QUALITY, optimize=True)
    del canvas
    return out.getvalue()
