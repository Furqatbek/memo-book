"""P2-4: an uploaded photo knows where the customer lives.

A phone writes GPS coordinates into EXIF, so a family photograph taken at
home carries the home address. Everything we derive from that file goes
somewhere the original does not: the display JPEG and the preview go to a
browser over a presigned URL, and the print PDF goes to the PRINTER — a
third party, over Telegram. A derivative that kept its EXIF would hand
them the customer's front door.

`image_processing` says in a comment that derivatives carry no metadata.
This file is the part that checks, because a comment is not a test and the
way this breaks is somebody adding `exif=` to a `save()` call to fix a
rotation bug — a reasonable-looking change that silently re-attaches the
coordinates to every page of every book.

The original upload keeps its EXIF on purpose: it is the customer's own
file, we need `taken_at` off it for R2, and it is never sent anywhere.
"""
import io

import pytest
from PIL import Image
from PIL.ExifTags import IFD

from app.render.compose import compose_page
from app.render.preview import render_preview_page
from app.services.image_processing import process_image

# 41°18'N 69°16'E — a residential address in Tashkent, written the way a
# phone writes it.
LAT = (41.0, 18.0, 0.0)
LON = (69.0, 16.0, 0.0)


def gps_jpeg(w: int = 2400, h: int = 1800) -> bytes:
    exif = Image.Exif()
    exif[0x0132] = "2026:06:01 10:00:00"          # DateTime, which we DO want
    gps = exif.get_ifd(IFD.GPSInfo)
    gps[1], gps[2] = "N", LAT
    gps[3], gps[4] = "E", LON
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (30, 120, 90)).save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def assert_no_metadata(data: bytes, what: str) -> None:
    """No EXIF block, no GPS IFD, and nothing that decodes as either."""
    img = Image.open(io.BytesIO(data))
    exif = img.getexif()
    assert list(exif.keys()) == [], f"{what} carries EXIF tags {list(exif.keys())}"
    assert not dict(exif.get_ifd(IFD.GPSInfo)), f"{what} carries a GPS IFD"
    # Belt and braces: the JPEG APP1 marker introduces an EXIF segment, and
    # its absence is checkable without trusting the parser that just told us
    # there were no tags.
    assert b"Exif\x00\x00" not in data, f"{what} still has an APP1 EXIF segment"


def test_the_fixture_really_does_carry_coordinates():
    """Guards the other tests: if the fixture silently stopped carrying GPS,
    every assertion below would pass while proving nothing."""
    raw = gps_jpeg()
    exif = Image.open(io.BytesIO(raw)).getexif()
    assert dict(exif.get_ifd(IFD.GPSInfo))[2] == LAT
    assert b"Exif\x00\x00" in raw


class TestIngestDerivatives:
    def test_the_display_jpeg_has_no_exif(self):
        assert_no_metadata(process_image(gps_jpeg()).display_jpeg, "display_jpeg")

    def test_the_thumbnail_has_no_exif(self):
        assert_no_metadata(process_image(gps_jpeg()).thumb_jpeg, "thumb_jpeg")

    def test_the_date_is_still_read_off_the_original(self):
        """Stripping the derivatives must not cost us R2: `taken_at` is
        extracted from the upload BEFORE anything is re-encoded (R5)."""
        assert process_image(gps_jpeg()).taken_at is not None


class TestWhatLeavesTheBuilding:
    """The two surfaces that reach somebody other than the customer."""

    PAGE = {
        "layout": "full",
        "placements": [{"photo_id": "p1", "x_mm": 0, "y_mm": 0,
                        "w_mm": 148, "h_mm": 210, "rotation": 0, "fit": "cover"}],
        "texts": [], "stickers": [], "background": None,
    }

    def test_a_composed_print_page_has_no_exif(self):
        """This JPEG is what the print PDF embeds, and that PDF is sent to
        the printer over Telegram."""
        assert_no_metadata(compose_page(self.PAGE, {"p1": gps_jpeg()}),
                           "the composed print page")

    def test_a_preview_page_has_no_exif(self):
        assert_no_metadata(render_preview_page(self.PAGE, {"p1": gps_jpeg()}),
                           "the preview page")

    @pytest.mark.parametrize("make", [
        lambda: compose_page(TestWhatLeavesTheBuilding.PAGE, {"p1": gps_jpeg()}),
        lambda: render_preview_page(TestWhatLeavesTheBuilding.PAGE, {"p1": gps_jpeg()}),
        lambda: process_image(gps_jpeg()).display_jpeg,
    ])
    def test_no_derivative_contains_the_coordinates_anywhere(self, make):
        """Not "has no EXIF tags" — the raw bytes are searched for the
        numbers themselves, in case they survive somewhere a tag parser does
        not look (a comment segment, an XMP packet)."""
        data = bytes(make())
        # EXIF rationals are pairs of 32-bit ints, so the coordinates are
        # searched for in the packed form a GPS IFD would actually contain
        # rather than as bare integers, which would match anything.
        for packed in (b"\x00\x00\x00\x29\x00\x00\x00\x01",   # 41/1
                       b"\x00\x00\x00\x45\x00\x00\x00\x01"):  # 69/1
            assert packed not in data, "GPS rationals survived into the output"
        assert b"GPSInfo" not in data
        assert b"http://ns.adobe.com/xap" not in data, "an XMP packet survived"
