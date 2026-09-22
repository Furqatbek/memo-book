"""Reading a Digital Negative (A103).

A DNG is a TIFF container, and that is the entire problem. Every ordinary
image reader opens one without complaining and hands back IFD0 — which in a
DNG is a **thumbnail**. Measured on a file laid out the way a phone writes
one: Pillow opened it, reported 320x240, `process_image` returned that as
the photo's dimensions, and the 4032x3024 image sat in the file the whole
time in a SubIFD nothing had looked at.

Nothing errored. That is what makes it the worst kind of bug here: the
photo would have gone into a book at postage-stamp resolution, and the only
thing standing between that and a printed book was the low-resolution
warning — which would have been telling the customer their photo was too
small while the sharp version was inside the file they gave us.

**Where the real picture lives.** IFD0 carries `SubIFDs` (tag 330), a list
of offsets to further IFDs. One of them is the sensor data — a Bayer mosaic
under lossless JPEG, which is not an image anything here can decode without
a raw processor. The others are previews the camera rendered itself, and
those are ordinary JPEGs.

**We take the camera's rendering, not our own.** Even with a raw processor
on hand, the embedded preview is the better source for a photo book: it is
what the customer saw on their phone and what they think the photo looks
like. A demosaic of our own would be flatter and differently coloured —
technically "more faithful" to the sensor and less faithful to the person.

**Sniffed from the bytes, never from the declared type.** The upload's
content type is whatever the browser said, and a DNG renamed to .jpg is
still a DNG. This reads the container.

What this module does NOT do is judge. It returns the largest image really
present; whether that is big enough to print is `domain/resolution.py`'s
call, and that module classifies rather than refuses on purpose (A79).
"""
import struct

import structlog

log = structlog.get_logger()

BYTE_ORDERS = {b"II": "<", b"MM": ">"}
TIFF_MAGIC = 42

TAG_IMAGE_WIDTH = 256
TAG_IMAGE_LENGTH = 257
TAG_COMPRESSION = 259
TAG_PHOTOMETRIC = 262
TAG_STRIP_OFFSETS = 273
TAG_STRIP_BYTE_COUNTS = 279
TAG_SUB_IFDS = 330
TAG_JPEG_OFFSET = 513          # JPEGInterchangeFormat
TAG_JPEG_LENGTH = 514          # JPEGInterchangeFormatLength
TAG_DNG_VERSION = 50706

# Compression codes that mean "the strip is a JPEG": old-style JPEG, the
# TIFF 6 "new JPEG", and the lossy JPEG a lossy DNG uses.
JPEG_COMPRESSIONS = frozenset({6, 7, 34892})

# What the pixels MEAN. 2 is RGB and 6 is YCbCr — a picture. 32803 (CFA) and
# 34892 (LinearRaw) are sensor data wearing a JPEG coat, and decoding one as
# a photograph gives a green-tinted mosaic, not a smaller picture.
RENDERED_PHOTOMETRICS = frozenset({2, 6})

JPEG_SOI = b"\xff\xd8\xff"

# Bounds for walking a structure that arrived over the internet. A TIFF is a
# graph of offsets and nothing stops one pointing at itself.
MAX_IFDS = 64
MAX_ENTRIES = 512

# (type code) -> (struct code, bytes each). Only the integer types are here;
# nothing below needs a rational or a float.
INT_TYPES = {1: ("B", 1), 3: ("H", 2), 4: ("L", 4), 9: ("l", 4), 13: ("L", 4)}


class _Reader:
    def __init__(self, data: bytes, order: str):
        self.data = data
        self.order = order

    def ints(self, type_code: int, count: int, entry_at: int) -> list[int]:
        """The values of one IFD entry, or [] for anything malformed.

        Total and forgiving by design: a tag we cannot read is a tag we do
        not use, and a file that is wrong in one corner is very often still
        right in the corner holding the picture.
        """
        spec = INT_TYPES.get(type_code)
        if spec is None or count <= 0 or count > MAX_ENTRIES:
            return []
        code, size = spec
        total = size * count
        if total <= 4:
            at = entry_at + 8
        else:
            (at,) = struct.unpack_from(f"{self.order}L", self.data, entry_at + 8)
        if at < 0 or at + total > len(self.data):
            return []
        try:
            return list(struct.unpack_from(f"{self.order}{count}{code}",
                                           self.data, at))
        except struct.error:
            return []


def _parse_header(data: bytes) -> tuple[str, int] | None:
    if len(data) < 8:
        return None
    order = BYTE_ORDERS.get(data[:2])
    if order is None:
        return None
    magic, first_ifd = struct.unpack_from(f"{order}HL", data, 2)
    if magic != TIFF_MAGIC or not 8 <= first_ifd < len(data):
        return None
    return order, first_ifd


def _read_ifd(reader: _Reader, offset: int) -> tuple[dict[int, list[int]], int]:
    """One IFD as {tag: values}, plus the offset of the next one (0 if none)."""
    data, order = reader.data, reader.order
    if offset + 2 > len(data):
        return {}, 0
    (count,) = struct.unpack_from(f"{order}H", data, offset)
    if count <= 0 or count > MAX_ENTRIES:
        return {}, 0
    end = offset + 2 + 12 * count
    if end + 4 > len(data):
        return {}, 0

    tags: dict[int, list[int]] = {}
    for i in range(count):
        entry_at = offset + 2 + 12 * i
        tag, type_code, values = struct.unpack_from(f"{order}HHL", data, entry_at)
        tags[tag] = reader.ints(type_code, values, entry_at)
    (next_ifd,) = struct.unpack_from(f"{order}L", data, end)
    return tags, next_ifd if 8 <= next_ifd < len(data) else 0


def _walk(data: bytes, order: str, first_ifd: int):
    """Every IFD in the file: the top-level chain and the SubIFDs hanging off
    it. Offsets already visited are skipped, so a file that points at itself
    ends the walk instead of running forever."""
    reader = _Reader(data, order)
    pending = [first_ifd]
    seen: set[int] = set()
    while pending and len(seen) < MAX_IFDS:
        offset = pending.pop(0)
        if offset in seen or not 8 <= offset < len(data):
            continue
        seen.add(offset)
        tags, next_ifd = _read_ifd(reader, offset)
        if not tags:
            continue
        yield tags
        if next_ifd:
            pending.append(next_ifd)
        pending.extend(tags.get(TAG_SUB_IFDS) or [])


def _first(tags: dict[int, list[int]], tag: int, default: int = 0) -> int:
    values = tags.get(tag) or []
    return values[0] if values else default


def _embedded_jpeg(data: bytes, tags: dict) -> tuple[int, int, bytes] | None:
    """(width, height, jpeg bytes) for one IFD, if it holds a real picture.

    Two ways a JPEG is attached: `JPEGInterchangeFormat`, which is a whole
    JPEG file at an offset, or a single JPEG-compressed strip. Both are
    accepted; anything spread over several strips is not, because stitching
    strips back together is a decoder's job and the previews we are after
    are never written that way.
    """
    if _first(tags, TAG_COMPRESSION) not in JPEG_COMPRESSIONS:
        return None
    if _first(tags, TAG_PHOTOMETRIC) not in RENDERED_PHOTOMETRICS:
        return None

    width, height = _first(tags, TAG_IMAGE_WIDTH), _first(tags, TAG_IMAGE_LENGTH)

    offsets = tags.get(TAG_JPEG_OFFSET) or tags.get(TAG_STRIP_OFFSETS) or []
    lengths = tags.get(TAG_JPEG_LENGTH) or tags.get(TAG_STRIP_BYTE_COUNTS) or []
    if len(offsets) != 1 or len(lengths) != 1:
        return None
    at, size = offsets[0], lengths[0]
    if size <= 0 or at < 0 or at + size > len(data):
        return None

    blob = data[at:at + size]
    # The tags said JPEG; the bytes have the last word. A strip that does not
    # start with SOI is something else, and handing it to a decoder as an
    # image is how a container becomes an attack surface.
    if not blob.startswith(JPEG_SOI):
        return None
    return width, height, blob


def is_dng(data: bytes) -> bool:
    """Read from the container, not from the file name or the declared type."""
    header = _parse_header(data)
    if header is None:
        return False
    order, first_ifd = header
    for tags in _walk(data, order, first_ifd):
        return TAG_DNG_VERSION in tags     # IFD0 carries it; only IFD0 is checked
    return False


def largest_embedded_image(data: bytes) -> bytes | None:
    """The biggest picture actually inside this DNG, or None if there is none.

    Biggest by pixel count, because "the first one" is precisely the bug this
    exists to fix — in a DNG the first one is the thumbnail.
    """
    header = _parse_header(data)
    if header is None:
        return None
    order, first_ifd = header

    best: tuple[int, int, bytes] | None = None
    for tags in _walk(data, order, first_ifd):
        found = _embedded_jpeg(data, tags)
        if found is None:
            continue
        if best is None or found[0] * found[1] > best[0] * best[1]:
            best = found

    if best is None:
        return None
    log.info("dng.preview_extracted", width=best[0], height=best[1],
             bytes=len(best[2]))
    return best[2]
