"""Page/cover background and title colours flow into the print rasters."""
import io

from PIL import Image

from app.render.compose import compose_page, hex_to_rgb
from app.render.cover import _compose_cover_raster, build_cover_pdf, cover_geometry
from tests.render.helpers import solid_jpeg


def close(a: tuple, b: tuple, tol: int = 12) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b, strict=True))


def test_hex_to_rgb_parses_and_defaults():
    assert hex_to_rgb("#1a2b3c") == (26, 43, 60)
    assert hex_to_rgb(None) == (255, 255, 255)
    assert hex_to_rgb("nonsense") == (255, 255, 255)


def test_page_bg_color_fills_around_inset_placement():
    page = {
        "index": 0, "bg_color": "#204060",
        "placements": [{"photo_id": "p1", "x_mm": 30, "y_mm": 30,
                        "w_mm": 88, "h_mm": 120, "rotation": 0, "fit": "cover"}],
        "texts": [],
    }
    jpeg = compose_page(page, {"p1": solid_jpeg(600, 800, (200, 20, 20))}, scale=0.25)
    img = Image.open(io.BytesIO(jpeg))
    assert close(img.getpixel((3, 3)), (32, 64, 96))              # bg corner
    assert close(img.getpixel((img.width // 2, img.height // 2)), (200, 20, 20))


def test_contain_letterbox_uses_page_bg():
    page = {
        "index": 0, "bg_color": "#ffcc00",
        "placements": [{"photo_id": "p1", "x_mm": -3, "y_mm": -3,
                        "w_mm": 154, "h_mm": 216, "rotation": 0, "fit": "contain"}],
        "texts": [],
    }
    jpeg = compose_page(page, {"p1": solid_jpeg(800, 200, (20, 20, 200))}, scale=0.25)
    img = Image.open(io.BytesIO(jpeg))
    assert close(img.getpixel((img.width // 2, 3)), (255, 204, 0))  # letterbox band


def test_cover_bg_color_without_photo():
    cover = {"title": "T", "bg_color": "#803010"}
    geo = cover_geometry(16)
    raster = _compose_cover_raster(cover, geo, None)
    img = Image.open(io.BytesIO(raster))
    assert close(img.getpixel((5, 5)), (128, 48, 16))


def test_cover_pdf_with_custom_title_color_builds():
    cover = {"title": "Our Trip", "subtitle": "2026", "title_size_pt": 28,
             "title_color": "#ffee00", "bg_color": "#101820"}
    pdf = build_cover_pdf(cover, 16, None, cache_tag="colors-test")
    assert pdf.startswith(b"%PDF")
