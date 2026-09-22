"""Pure image processing for the ingest pipeline (spec Part 6). No DB, no
storage — bytes in, derivatives + metadata out.

Order matters and is load-bearing:
- dimensions are read from the header and rejected BEFORE the pixel data is
  decoded (decompression-bomb guard);
- EXIF (taken_at, orientation) is extracted BEFORE any conversion (R5);
- orientation is applied physically and reported as 1 (R4);
- derivatives are re-encoded without any metadata (EXIF often carries the
  GPS coordinates of the user's home).

A RAW file is not decoded here and never was. What changed in A103 is that
we stopped pretending otherwise: a DNG is a TIFF container, so Pillow opened
one happily and handed back its IFD0 THUMBNAIL as if it were the photograph.
`_pixel_source` now takes the largest picture actually inside the container.
"""
import hashlib
import io
from dataclasses import dataclass
from datetime import UTC, datetime

from PIL import Image, UnidentifiedImageError
from PIL.ExifTags import IFD

from app.services import dng

# HEIF/HEIC is registered once for the whole package, in app/__init__.py.
# It used to be registered here, which meant only processes that imported
# THIS module could read an iPhone photo — and the render worker does not
# import it (A93).

MAX_BYTES = 60 * 1024 * 1024
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
    """A photo we could not take, and why.

    `code` is a stable identifier and is what gets stored on the photo, so
    the editor can say what went wrong in the customer's own language. It
    used to store the prose below, which nothing ever displayed — every
    failed upload showed a bare red "Failed" and the reason was thrown away
    (A103). `reason` stays as English prose for the log line.
    """

    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code
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


# The same mapping `ImageOps.exif_transpose` uses internally. It is spelled
# out here because the orientation no longer always comes from the image in
# hand: a DNG's preview can rely on a tag written on the container around it,
# and `exif_transpose` can only read the tag the image carries itself.
_ORIENTATION_OP = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}


def _apply_orientation(img: Image.Image, orientation: int) -> Image.Image:
    """R4: rotate physically, so nothing downstream has to carry the tag."""
    op = _ORIENTATION_OP.get(orientation)
    return img.transpose(op) if op is not None else img


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


def source_pixels(raw: bytes) -> bytes:
    """The picture inside an uploaded file, at its original resolution.

    For everything but a RAW file this is the file itself. It exists because
    `original_key` holds exactly what the customer uploaded, and for a DNG
    that is a container whose first image is a thumbnail — so the preview
    renderer and the print renderer, which both read those bytes directly,
    each got 320x240 and no error (A103).

    Ingest is not the only reader, and correcting only the dimensions it
    reports would have been worse than leaving the bug alone: the photo
    would have measured 4032x3024 in the tray, passed the low-resolution
    check, and still printed as a postage stamp.

    Falling back to `raw` cannot lose anything in practice — a DNG with no
    readable picture fails ingest and can never reach a page — but it is the
    right way round regardless: an order that renders something is better
    than one that raises at the printer.
    """
    if not dng.is_dng(raw):
        return raw
    return dng.largest_embedded_image(raw) or raw


def _pixel_source(data: bytes) -> tuple[bytes, bytes]:
    """(bytes to decode, bytes holding the metadata).

    The two are the same file for an ordinary photo. For a DNG they are not:
    a DNG is a TIFF whose IFD0 is a THUMBNAIL, so decoding the file directly
    gives a 320x240 image and no error at all, while the real photograph sits
    in a SubIFD (A103). The pixels come from the largest picture actually in
    the container; the capture time stays with the container, because the
    embedded preview usually carries no EXIF of its own.
    """
    if not dng.is_dng(data):
        return data, data
    preview = dng.largest_embedded_image(data)
    if preview is None:
        raise IngestError(
            "raw_no_preview",
            "a RAW file with no embedded preview we can read")
    return preview, data


def process_image(data: bytes) -> ProcessedImage:
    if len(data) == 0:
        raise IngestError("empty", "empty file")
    if len(data) > MAX_BYTES:
        raise IngestError("too_large", f"file exceeds {MAX_BYTES} bytes")

    pixels, metadata = _pixel_source(data)

    try:
        img = Image.open(io.BytesIO(pixels))
    except UnidentifiedImageError as exc:
        raise IngestError("not_an_image", "not a valid image") from exc

    # Header-only checks BEFORE decoding any pixel data.
    width, height = img.size
    if width > MAX_SIDE_PX or height > MAX_SIDE_PX:
        raise IngestError(
            "too_large",
            f"dimensions {width}x{height} exceed {MAX_SIDE_PX}px per side")
    if width * height > MAX_PIXELS:
        raise IngestError(
            "too_large", f"{width * height} pixels exceed the {MAX_PIXELS} limit")

    # Integrity pass, then reopen (verify() invalidates the parser state).
    try:
        img.verify()
    except Exception as exc:
        raise IngestError("corrupt", "corrupt image data") from exc
    img = Image.open(io.BytesIO(pixels))

    taken_at, orientation = _extract_exif(img)  # R5: before any conversion
    if metadata is not pixels:
        # A DNG: the capture time is on the container, not on the preview.
        container_taken_at, container_orientation = _extract_exif(
            Image.open(io.BytesIO(metadata)))
        taken_at = taken_at or container_taken_at
        # Cameras differ on whether the embedded preview is already upright.
        # Trust the preview's own tag when it has one, and fall back to the
        # container's — either alone puts somebody's photos in sideways.
        if orientation <= 1:
            orientation = container_orientation

    try:
        img.load()
    except Exception as exc:
        raise IngestError("corrupt", "corrupt image data") from exc

    img = _apply_orientation(img, orientation)  # R4: rotate physically
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
