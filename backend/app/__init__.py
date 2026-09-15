"""The backend package.

The one thing that happens on import: HEIF/HEIC decoding is registered with
Pillow (A93).

This belongs here, and nowhere else, because of how it failed. The
registration lived in `app.services.image_processing` — the module that
makes thumbnails — so any process that imported THAT module could read an
iPhone photo and any process that did not, could not. In development that
distinction never appears: `TASK_EAGER` runs ingest, preview and render in
the one API process, which imports the photos service and therefore
registers the opener. In production the RQ worker forks per job, so a
preview job imported the render path and never the photos service, and
`Image.open` on the stored original raised `UnidentifiedImageError`.

The result was that every customer with an iPhone got a failed preview —
their thumbnails were fine, because ingest wrote JPEG copies, but the
preview and the print render both read the ORIGINAL, which is still HEIC.

Registering a codec is a process-wide, idempotent act, so it belongs at the
process-wide level. Python imports parent packages first, which means any
`import app.anything` has already run this line: there is no longer a way
to reach our imaging code without it.
"""
import pillow_heif

pillow_heif.register_heif_opener()
