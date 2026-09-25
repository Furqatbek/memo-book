"""The operator's photograph of the press — CR-003-2.

One person, standing in a print shop, holding a phone. Everything here is
shaped by that: the file arrives at whatever size the phone produced, in
whatever orientation the phone recorded, and there is nobody to tell them
it did not work.

So it is resized, re-encoded and stripped here rather than refused:

  * **EXIF goes.** A phone photo carries GPS coordinates. This picture is
    sent to a customer, so the print shop's location — and the operator's
    movements — must not travel with it. Pillow's `save` writes no EXIF
    unless asked, and `exif_transpose` applies the rotation first so
    dropping the tag cannot turn the picture on its side.
  * **Resized to something Telegram accepts.** Telegram refuses a photo
    over 10 MB and downscales anything over 10 000 px on a side. A modern
    phone clears both without trying.
  * **Not a print artifact.** This lives under `ops/`, never under a
    book's key prefix, because it is not part of anything anyone paid for.
"""
import io
import uuid
from datetime import UTC, datetime

import anyio
import structlog

from app import storage

log = structlog.get_logger()

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
# Comfortably inside Telegram's limits and still sharp on a phone screen.
MAX_EDGE_PX = 2048
JPEG_QUALITY = 85


class ProgressPhotoError(ValueError):
    """Message meant for the operator to read, on their phone, in a hurry."""


def _key(human_ref: str) -> str:
    day = datetime.now(UTC).strftime("%Y%m%d")
    return f"ops/progress/{human_ref}/{day}-{uuid.uuid4().hex[:8]}.jpg"


def _normalise(raw: bytes) -> bytes:
    from PIL import Image, ImageOps

    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as exc:  # noqa: BLE001 — any decoder failure reads the same
        raise ProgressPhotoError(
            "that file is not a photo we can read") from exc
    img = ImageOps.exif_transpose(img)
    if img.mode != "RGB":
        img = img.convert("RGB")
    if max(img.width, img.height) > MAX_EDGE_PX:
        img.thumbnail((MAX_EDGE_PX, MAX_EDGE_PX), Image.LANCZOS)
    out = io.BytesIO()
    # No `exif=` argument, so none is written. That is the GPS strip.
    img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return out.getvalue()


async def store(human_ref: str, raw: bytes) -> str:
    if not raw:
        raise ProgressPhotoError("that file is empty")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ProgressPhotoError(
            f"that photo is {len(raw) // (1024 * 1024)} MB; the limit is "
            f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    jpeg = await anyio.to_thread.run_sync(_normalise, raw)
    key = _key(human_ref)
    await anyio.to_thread.run_sync(storage.put_bytes, key, jpeg, "image/jpeg")
    log.info("progress_photo.stored", order=human_ref, key=key,
             bytes_in=len(raw), bytes_out=len(jpeg))
    return key
