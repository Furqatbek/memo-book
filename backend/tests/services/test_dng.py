"""A103: reading a Digital Negative.

The load-bearing test here is `test_the_full_size_preview_wins_over_the_thumbnail`.
A DNG is a TIFF container, so every ordinary image reader opens one without
complaining and hands back IFD0 — which is a thumbnail. Nothing errors; the
photo simply becomes 320x240 and prints like a postage stamp. Everything
else in this file exists to stop that being traded for a different silent
wrong answer: sensor data decoded as a picture, or a strip that says JPEG
and is not.
"""
import io
import struct

import pytest
from PIL import Image

from app.services import dng
from tests.dng_fixture import PHOTOMETRIC_CFA, build_dng, jpeg_bytes


def size_of(blob: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(blob)).size


class TestRecognisingOne:
    def test_a_dng_is_recognised(self):
        assert dng.is_dng(build_dng()) is True

    def test_from_either_byte_order(self):
        """Most raw files are little-endian; some cameras write big-endian,
        and a photo that depends on whose camera it came out of is a photo
        we would lose for no reason anybody could explain."""
        assert dng.is_dng(build_dng(order="<")) is True
        assert dng.is_dng(build_dng(order=">")) is True

    def test_a_tiff_without_the_dng_tag_is_not_a_dng(self):
        """Being a TIFF is not enough. The DNGVersion tag is what says the
        IFD0 image is a preview of something else."""
        assert dng.is_dng(build_dng(dng_version=False)) is False

    @pytest.mark.parametrize("fmt", ["JPEG", "PNG", "TIFF", "BMP"])
    def test_ordinary_images_are_not_dngs(self, fmt):
        buf = io.BytesIO()
        Image.new("RGB", (32, 32), "red").save(buf, format=fmt)
        assert dng.is_dng(buf.getvalue()) is False

    @pytest.mark.parametrize("data", [
        b"",
        b"II",
        b"II*\x00",
        b"II*\x00\xff\xff\xff\xff",          # first IFD past the end
        b"XX*\x00\x08\x00\x00\x00",          # not a byte order we know
        b"II\x00\x00\x08\x00\x00\x00",       # not magic 42
        b"nothing to see here",
    ])
    def test_rubbish_is_refused_without_raising(self, data):
        """This parses a structure that arrived over the internet, so every
        shape that is not ours has to be a `False`, never a traceback."""
        assert dng.is_dng(data) is False
        assert dng.largest_embedded_image(data) is None


class TestFindingThePicture:
    def test_the_full_size_preview_wins_over_the_thumbnail(self):
        """THE one. IFD0 holds a 320x240 thumbnail and the SubIFD holds the
        4032x3024 picture the camera rendered. Taking the first image in the
        file is what silently turned a 12-megapixel photo into a postage
        stamp; taking the largest is the fix."""
        blob = dng.largest_embedded_image(build_dng())
        assert size_of(blob) == (4032, 3024)

    def test_it_finds_the_picture_in_a_big_endian_file(self):
        assert size_of(dng.largest_embedded_image(build_dng(order=">"))) == (4032, 3024)

    def test_with_no_full_preview_the_thumbnail_is_all_there_is(self):
        """Honest rather than clever: some DNGs really do carry nothing but
        the sensor data and a thumbnail. We return the best thing present and
        let the low-resolution machinery say it will print badly — which is
        the policy everywhere else (A79)."""
        assert size_of(dng.largest_embedded_image(build_dng(with_preview=False))) == (320, 240)

    def test_sensor_data_is_never_mistaken_for_a_picture(self):
        """The raw SubIFD is JPEG-compressed too. What makes it not a
        photograph is its photometric interpretation: a Bayer mosaic decoded
        as an image is a green-tinted grid, not a smaller version of the
        picture."""
        blob = dng.largest_embedded_image(
            build_dng(preview_photometric=PHOTOMETRIC_CFA))
        # Only the thumbnail is left — the "preview" was sensor data.
        assert size_of(blob) == (320, 240)

    def test_a_strip_that_claims_jpeg_but_is_not_is_skipped(self):
        """The tags said JPEG; the bytes have the last word. Handing a
        decoder whatever a container points at is how a file format becomes
        an attack surface."""
        blob = dng.largest_embedded_image(build_dng(corrupt_preview=True))
        assert size_of(blob) == (320, 240)

    def test_a_dng_holding_no_picture_at_all_returns_none(self):
        """Not an exception: the caller turns this into a failure the
        customer can read, and it is the one case where "export a JPEG" is
        the only thing we can honestly tell them."""
        raw_only = build_dng(with_preview=False,
                             thumb_size=(8, 8))
        # Strip the thumbnail's JPEG magic so nothing decodable is left.
        broken = raw_only.replace(jpeg_bytes((8, 8), (190, 60, 60))[:3],
                                  b"\x00\x00\x00", 1)
        assert dng.largest_embedded_image(broken) is None


class TestItCannotBeMadeToHang:
    def test_an_ifd_pointing_at_itself_ends_the_walk(self):
        """A TIFF is a graph of offsets and nothing in the format stops one
        pointing back at itself. An ingest worker that spins forever on a
        malformed upload takes the queue with it."""
        data = bytearray(build_dng())
        # Point IFD0's "next IFD" at IFD0. Finding it: the first IFD offset
        # is in the header, and the next-IFD pointer follows its entries.
        (first,) = struct.unpack_from("<L", data, 4)
        (count,) = struct.unpack_from("<H", data, first)
        struct.pack_into("<L", data, first + 2 + 12 * count, first)
        assert dng.is_dng(bytes(data)) is True
        assert size_of(dng.largest_embedded_image(bytes(data))) == (4032, 3024)

    def test_a_subifd_pointing_into_the_middle_of_nowhere_is_skipped(self):
        data = build_dng()
        truncated = data[:len(data) // 2]
        # Whatever survives, it must answer rather than raise or loop.
        result = dng.largest_embedded_image(truncated)
        assert result is None or result.startswith(b"\xff\xd8\xff")
