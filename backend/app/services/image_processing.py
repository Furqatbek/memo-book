"""Pure image processing for the ingest pipeline (spec Part 6). No DB, no
storage — bytes in, derivatives + metadata out.

Order matters and is load-bearing:
- dimensions are read from the header and rejected BEFORE the pixel data is
  decoded (decompression-bomb guard);
- EXIF (taken_at, orientation) is extracted BEFORE any conversion (R5);
- orientation is applied physically and reported as 1 (R4);
- derivatives are re-encoded without any metadata (EXIF often carries the
  GPS coordinates of the user's home).
"""
import hashlib
import io
from dataclasses import dataclass
from datetime import UTC, datetime

import pillow_heif
from PIL import Image, ImageOps, UnidentifiedImageError
from PIL.ExifTags import IFD

pillow_heif.register_heif_opener()

MAX_BYTES = 25 * 1024 * 1024
MAX_SIDE_PX = 15_000
MAX_PIXELS = 80_000_000

# Explicit global guard as well (spec Part 6/11): Pillow raises on anything
# bigger even if a code path forgets the header check.
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

DISPLAY_LONG_EDGE = 2000
DISPLAY_QUALITY = 85
THUMB_LONG_EDGE = 400
THUMB_QUALITY = 80

EXIF_DATETIME_ORIGINAL = 0x9003
EXIF_DATETIME = 0x0132
EXIF_ORIENTATION = 0x0112


class IngestError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ProcessedImage:
    width: int              # post-rotation
    height: int             # post-rotation
    taken_at: datetime | None
    original_orientation: int
    sha256: str
    display_jpeg: bytes
    thumb_jpeg: bytes


def _parse_exif_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # EXIF has no timezone; treat as UTC — only relative order matters (R2).
        return datetime.strptime(value.strip(), "%Y:%m:%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def _extract_exif(img: Image.Image) -> tuple[datetime | None, int]:
    exif = img.getexif()
    orientation = int(exif.get(EXIF_ORIENTATION, 1) or 1)
    try:
        original = exif.get_ifd(IFD.Exif).get(EXIF_DATETIME_ORIGINAL)
    except Exception:  # noqa: BLE001 — malformed EXIF IFDs are common in the wild
        original = None
    taken_at = _parse_exif_datetime(original) or _parse_exif_datetime(exif.get(EXIF_DATETIME))
    return taken_at, orientation


def _flatten_to_rgb(img: Image.Image) -> Image.Image:
    if img.mode == "RGB":
        return img
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return img.convert("RGB")


def _derive_jpeg(img: Image.Image, long_edge: int, quality: int) -> bytes:
    copy = img.copy()
    copy.thumbnail((long_edge, long_edge), Image.LANCZOS)
    out = io.BytesIO()
    # No exif= argument: derived files carry no metadata at all.
    copy.save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()


def process_image(data: bytes) -> ProcessedImage:
    if len(data) == 0:
        raise IngestError("empty file")
    if len(data) > MAX_BYTES:
        raise IngestError(f"file exceeds {MAX_BYTES} bytes")

    try:
        img = Image.open(io.BytesIO(data))
    except UnidentifiedImageError as exc:
        raise IngestError("not a valid image") from exc

    # Header-only checks BEFORE decoding any pixel data.
    width, height = img.size
    if width > MAX_SIDE_PX or height > MAX_SIDE_PX:
        raise IngestError(f"dimensions {width}x{height} exceed {MAX_SIDE_PX}px per side")
    if width * height > MAX_PIXELS:
        raise IngestError(f"{width * height} pixels exceed the {MAX_PIXELS} limit")

    # Integrity pass, then reopen (verify() invalidates the parser state).
    try:
        img.verify()
    except Exception as exc:
        raise IngestError("corrupt image data") from exc
    img = Image.open(io.BytesIO(data))

    taken_at, orientation = _extract_exif(img)  # R5: before any conversion

    try:
        img.load()
    except Exception as exc:
        raise IngestError("corrupt image data") from exc

    img = ImageOps.exif_transpose(img)  # R4: rotate physically
    img = _flatten_to_rgb(img)

    return ProcessedImage(
        width=img.width,
        height=img.height,
        taken_at=taken_at,
        original_orientation=orientation,
        sha256=hashlib.sha256(data).hexdigest(),
        display_jpeg=_derive_jpeg(img, DISPLAY_LONG_EDGE, DISPLAY_QUALITY),
        thumb_jpeg=_derive_jpeg(img, THUMB_LONG_EDGE, THUMB_QUALITY),
    )
