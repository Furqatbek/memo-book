"""One reader for a photo's uploaded bytes (A103).

`original_key` holds what the customer actually sent, and for a RAW file
that is a container whose first image is a thumbnail. Six separate callers
read those bytes straight out of storage — the interior, cover and
back-cover renderers, and the same three in the preview — and every one of
them would have put a 320x240 thumbnail into a printed book without
reporting anything wrong.

Fixing six call sites is not a fix; it lasts until somebody adds a seventh.
This test is the invariant: `storage.get_bytes` is never handed an
`original_key` anywhere except `services/photo_bytes.py`, which is the one
place that knows a container may not be a picture.
"""
import pathlib
import re

SERVICES = pathlib.Path(__file__).resolve().parents[1] / "app"
READER = "photo_bytes.py"

# Two files may fetch an original, for opposite reasons, and both are the
# point rather than an exemption:
#
#   photo_bytes.py  wants the PICTURE, and unwraps the container to get it;
#   photos.py       wants the CONTAINER — ingest hands the whole file to
#                   `process_image`, which does its own extraction and hashes
#                   the uploaded bytes so that re-uploading the same DNG is
#                   still recognised as a duplicate.
#
# Anything else reading those bytes is reading a thumbnail and does not know
# it. This list is deliberately hard to extend: adding a name to it should
# require saying which of those two things the new caller wants.
ALLOWED = {READER, "photos.py"}

# A call that fetches an original from storage, on one line or split over
# several — `anyio.to_thread.run_sync(storage.get_bytes, photo.original_key)`
# wraps differently depending on how deep it sits.
UNSAFE = re.compile(r"get_bytes[^\n]{0,80}original_key"
                    r"|get_bytes\s*,?\s*\n[^\n]{0,80}original_key")


def python_files():
    for path in sorted(SERVICES.rglob("*.py")):
        if "__pycache__" not in path.parts:
            yield path


class TestOnlyOneReader:
    def test_nothing_else_fetches_an_original_from_storage(self):
        offenders = []
        for path in python_files():
            if path.name in ALLOWED:
                continue
            if UNSAFE.search(path.read_text()):
                offenders.append(str(path.relative_to(SERVICES.parent)))
        assert offenders == [], (
            "these read a photo's uploaded bytes directly; a DNG's first "
            "image is a thumbnail, so they must go through "
            f"services/photo_bytes.read_original instead: {offenders}")

    def test_the_reader_itself_still_does_the_extraction(self):
        """Guards the other half: the single reader is only worth having
        while it is the thing that unwraps a container."""
        source = (SERVICES / "services" / READER).read_text()
        assert "source_pixels" in source
        assert "storage.get_bytes" in source

    def test_the_renderers_use_it(self):
        """A reader nobody calls would pass the test above trivially."""
        for name in ("render.py", "preview.py"):
            source = (SERVICES / "services" / name).read_text()
            assert "read_original" in source, name
