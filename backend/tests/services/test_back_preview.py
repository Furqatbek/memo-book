"""A95: a designed back has to appear in the preview.

The preview is the contract — the customer confirms what they saw. Before
this, a back panel earned a preview tile only by having photos on it, which
was right when the only alternative was a flat rectangle. A design's back
artwork changes that: the back can now be fully designed and carry no photos
at all, and a customer who is never shown it is confirming a book they have
not seen.
"""
import io

from PIL import Image

from app.render.compose import compose_page
from app.services.preview import _back_as_page

PLACEMENT = {"photo_id": "p1", "x_mm": -3, "y_mm": -3, "w_mm": 154, "h_mm": 216}


def image(colour, size=(900, 1200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, "JPEG", quality=95)
    return buf.getvalue()


class TestWhenTheBackEarnsATile:
    def test_a_truly_blank_back_still_gets_none(self):
        """Unchanged from A91: a preview of a flat rectangle tells nobody
        anything, and its absence is what `back_url: null` means."""
        assert _back_as_page({"bg_color": "#ffffff"}) is None

    def test_photos_alone_earn_one(self):
        page = _back_as_page({"bg_color": "#ffffff",
                              "back": {"layout": "full",
                                       "placements": [PLACEMENT]}})
        assert page is not None
        assert page["placements"] == [PLACEMENT]

    def test_artwork_alone_earns_one(self):
        """The new case. No photos, but there is something to see."""
        page = _back_as_page({"bg_color": "#ffffff"}, has_artwork=True)
        assert page is not None
        assert page["placements"] == [], "no photos, and that is fine"

    def test_artwork_and_photos_together(self):
        page = _back_as_page({"bg_color": "#112233",
                              "back": {"layout": "full",
                                       "placements": [PLACEMENT]}},
                             has_artwork=True)
        assert page["placements"] == [PLACEMENT]
        assert page["bg_color"] == "#112233"


class TestTheBackdropItself:
    def test_the_artwork_fills_the_page_behind_everything(self):
        raw = compose_page({"bg_color": "#00ff00", "placements": []}, {},
                           scale=0.2, bg_image_bytes=image((0, 0, 255)))
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        px = img.getpixel((img.width // 2, img.height // 2))
        assert abs(px[2] - 255) <= 6 and px[0] <= 6, (
            "the flat colour is still showing through the artwork")

    def test_a_photo_is_drawn_on_top_of_it(self):
        raw = compose_page(
            {"bg_color": "#00ff00", "placements": [PLACEMENT]},
            {"p1": image((255, 255, 0))},
            scale=0.2, bg_image_bytes=image((0, 0, 255)))
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        px = img.getpixel((img.width // 2, img.height // 2))
        assert px[0] > 200 and px[1] > 200, "the artwork covered the photo"

    def test_pages_without_one_are_unchanged(self):
        """Every interior page in every book. This argument is new, and a
        new argument that alters the default is a silent reformat of the
        whole catalogue."""
        plain = compose_page({"bg_color": "#00ff00", "placements": []}, {},
                             scale=0.2)
        same = compose_page({"bg_color": "#00ff00", "placements": []}, {},
                            scale=0.2, bg_image_bytes=None)
        assert plain == same
