"""A103: a RAW photo must survive the whole pipeline, not just ingest.

This is A93's bug wearing different clothes, and the shape is worth naming
because it has now happened twice:

* the browser uploads the ORIGINAL file, so `original_key` holds whatever
  the camera wrote;
* ingest writes JPEG display and thumbnail copies, so the tray looks
  perfect and the customer has no reason to suspect anything;
* the preview and the print render both read the ORIGINAL.

Where A93's original was HEIC and simply failed to open, this one is worse.
A DNG is a TIFF container whose IFD0 is a thumbnail, so `Image.open` does
NOT fail — it returns 320x240 and the book prints a postage stamp with
nothing anywhere reporting a problem.

Half a fix would have been worse than none: correcting only the size ingest
reports leaves the photo measuring 4032x3024 in the tray, passing the
low-resolution check, and still printing small. So what these assert is the
size of the pixels the COMPOSITOR actually drew.

The subprocess is the same trick A93 used, for the same reason: in-process
the whole app is already imported, so an assertion here would pass whatever
the render path can reach on its own.
"""
import io
import subprocess
import sys
import textwrap

from PIL import Image

from tests.dng_fixture import build_dng

# Deliberately lopsided: 2400x1600 is 3:2, while the thumbnail hiding in
# IFD0 is 4:3. If anything downstream grabs the wrong image, the aspect
# ratio gives it away as well as the size.
RAW = build_dng(thumb_size=(320, 240), preview_size=(2400, 1600))


def run_isolated(body: str, data: bytes) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(body)],
        input=data, capture_output=True, timeout=120,
    )


def answer(proc: subprocess.CompletedProcess) -> str:
    """The snippet's last line. The extraction logs as it works, and that
    log goes to stdout in a bare interpreter — so the answer is the last
    line, not the whole stream."""
    lines = [ln for ln in proc.stdout.decode().splitlines() if ln.strip()]
    assert lines, proc.stderr.decode()[-900:]
    return lines[-1].strip()


class TestTheRenderPathResolvesARaw:
    def test_the_reader_hands_over_the_picture_not_the_container(self):
        """`read_original` is the only thing standing between a DNG in
        storage and a decoder that would quietly take its thumbnail."""
        proc = run_isolated("""
            import io, sys
            from PIL import Image
            from app.services.image_processing import source_pixels
            img = Image.open(io.BytesIO(source_pixels(sys.stdin.buffer.read())))
            print(f"{img.width}x{img.height}")
        """, RAW)
        assert proc.returncode == 0, proc.stderr.decode()[-900:]
        assert answer(proc) == "2400x1600", (
            "the render path resolved a DNG to its thumbnail")

    def test_a_page_is_composed_from_the_full_size_picture(self):
        """The compositor is where it would actually show. A page built from
        the 320x240 thumbnail is the printed postage stamp."""
        proc = run_isolated("""
            import io, json, sys
            from PIL import Image
            from app.render.compose import compose_page
            from app.services.image_processing import source_pixels

            raw = sys.stdin.buffer.read()
            page = {"bg_color": "#ffffff", "placements": [
                {"photo_id": "p1", "x_mm": -3, "y_mm": -3,
                 "w_mm": 154, "h_mm": 216}]}
            out = compose_page(page, {"p1": source_pixels(raw)})
            print(len(out))
        """, RAW)
        assert proc.returncode == 0, proc.stderr.decode()[-900:]
        assert int(answer(proc)) > 0

    def test_bare_pillow_would_have_taken_the_thumbnail(self):
        """The canary. If this ever stops reporting 320x240, either Pillow
        learned to read DNGs properly or the fixture stopped being shaped
        like one — and every test above has quietly stopped meaning
        anything."""
        img = Image.open(io.BytesIO(RAW))
        assert (img.width, img.height) == (320, 240), (
            "the fixture no longer reproduces the bug")


class TestTheFixtureIsHonest:
    def test_the_real_picture_really_is_in_there(self):
        """Guards against proving something about a file that only we could
        ever produce: the picture has to be present and decodable, just not
        where a naive reader looks."""
        from app.services import dng

        assert dng.is_dng(RAW)
        found = Image.open(io.BytesIO(dng.largest_embedded_image(RAW)))
        assert (found.width, found.height) == (2400, 1600)
