"""A93: an iPhone photo must survive the whole pipeline, not just ingest.

The bug this exists to prevent, exactly:

* the browser uploads the ORIGINAL file, so an iPhone gives us HEIC;
* ingest writes JPEG display and thumbnail copies, so the tray looks
  perfect and the customer has no reason to suspect anything;
* the preview and the print render both read the ORIGINAL — still HEIC;
* `register_heif_opener()` lived in `app.services.image_processing`, which
  the render path does not import;
* in development `TASK_EAGER` runs everything in the one API process, which
  imports the photos service, so the opener was always registered and every
  check passed;
* in production the RQ worker forks per job, so the preview child imported
  the render path alone and `Image.open` raised
  `UnidentifiedImageError` — a failed preview for every customer with an
  iPhone.

**These tests run in a SUBPROCESS on purpose.** Inside pytest the registry
is already populated by some other test's imports, so asserting in-process
would pass no matter where the registration lives — which is precisely the
mistake that let this ship. The subprocess imports only the render path,
the way a forked worker does.
"""
import io
import subprocess
import sys
import textwrap

import pytest
from PIL import Image

pillow_heif = pytest.importorskip("pillow_heif")


@pytest.fixture(scope="module")
def heic_bytes() -> bytes:
    """A real HEIC file, made the way a phone hands us one."""
    pillow_heif.register_heif_opener()
    buf = io.BytesIO()
    Image.new("RGB", (1600, 1200), (200, 60, 40)).save(buf, format="HEIF", quality=80)
    return buf.getvalue()


def run_isolated(body: str, data: bytes) -> subprocess.CompletedProcess:
    """Run `body` in a fresh interpreter, HEIC on stdin. Nothing but what the
    snippet itself imports is loaded — no pytest, no conftest, no ingest."""
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(body)],
        input=data, capture_output=True, timeout=120,
    )


PAGE = ('{"bg_color": "#ffffff", "placements": [{"photo_id": "p1", '
        '"x_mm": -3, "y_mm": -3, "w_mm": 154, "h_mm": 216}]}')


def test_the_render_path_alone_can_open_an_iphone_photo(heic_bytes):
    """The whole bug in one assertion: a process that imports only the
    compositor — as a forked preview worker does — must still decode HEIC."""
    proc = run_isolated(f"""
        import json, sys
        from app.render.compose import compose_page
        assert "app.services.image_processing" not in sys.modules, (
            "this test is worthless if the ingest module is loaded")
        out = compose_page(json.loads('{PAGE}'), {{"p1": sys.stdin.buffer.read()}})
        print(len(out))
    """, heic_bytes)
    assert proc.returncode == 0, (
        f"the render path cannot read an iPhone photo:\n"
        f"{proc.stderr.decode()[-900:]}")
    assert int(proc.stdout) > 0


def test_the_cover_render_alone_can_open_an_iphone_photo(heic_bytes):
    """Same for the cover, which is a separate entry point and a separate
    import chain — a customer's cover photo is just as likely to be HEIC."""
    proc = run_isolated("""
        import sys
        from app.render.cover import build_cover_pdf
        assert "app.services.image_processing" not in sys.modules
        pdf = build_cover_pdf({"bg_color": "#ffffff", "title": "x"}, 32,
                              sys.stdin.buffer.read())
        print(len(pdf))
    """, heic_bytes)
    assert proc.returncode == 0, (
        f"the cover render cannot read an iPhone photo:\n"
        f"{proc.stderr.decode()[-900:]}")
    assert int(proc.stdout) > 0


def test_importing_anything_from_app_is_enough(heic_bytes):
    """The property that makes this hard to break again: the registration is
    in `app/__init__.py`, and Python imports parent packages first, so there
    is no way to reach our imaging code without it."""
    proc = run_isolated("""
        import sys
        import app.domain.geometry       # nothing to do with images
        from PIL import Image
        Image.open(__import__("io").BytesIO(sys.stdin.buffer.read())).load()
        print("ok")
    """, heic_bytes)
    assert proc.returncode == 0, proc.stderr.decode()[-900:]
    assert proc.stdout.strip() == b"ok"


def test_the_test_would_notice_if_the_registration_went_away(heic_bytes):
    """Pillow on its own cannot do this. If this ever starts passing, HEIC
    has become a built-in format and the tests above have stopped meaning
    anything."""
    proc = run_isolated("""
        import io, sys
        from PIL import Image
        Image.open(io.BytesIO(sys.stdin.buffer.read())).load()
        print("ok")
    """, heic_bytes)
    assert proc.returncode != 0, (
        "bare Pillow decoded HEIC — these tests no longer prove anything")
