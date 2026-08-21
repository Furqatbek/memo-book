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


def hex_to_rgb(value: str | None) -> tuple[int, int, int]:
    """Layout colours are schema-validated #rrggbb; anything else means an
    older stored layout without the field — default to white."""
    if isinstance(value, str) and len(value) == 7 and value.startswith("#"):
        try:
            return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
        except ValueError:
            pass
    return (255, 255, 255)


def _fit_cover(img: Image.Image, tw: int, th: int, zoom: float = 1.0,
               focus_x: float = 0.5, focus_y: float = 0.5) -> Image.Image:
    """Fill (tw, th) with the photo, cropping the overflow.

    `zoom` > 1 enlarges beyond the minimum cover scale; `focus_*` slides the
    crop window across the overflow (0 = left/top edge, 1 = right/bottom).
    At the defaults this is a plain centred crop and the arithmetic reduces
    to the original one exactly — `int((rw - tw) * 0.5) == (rw - tw) // 2` —
    so books laid out before crop control render unchanged.
    """
    scale = max(tw / img.width, th / img.height) * max(1.0, zoom)
    # Never smaller than the target: rounding must not open a transparent gap.
    rw = max(tw, round(img.width * scale))
    rh = max(th, round(img.height * scale))
    resized = img.resize((rw, rh), Image.LANCZOS)
    left = int((rw - tw) * min(max(focus_x, 0.0), 1.0))
    top = int((rh - th) * min(max(focus_y, 0.0), 1.0))
    return resized.crop((left, top, left + tw, top + th))


def _fit_contain(img: Image.Image, tw: int, th: int,
                 bg: tuple[int, int, int] = (255, 255, 255)) -> Image.Image:
    scale = min(tw / img.width, th / img.height)
    resized = img.resize((max(1, round(img.width * scale)),
                          max(1, round(img.height * scale))), Image.LANCZOS)
    background = Image.new("RGB", (tw, th), bg)
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
    bg = hex_to_rgb(page.get("bg_color"))
    canvas = Image.new("RGB", (cw, ch), bg)

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
            img = img.rotate(-rotation, expand=True, fillcolor=bg)

        rect = placement_to_px(RectMM(placement["x_mm"], placement["y_mm"],
                                      placement["w_mm"], placement["h_mm"]))
        tw = max(1, round(rect.w * scale))
        th = max(1, round(rect.h * scale))
        if placement.get("fit", "cover") == "contain":
            fitted = _fit_contain(img, tw, th, bg)
        else:
            fitted = _fit_cover(img, tw, th,
                                zoom=float(placement.get("zoom", 1.0) or 1.0),
                                focus_x=float(placement.get("focus_x", 0.5)),
                                focus_y=float(placement.get("focus_y", 0.5)))
        canvas.paste(fitted, (round(rect.x * scale), round(rect.y * scale)))
        del img, fitted  # free before the next placement

    out = io.BytesIO()
    canvas.save(out, format="JPEG", quality=PAGE_JPEG_QUALITY, optimize=True)
    del canvas
    return out.getvalue()
