"""Ingest pipeline core (spec Part 6 + the 'Image ingest' block of 9.2)."""
import io
from datetime import UTC, datetime

import pytest
from PIL import Image
from PIL.ExifTags import IFD

from app.services import image_processing as ip
from app.services.image_processing import IngestError, process_image

TS = "2026:06:01 10:30:00"
TS_DT = datetime(2026, 6, 1, 10, 30, tzinfo=UTC)


def build_exif(datetime_str: str | None = None, orientation: int | None = None) -> Image.Exif:
    exif = Image.Exif()
    if datetime_str:
        exif[ip.EXIF_DATETIME] = datetime_str
        # DateTimeOriginal lives in the nested Exif IFD.
        exif.get_ifd(IFD.Exif)[ip.EXIF_DATETIME_ORIGINAL] = datetime_str
    if orientation:
        exif[ip.EXIF_ORIENTATION] = orientation
    return exif


def jpeg_bytes(w=800, h=600, exif: Image.Exif | None = None, color=(200, 60, 40)) -> bytes:
    img = Image.new("RGB", (w, h), color)
    out = io.BytesIO()
    img.save(out, format="JPEG", exif=exif.tobytes() if exif else b"")
    return out.getvalue()


def png_alpha_bytes(w=400, h=300) -> bytes:
    img = Image.new("RGBA", (w, h), (255, 0, 0, 0))  # fully transparent red
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def heic_bytes(w=640, h=480, datetime_str: str | None = TS) -> bytes:
    img = Image.new("RGB", (w, h), (30, 90, 160))
    out = io.BytesIO()
    exif = build_exif(datetime_str)
    img.save(out, format="HEIF", exif=exif.tobytes())
    return out.getvalue()


class TestBasicJpeg:
    def test_dimensions_hash_and_derivatives(self):
        data = jpeg_bytes(3000, 2000)
        result = process_image(data)
        assert (result.width, result.height) == (3000, 2000)
        assert len(result.sha256) == 64

        display = Image.open(io.BytesIO(result.display_jpeg))
        assert max(display.size) == ip.DISPLAY_LONG_EDGE
        thumb = Image.open(io.BytesIO(result.thumb_jpeg))
        assert max(thumb.size) == ip.THUMB_LONG_EDGE

    def test_taken_at_extracted_from_exif(self):
        data = jpeg_bytes(exif=build_exif(TS))
        assert process_image(data).taken_at == TS_DT

    def test_no_exif_means_no_taken_at(self):
        assert process_image(jpeg_bytes()).taken_at is None


class TestOrientation:
    def test_orientation_6_is_applied_physically(self):
        # 400x200 landscape tagged orientation 6 (90° CW needed) becomes
        # 200x400 portrait after physical rotation (R4).
        data = jpeg_bytes(400, 200, exif=build_exif(orientation=6))
        result = process_image(data)
        assert (result.width, result.height) == (200, 400)
        assert result.original_orientation == 6

        display = Image.open(io.BytesIO(result.display_jpeg))
        assert display.height > display.width  # derivative physically rotated


class TestMetadataStripping:
    def test_derivatives_carry_no_exif(self):
        data = jpeg_bytes(exif=build_exif(TS, orientation=6))
        result = process_image(data)
        for derived in (result.display_jpeg, result.thumb_jpeg):
            img = Image.open(io.BytesIO(derived))
            assert dict(img.getexif()) == {}
            assert "exif" not in img.info


class TestAlphaFlattening:
    def test_png_alpha_flattens_to_white(self):
        result = process_image(png_alpha_bytes())
        display = Image.open(io.BytesIO(result.display_jpeg))
        assert display.mode == "RGB"
        r, g, b = display.getpixel((10, 10))
        assert r > 240 and g > 240 and b > 240  # transparent area became white


class TestHeic:
    def test_heic_converts_and_taken_at_survives(self):
        """The R5 regression test: HEIC decodes AND taken_at is extracted
        before conversion. If a conversion path strips EXIF, every iPhone
        book ships shuffled with no error anywhere."""
        result = process_image(heic_bytes())
        assert result.taken_at == TS_DT
        assert result.width == 640
        display = Image.open(io.BytesIO(result.display_jpeg))
        assert display.format == "JPEG"


class TestValidation:
    def test_garbage_with_jpg_name_rejected(self):
        with pytest.raises(IngestError, match="not a valid image"):
            process_image(b"this is definitely not an image" * 100)

    def test_empty_file_rejected(self):
        with pytest.raises(IngestError, match="empty"):
            process_image(b"")

    def test_oversized_side_rejected_before_decode(self):
        # A real >15000px side: 15001x2 is only ~30k pixels, tiny to build,
        # but the header check must reject it.
        img = Image.new("RGB", (15_001, 2))
        out = io.BytesIO()
        img.save(out, format="PNG")
        with pytest.raises(IngestError, match="per side"):
            process_image(out.getvalue())

    def test_pixel_bomb_rejected(self, monkeypatch):
        monkeypatch.setattr(ip, "MAX_PIXELS", 10_000)
        with pytest.raises(IngestError, match="pixels exceed"):
            process_image(jpeg_bytes(200, 100))

    def test_byte_limit_rejected(self, monkeypatch):
        monkeypatch.setattr(ip, "MAX_BYTES", 10)
        with pytest.raises(IngestError, match="exceeds"):
            process_image(jpeg_bytes())
