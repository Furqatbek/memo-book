"""Build files with a real DNG's structure, for the tests (A103).

There is no DNG in the repository and there should not be: a real one is
tens of megabytes of somebody's photograph. What the tests need is the
SHAPE, and the shape is the whole bug —

    IFD0            NewSubfileType=1   a thumbnail, plus the tags
                    SubIFDs (330) -> [raw, full-size preview]
    SubIFD "raw"    NewSubfileType=0   CFA sensor data under lossless JPEG
    SubIFD "prev"   NewSubfileType=1   a full-size JPEG the camera rendered

— because the full-resolution image is NOT in the top-level IFD chain.
Anything that opens a DNG as an ordinary TIFF gets the little IFD0
thumbnail and no error at all, which is exactly what our ingest did.

Building it by hand rather than with an imaging library is deliberate: a
library that could write this could also read it, and then the test would be
checking that a library agrees with itself.
"""
import io
import struct

from PIL import Image

BYTE, ASCII, SHORT, LONG = 1, 2, 3, 4

NEW_SUBFILE_TYPE = 254
IMAGE_WIDTH = 256
IMAGE_LENGTH = 257
BITS_PER_SAMPLE = 258
COMPRESSION = 259
PHOTOMETRIC = 262
MAKE = 271
MODEL = 272
STRIP_OFFSETS = 273
SAMPLES_PER_PIXEL = 277
ROWS_PER_STRIP = 278
STRIP_BYTE_COUNTS = 279
DATETIME_ORIGINAL = 0x9003
EXIF_IFD = 0x8769
ORIENTATION = 0x0112
SUB_IFDS = 330
DNG_VERSION = 50706

PHOTOMETRIC_YCBCR = 6
PHOTOMETRIC_CFA = 32803
COMPRESSION_JPEG = 7


def jpeg_bytes(size, colour=(60, 120, 200), orientation=None):
    buf = io.BytesIO()
    img = Image.new("RGB", size, colour)
    if orientation is None:
        img.save(buf, format="JPEG", quality=80)
    else:
        exif = img.getexif()
        exif[ORIENTATION] = orientation
        img.save(buf, format="JPEG", quality=80, exif=exif)
    return buf.getvalue()


class _Writer:
    """Lays out data blocks and IFDs, resolving offsets as it goes."""

    def __init__(self, order="<"):
        self.order = order
        magic = b"II" if order == "<" else b"MM"
        self.out = bytearray(magic + struct.pack(f"{order}HL", 42, 0))

    def blob(self, data: bytes) -> int:
        if len(self.out) % 2:
            self.out += b"\x00"
        at = len(self.out)
        self.out += data
        return at

    def ifd(self, entries: list, next_ifd: int = 0) -> int:
        """entries: (tag, type, values). `values` is bytes for BYTE/ASCII."""
        order = self.order
        if len(self.out) % 2:
            self.out += b"\x00"
        at = len(self.out)
        entries = sorted(entries, key=lambda e: e[0])
        body = bytearray(struct.pack(f"{order}H", len(entries)))
        tail = bytearray()
        tail_base = at + 2 + 12 * len(entries) + 4

        for tag, typ, values in entries:
            if isinstance(values, bytes):
                raw, count = values, len(values)
            else:
                count = len(values)
                raw = struct.pack(f"{order}{{}}{'H' if typ == SHORT else 'L'}"
                                  .format(count), *values)
            body += struct.pack(f"{order}HHL", tag, typ, count)
            if len(raw) <= 4:
                body += raw.ljust(4, b"\x00")
            else:
                body += struct.pack(f"{order}L", tail_base + len(tail))
                tail += raw
                if len(tail) % 2:
                    tail += b"\x00"
        body += struct.pack(f"{order}L", next_ifd)
        self.out += bytes(body) + bytes(tail)
        return at

    def finish(self, first_ifd: int) -> bytes:
        out = bytearray(self.out)
        struct.pack_into(f"{self.order}L", out, 4, first_ifd)
        return bytes(out)


def build_dng(*, thumb_size=(320, 240), preview_size=(4032, 3024),
              with_preview=True, order="<", dng_version=True,
              taken_at=None, thumb_orientation=None, preview_orientation=None,
              preview_photometric=PHOTOMETRIC_YCBCR,
              corrupt_preview=False) -> bytes:
    """A DNG. Defaults give the common case: a small thumbnail in IFD0 and a
    full-size rendered preview hidden in a SubIFD."""
    w = _Writer(order)

    thumb = jpeg_bytes(thumb_size, (190, 60, 60), thumb_orientation)
    thumb_at = w.blob(thumb)

    raw_w, raw_h = preview_size
    raw_len = max(64, raw_w * raw_h // 256)
    raw_at = w.blob(b"\x00" * raw_len)

    if with_preview:
        preview = jpeg_bytes(preview_size, (60, 120, 200), preview_orientation)
        if corrupt_preview:
            # Claims to be a JPEG in the tags; is not one in the bytes.
            preview = b"\x00\x00\x00\x00" + preview[4:]
        preview_at = w.blob(preview)

    # SubIFD: the sensor data. A picture-shaped thing that is not a picture.
    sub = [w.ifd([
        (NEW_SUBFILE_TYPE, LONG, [0]),
        (IMAGE_WIDTH, LONG, [raw_w]),
        (IMAGE_LENGTH, LONG, [raw_h]),
        (BITS_PER_SAMPLE, SHORT, [16]),
        (COMPRESSION, SHORT, [COMPRESSION_JPEG]),
        (PHOTOMETRIC, SHORT, [PHOTOMETRIC_CFA]),
        (SAMPLES_PER_PIXEL, SHORT, [1]),
        (ROWS_PER_STRIP, LONG, [raw_h]),
        (STRIP_OFFSETS, LONG, [raw_at]),
        (STRIP_BYTE_COUNTS, LONG, [raw_len]),
    ])]

    if with_preview:
        sub.append(w.ifd([
            (NEW_SUBFILE_TYPE, LONG, [1]),
            (IMAGE_WIDTH, LONG, [preview_size[0]]),
            (IMAGE_LENGTH, LONG, [preview_size[1]]),
            (COMPRESSION, SHORT, [COMPRESSION_JPEG]),
            (PHOTOMETRIC, SHORT, [preview_photometric]),
            (SAMPLES_PER_PIXEL, SHORT, [3]),
            (BITS_PER_SAMPLE, SHORT, [8, 8, 8]),
            (ROWS_PER_STRIP, LONG, [preview_size[1]]),
            (STRIP_OFFSETS, LONG, [preview_at]),
            (STRIP_BYTE_COUNTS, LONG, [len(preview)]),
        ]))

    entries = [
        (NEW_SUBFILE_TYPE, LONG, [1]),
        (IMAGE_WIDTH, LONG, [thumb_size[0]]),
        (IMAGE_LENGTH, LONG, [thumb_size[1]]),
        (COMPRESSION, SHORT, [COMPRESSION_JPEG]),
        (PHOTOMETRIC, SHORT, [PHOTOMETRIC_YCBCR]),
        (SAMPLES_PER_PIXEL, SHORT, [3]),
        (BITS_PER_SAMPLE, SHORT, [8, 8, 8]),
        (ROWS_PER_STRIP, LONG, [thumb_size[1]]),
        (STRIP_OFFSETS, LONG, [thumb_at]),
        (STRIP_BYTE_COUNTS, LONG, [len(thumb)]),
        (MAKE, ASCII, b"Apple\x00"),
        (MODEL, ASCII, b"iPhone 15 Pro\x00"),
        (SUB_IFDS, LONG, sub),
    ]
    if dng_version:
        entries.append((DNG_VERSION, BYTE, b"\x01\x06\x00\x00"))
    if thumb_orientation:
        entries.append((ORIENTATION, SHORT, [thumb_orientation]))
    if taken_at:
        exif_ifd = w.ifd([
            (DATETIME_ORIGINAL, ASCII, taken_at.encode() + b"\x00"),
        ])
        entries.append((EXIF_IFD, LONG, [exif_ifd]))

    return w.finish(w.ifd(entries))
