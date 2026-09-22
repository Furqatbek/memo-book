"""The one place that reads a photo's uploaded bytes (A103).

`original_key` holds exactly what the customer sent us, and for a RAW file
that is a container rather than a picture: a DNG's own first image is a
thumbnail, so anything calling `storage.get_bytes` on it directly gets
320x240 and no error at all.

There were six such callers — the interior renderer, the cover renderer,
the back-cover renderer, and the three matching ones in the preview — and
every one of them would have printed a postage stamp. Six correct call
sites is not an invariant; one reader is. `tests/test_photo_bytes_reader.py`
holds it.
"""
from app import storage
from app.services.image_processing import source_pixels


def read_original(original_key: str) -> bytes:
    """A photo's pixels at full resolution, whatever container they arrived in.

    Synchronous, and takes the KEY rather than the Photo: every caller runs
    it in a worker thread, and touching an ORM instance from one is how a
    lazy load turns into a MissingGreenlet at the printer.
    """
    return source_pixels(storage.get_bytes(original_key))
