# Implementation assumptions

The spec (Part 0) says to state assumptions before writing code. These are the
decisions taken where the spec left room; each is cheap to reverse now and
expensive later, so flag disagreements early.

**A1 — Monorepo layout.** The backend lives in `backend/` in the same
repository as the landing site. The Pages deploy workflow is unaffected.

**A2 — Python 3.11+, not 3.12-only.** The dev sandbox runs 3.11; CI and the
Docker image use 3.12. No 3.12-only syntax is used.

**A3 — Text clamping strategy.** A box larger than the safe area is first
shrunk to the safe area's size, then shifted fully inside it. The spec requires
"silently clamp and return the clamped value" but does not say whether to move
or shrink; shrink-then-shift guarantees the property "clamped result is always
inside the safe area" for every input.

**A4 — Resolution rule details.** Effective DPI is computed per axis and the
worse axis decides. Boundaries per spec table: exactly 200 → `ok`, exactly
100 → `warn`. The 800px floor applies when the placement covers the full trim
size or more (i.e. a full-page/full-bleed placement).

**A5 — `render_failed → rendering` is allowed** as the operator retry path.
The diagram shows no outgoing edge from `render_failed`, but Part 9 requires
"retry after a transient failure produces a valid PDF", which needs a legal
way back into `rendering`.

**A6 — `locked → draft` is allowed** so a cancelled payment unlocks the book
for further editing. Otherwise a cancelled checkout would strand the book.

**A7 — `refunded` is reachable from `shipped` and `delivered`.** The diagram's
branch point is ambiguous; both are accepted until the founder says otherwise.

**A8 — Ordering tie-breaks.** R2 defines taken_at → uploaded_at; a final
tie-break on photo id makes the sort fully deterministic even for identical
timestamps (required by the "never random" test).

**A9 — Effects are declared, not executed, by the domain.** `transition_order`
returns the effects a transition mandates (enqueue render, alert operator,
notify production). The service layer (later milestones) executes them; unit
tests can assert "exactly one render enqueue on entering paid" without infra.

**A10 — `/ready` storage check** uses S3 `head_bucket` (works for MinIO and
any S3-compatible provider), with a short timeout, run in a worker thread.

**A11 — `pillow`, `pillow-heif`, `rq`, `reportlab` are not yet dependencies.**
They enter `pyproject.toml` with their milestones (M4/M6) to keep the
dependency surface reviewable per milestone.

**A12 — `placements` allows 0 or 1 entries in MVP.** Part 12 says "a validator
enforcing len == 1", but a freshly created draft has empty pages, so the
validator enforces `len <= 1`; the "every page filled" requirement is checkout
eligibility's job (R1), not the layout schema's.

**A13 — `page-count` changes also require `If-Match`.** The endpoint rewrites
the layout document, so it participates in the same optimistic-concurrency
scheme as `PATCH /layout`. A missing header returns 428 VERSION_REQUIRED.

**A14 — `photo_id` values in placements are not existence-checked yet.**
Photos arrive in Milestone 4; referential validation joins checkout
eligibility (M5) and render preflight (M6).

**A15 — Auth failures return 404, not 401/403.** A wrong edit token is
byte-identical to a missing book, so the API cannot be used as an oracle for
which book ids exist.

**A16 — Tests run on Postgres when available, SQLite otherwise.** CI provides
a real Postgres 16 service (`TEST_DATABASE_URL`); the JSONB column degrades to
JSON on SQLite via a type variant. Testcontainers was skipped because the spec's
integration matrix is covered by CI's real Postgres with less machinery.

**A17 — Storage in tests is moto (in-process mocked S3),** with real presign
and object semantics; the spec's MinIO-via-testcontainers is equivalent here
and moto runs everywhere, including sandboxes without a Docker daemon. The
docker-compose MinIO remains the dev-stack storage.

**A18 — The HEIC fixture is generated with pillow-heif,** carrying real EXIF
(DateTimeOriginal + orientation), not committed from an actual iPhone. The
decode/EXIF-extraction path is identical; still, drop one genuine iPhone HEIC
into the fixtures before launch as the spec asks — camera files have quirks
synthetic ones don't.

**A19 — EXIF timestamps are stored as UTC.** EXIF has no timezone; R2 only
needs relative order within one trip, so a consistent convention beats a
guessed timezone.

**A20 — `resolution_status` in photo lists is computed for a full-bleed
placement** (the default use). The editor recalculates per actual placed size
with the same domain thresholds.

**A21 — Duplicate photos still get derivatives** so the editor can show what
the duplicate is; they are flagged `status=duplicate` with `duplicate_of`
pointing at the surviving photo. The backend never silently drops.

**A22 — `complete` verifies the object exists in storage** before enqueueing
ingest, and completing an already-processed photo is an idempotent no-op.

**A23 — "Usable" photos for auto-place and eligibility are `ready` and
`duplicate`.** Duplicates are placeable (the user chose to keep them); pending,
processing and failed photos count for nothing. The same definition is used in
both places so eligibility can never pass while auto-place under-fills.

**A24 — Auto-place writes full-bleed placements** (`-3,-3,154,216`, fit=cover),
rewrites *only* placements (cover and texts survive), places the first
`page_count` photos in R2 order, and returns surplus photo ids as
`unplaced_photo_ids` — surfaced, never silently dropped (R3). It participates
in the same If-Match concurrency scheme as every other layout mutation.

**A25 — Both colour paths exist (founder decision, 5 Aug 2026).** RGB is the
canonical, byte-deterministic artifact; `RENDER_COLOR_MODE=cmyk` converts it
via Ghostscript (+ optional `ICC_PROFILE_PATH`) at the boundary. Determinism
guarantees apply to the RGB artifact only — Ghostscript stamps timestamps.

**A26 — Spine widths are still PLACEHOLDERS.** The founder confirmed the page
tiers (16/32/48/96) but not the spine mm values; `SPINE_MM_*` in config keeps
the spec's placeholder numbers. Do not send any cover to production print
until the printer's real values replace them (they gate Milestone 10).

**A27 — All user-selected font names render as bundled DejaVu Sans** (repo-
pinned, full Latin+Cyrillic). Brand fonts (e.g. Inter) can be added to
`app/render/fonts/` later; the layout schema already carries the font name.

**A28 — Page rasters enter the PDF as JPEG files by path** (quality 95).
ReportLab's DCT passthrough keeps peak RSS at ~62MB for a 96-page book,
versus ~1GB via `drawImage(ImageReader)` which decodes and retains raw RGB —
the memory test in Part 9.3 exists precisely to keep this from regressing.
Text stays vector (never rasterised). Crop marks are omitted until the
printer asks for them.

**A29 — Render preflight refuses incomplete books**: wrong page count, any
page without a placement, or a placement referencing an unavailable photo
raises before a single page is composed. Blank pages are a guaranteed refund;
better to fail loudly in the worker than to print one.

**A30 — Preview details.** Per-page watermarked JPEGs at 72 DPI under
`books/{id}/preview/` (a namespace the print pipeline never reads). Unlike the
print render, preview has NO preflight: empty pages render as watermarked
blanks so the user sees exactly what would print. Staleness is tracked by
comparing the layout version the preview was rendered from with the current
one; text is approximated in raster (the print PDF keeps vector text). The
checkout confirmation gate (M8) must require status=ready AND stale=false.
