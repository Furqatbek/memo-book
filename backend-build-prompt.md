# BACKEND BUILD PROMPT — Photo Book Platform

**Version:** 1.0 — 5 August 2026
**Stack:** Python
**Intended use:** paste this entire document into an AI coding agent (Claude Code, Cursor, etc.) as the build specification.

> **Reading key.** Blocks marked **▶ FOUNDER NOTE** are commentary for you, not instructions for the AI. Everything else is the spec. You can leave the founder notes in — they give the coding agent useful rationale — but do not treat them as requirements.

---

# PART 0 — HOW TO USE THIS DOCUMENT

Do not paste this and say "build it." That produces 8,000 lines of unreviewable code.

Build in the milestone order in **Part 10**. For each milestone, paste Parts 1–3 (context, domain, rules) plus that milestone's section, and say:

> Implement Milestone N only. Write the tests described for this milestone first, then the implementation. Do not implement future milestones. Stop and list your assumptions before writing code.

**Before Milestone 6, you must ask your printer two questions.** The answers change the code:

1. **Do you accept RGB PDF, or require CMYK with your ICC profile?** If RGB, you skip colour conversion entirely — a week of work removed.
2. **What is the spine width formula for each page count?** Hardcover spine depends on paper thickness and board. You cannot generate a cover file without this number.

---

# PART 1 — PROJECT CONTEXT

## What the product is

A self-serve web platform where a user builds their own photo book, pays, and receives it printed and delivered. The user does all design work. We provide the editor, the printing, and the delivery.

This document specifies **the backend only**. The frontend editor is a separate concern; the backend exposes an API it consumes.

## Product constraints that drive the architecture

| Constraint | Consequence for backend |
|---|---|
| Book format is **A5, 148 × 210 mm**, hardcover, lay-flat | Fixed page geometry; all layout stored in millimetres |
| Page tiers: **16, 32, 48, 96** | Enum, not free integer. Validation gate. |
| **1 photo = 1 page** (MVP rule) | Placement model is trivial; keep the seam open for multi-photo pages |
| **30-day** draft retention | Expiry job, reminder emails |
| **No user accounts** in MVP | Anonymous sessions via signed book tokens |
| Payment in **Uzbek so'm** via local acquirers | UZS integer minor units; webhook-driven; idempotency is critical |
| **PDF generated after payment**, never before | Render job triggered by payment webhook only |
| Notification to **Telegram** with a storage **link**, never the file | Telegram bot upload cap is ~50MB; a 96-page book exceeds it |
| **No AI enhancement in MVP** | Build the seam, leave it unimplemented |
| Autosave on every user action | High write volume — see layout storage decision in Part 3 |

## Non-goals for MVP

Do not build: user accounts, password auth, admin dashboard UI, multi-photo pages, AI image enhancement, coupon/discount engine, multi-currency, internationalisation of the API, analytics pipeline. Leave clean seams for all of them.

---

# PART 2 — TECHNOLOGY

Use these unless you have a specific reason not to. State the reason if you deviate.

| Layer | Choice | Why |
|---|---|---|
| API | **FastAPI** | async, automatic OpenAPI, Pydantic validation is a real correctness win here |
| Validation | **Pydantic v2** | request/response models, strict mode |
| DB | **PostgreSQL 16** | JSONB for layout documents, transactional integrity for orders |
| ORM | **SQLAlchemy 2.0** (async) + **Alembic** | migrations are non-optional from day one |
| Queue | **Redis** + **RQ** | RQ is simpler than Celery and sufficient. Use Celery only if you need scheduling complexity later. |
| Object storage | **S3-compatible** (MinIO locally, any provider in prod) | never store binaries in Postgres |
| Images | **Pillow** + **pillow-heif** | HEIC support is critical path |
| PDF | **ReportLab** | direct control over placement, CMYK support, no browser dependency |
| Colour | **Ghostscript** (only if printer requires CMYK) | ICC-based conversion |
| Tests | **pytest**, **pytest-asyncio**, **hypothesis**, **testcontainers** | |
| HTTP client | **httpx** | async, used for Telegram + acquirer calls |
| Config | **pydantic-settings** | env-var driven, no config files in repo |
| Logging | **structlog**, JSON output | |

**Do not use headless Chrome to render PDFs.** It is tempting because you can reuse the editor's CSS, but it outputs RGB at screen resolution, has no reliable CMYK path, and adds a fragile 400MB dependency. Composite images directly.

---

# PART 3 — DOMAIN MODEL

## Print geometry constants

Define these once, in a single module. Every other module imports them.

```python
DPI = 300
MM_PER_INCH = 25.4
PX_PER_MM = DPI / MM_PER_INCH          # 11.8110236...

TRIM_W_MM = 148.0                       # A5
TRIM_H_MM = 210.0
BLEED_MM = 3.0

CANVAS_W_MM = TRIM_W_MM + 2 * BLEED_MM  # 154.0
CANVAS_H_MM = TRIM_H_MM + 2 * BLEED_MM  # 216.0

CANVAS_W_PX = 1819                      # round(154 * 11.811)
CANVAS_H_PX = 2551                      # round(216 * 11.811)

SAFE_MARGIN_MM = 5.0                    # text must stay this far inside TRIM
```

Rules derived from these:

- **All stored coordinates are millimetres**, origin at the top-left of the **trim** box (not the bleed box). This keeps the frontend simple and makes the data readable by humans.
- A photo intended to be full-bleed must be placed at `(-3, -3)` with size `154 × 216`. The frontend does this; the backend validates it is within the canvas.
- **Text boxes must be clamped** to the safe area: `x >= 5`, `y >= 5`, `x + w <= 143`, `y + h <= 205`. Clamp server-side on save. Do not reject — silently clamp, and return the clamped value so the editor can reflect it.

> **▶ FOUNDER NOTE.** Trimming has physical tolerance of 1–2mm. Text at 5mm is safe on every copy. Text at 2mm gets sliced on some copies and not others, which is worse than always being wrong, because you won't reproduce it in testing.

## Low-resolution thresholds

```python
def resolution_status(px_w: int, px_h: int, target_mm_w: float, target_mm_h: float) -> str:
    """Return 'ok' | 'warn' | 'block' for a photo placed at a given physical size."""
```

Compute effective DPI at the placed size. Thresholds:

| Effective DPI at placed size | Status | Behaviour |
|---|---|---|
| >= 200 | `ok` | no badge |
| 100–199 | `warn` | yellow badge in editor; allowed |
| < 100 | `block` | cannot be placed at that size; user must shrink it or choose another photo |

Absolute floors regardless of placed size: a source image narrower than **800px** may never fill a full page.

> **▶ FOUNDER NOTE.** This replaces the AI-enhancement feature for MVP. It is an `if` statement, not a sprint, and it prevents the single most expensive failure — printing a visibly blurry book and eating the reprint plus the review.

## Entities

```
Book
  id                UUID pk
  edit_token        str, indexed, unique   # anonymous ownership
  page_count        int, one of {16,32,48,96}
  status            enum: draft | locked | ordered | expired
  layout            JSONB                  # see below
  layout_version    int                    # optimistic concurrency
  email             str, nullable          # optional, for recovery
  reminder_3d_sent  bool
  reminder_14d_sent bool
  created_at        tz-aware
  updated_at        tz-aware
  expires_at        tz-aware               # created_at + 30 days

Photo
  id                UUID pk
  book_id           FK -> Book
  original_key      str        # storage key, immutable, never overwritten
  display_key       str        # JPEG, max 2000px long edge, for editor
  thumb_key         str        # 400px
  orig_width        int
  orig_height       int
  mime_original     str
  bytes_original    int
  taken_at          tz-aware, nullable     # from EXIF DateTimeOriginal
  exif_orientation  int, default 1
  uploaded_at       tz-aware
  sha256            str, indexed           # dedupe within a book

Order
  id                UUID pk
  book_id           FK -> Book, unique     # one order per book
  human_ref         str, unique            # short code shown to user, e.g. "UB-7K3M2"
  customer_name     str
  customer_phone    str
  customer_address  text
  customer_email    str, nullable
  amount_minor      bigint                 # UZS in minor units
  currency          str, default 'UZS'
  status            enum (see state machine)
  provider          enum: payme | click | uzum
  provider_txn_id   str, nullable, indexed
  created_at, paid_at, rendered_at, shipped_at

PdfArtifact
  id                UUID pk
  order_id          FK -> Order
  kind              enum: interior | cover
  storage_key       str
  sha256            str
  page_count        int
  bytes             int
  render_ms         int
  created_at

PaymentEvent            # append-only audit + idempotency
  id                UUID pk
  provider          str
  provider_event_id str
  order_id          FK, nullable
  method            str            # e.g. CreateTransaction / Prepare
  raw_payload       JSONB
  received_at
  UNIQUE (provider, provider_event_id, method)

OutboxMessage           # transactional outbox for Telegram/email
  id                UUID pk
  topic             str
  payload           JSONB
  status            enum: pending | sent | failed
  attempts          int
  next_attempt_at
  last_error        text
```

## Layout storage: JSONB document, not normalised rows

Store the entire page layout as one JSONB column on `Book`, versioned with an integer.

```json
{
  "version": 1,
  "cover": {
    "photo_id": "…", "title": "Italy 2026", "subtitle": "June",
    "title_font": "Inter", "title_size_pt": 28
  },
  "pages": [
    {
      "index": 0,
      "placement": {
        "photo_id": "…",
        "x_mm": -3, "y_mm": -3, "w_mm": 154, "h_mm": 216,
        "rotation": 0, "fit": "cover"
      },
      "texts": [
        { "id": "t1", "x_mm": 12, "y_mm": 180, "w_mm": 124, "h_mm": 18,
          "content": "Amalfi coast", "font": "Inter", "size_pt": 11,
          "align": "left", "color": "#1a1a1a" }
      ]
    }
  ]
}
```

**Why a document and not tables.** Autosave fires on every user action. A 96-page book normalised across `pages`, `placements` and `text_boxes` means a single drag produces a multi-table write and every load is a multi-join. The layout is *always* read and written as a whole, is never queried by its internals, and belongs to exactly one book. That is the textbook case for a document.

**Photos stay as rows** — they are assets with independent lifecycles, need garbage collection, dedupe by hash, and per-photo queries.

## Optimistic concurrency

`PATCH /books/{id}/layout` requires an `If-Match: <layout_version>` header. On mismatch return **409** with the current layout so the client can reconcile. This is what stops two open tabs from silently overwriting each other.

## Order state machine

```
draft_order
   │ checkout submitted, book locked
   ▼
pending_payment ──(provider cancel / timeout)──▶ cancelled
   │ payment webhook confirms
   ▼
paid
   │ render job enqueued
   ▼
rendering ──(render fails 3×)──▶ render_failed  ⚠ alert operator
   │
   ▼
rendered   ──▶ sent_to_production ──▶ shipped ──▶ delivered
                                          │
                                          └──▶ refunded
```

**Legal transitions only.** Implement as an explicit map and raise on illegal transitions; do not let arbitrary code assign `order.status`. Every transition writes a row to an `order_events` audit table.

**`paid` is the point of no return.** The book becomes immutable at `locked`; all layout mutation endpoints must return **423 Locked** thereafter.

---

# PART 4 — BUSINESS RULES (implement exactly)

### R1 — Tier gating
A user may only select page tier `N` if they have uploaded `>= N` photos, **or** they select the tier first and are blocked at checkout until they reach `N`. Enforce at checkout regardless.

**Never allow checkout with fewer photos than pages.** Blank printed pages are a guaranteed refund. Return a structured error naming the shortfall and the largest tier they currently qualify for.

### R2 — Auto-place ordering
Sort by `taken_at` ascending. Photos with null `taken_at` go **after** all dated photos, in `uploaded_at` order. Never random.

> **▶ FOUNDER NOTE.** This is the single most important rule in the product. A memory book is a story in sequence. Random order destroys the reason the thing exists and forces every user to manually reorder 48 pages.

### R3 — Surplus photos
If photo count exceeds page count, the API returns the next larger tier as an upsell suggestion in the checkout-eligibility response. If the user declines, they choose which photos to include; the backend never silently drops.

### R4 — EXIF orientation
Apply EXIF orientation on ingest by physically rotating the derived JPEG and resetting orientation to 1. Store `orig_width`/`orig_height` **post-rotation**. Nothing downstream should ever think about orientation again.

### R5 — EXIF preservation through HEIC conversion
`taken_at` must be extracted **before** any conversion and persisted to the DB column. Do not rely on EXIF surviving in the derived file.

> **▶ FOUNDER NOTE.** This is a silent killer. Many conversion paths strip EXIF. If that happens, `taken_at` is null for every iPhone photo, R2 falls back to upload order, and every book ships shuffled — with no error anywhere. There is an explicit test for this in Part 9.

### R6 — Draft expiry
`expires_at = created_at + 30 days`, extended to `now + 30 days` on every layout mutation. A nightly job marks expired drafts and deletes their storage objects. **Books in `locked` or `ordered` status are never expired.**

### R7 — Reminders
If `email` is present and the book is still `draft`: send a reminder at day 3 and at day 14 after last modification. Idempotent via the boolean flags.

### R8 — Rendering trigger
The render job is enqueued **only** by a payment transition into `paid`. Never on checkout submission. Never from a user-facing endpoint.

### R9 — Notification payload
The Telegram message contains the human reference, customer name and phone, page count, amount, and **time-limited signed download URLs** for the interior and cover PDFs. **Never the file itself.**

### R10 — Idempotency
Every payment webhook is idempotent on `(provider, provider_event_id, method)`. A duplicate returns the same response as the original without re-executing side effects. Assume every acquirer will call you twice.

---

# PART 5 — API SURFACE

All responses use a consistent error envelope:

```json
{ "error": { "code": "PHOTOS_INSUFFICIENT", "message": "…",
             "details": { "have": 10, "need": 16 } } }
```

Error codes are a closed enum in a shared module. The frontend switches on `code`, never on `message`.

### Books
```
POST   /api/v1/books                    {page_count} -> {book_id, edit_token, layout}
GET    /api/v1/books/{id}               (auth: edit_token) -> book + photos + layout
PATCH  /api/v1/books/{id}/layout        If-Match: version -> new version | 409
PATCH  /api/v1/books/{id}/page-count    {page_count} -> re-flows layout, warns on truncation
PATCH  /api/v1/books/{id}/email         {email}
POST   /api/v1/books/{id}/auto-place    -> layout with photos placed per R2
GET    /api/v1/books/{id}/checkout-eligibility
       -> {eligible, photo_count, page_count, issues[], suggested_tier}
```

### Photos
```
POST   /api/v1/books/{id}/photos/upload-url   {filename, mime, bytes}
       -> {upload_url, photo_id, storage_key}      # presigned PUT, direct to S3
POST   /api/v1/books/{id}/photos/{pid}/complete
       -> triggers ingest job -> {status: "processing"}
GET    /api/v1/books/{id}/photos              -> list with status + resolution_status
DELETE /api/v1/books/{id}/photos/{pid}
```

**Upload directly to object storage with presigned URLs.** Do not proxy image bytes through the API. A user uploading 96 photos at 4MB each is 384MB; routing that through your app server wastes memory, blocks workers, and will be your first outage.

### Preview
```
POST   /api/v1/books/{id}/preview       -> enqueues low-res preview render
GET    /api/v1/books/{id}/preview       -> {status, page_urls[]}
```

Preview renders at **72 DPI, RGB, watermarked**. It exists to satisfy the "no going back after payment" confirmation. It must never be reused as the print file.

### Checkout & payment
```
POST   /api/v1/books/{id}/checkout
       {name, phone, address, email?, confirmed_preview: true}
       -> locks book, creates Order(pending_payment), returns payment init data
POST   /api/v1/payments/{provider}/webhook     # provider-specific shape
GET    /api/v1/orders/{human_ref}              # public status lookup by ref + phone
```

`confirmed_preview` must be `true` or checkout is rejected. Record the timestamp of confirmation on the order — this is your defence against "I didn't know I couldn't edit it."

### Ops
```
GET /health     # process is alive — no dependency checks
GET /ready      # DB + Redis + storage reachable
GET /metrics    # Prometheus
```

---

# PART 6 — IMAGE INGEST PIPELINE

Runs as a background job after `photos/{pid}/complete`.

```
1. Fetch original from storage
2. Validate:
     - real image (Pillow verify), not just a trusted extension
     - dimensions <= 15000px per side          [decompression-bomb guard]
     - decoded pixel count <= 80_000_000
     - bytes <= 25MB
3. Extract EXIF -> taken_at, orientation        [BEFORE any conversion — R5]
4. Convert HEIC/HEIF -> JPEG                    [pillow_heif.register_heif_opener()]
5. Apply orientation physically, reset to 1     [R4]
6. Derive:
     display_key : longest edge 2000px, JPEG q85, sRGB
     thumb_key   : longest edge 400px,  JPEG q80
7. Compute sha256 of original; if a photo with the same hash exists
   in this book, mark as duplicate and surface it to the user
8. Persist Photo row; original is never modified or deleted
9. Emit photo.ingested
```

**Guard against decompression bombs before decoding.** `Image.open()` is lazy; read `.size` from the header and reject oversized images before `.load()`. Set `Image.MAX_IMAGE_PIXELS` explicitly.

**Strip all metadata from derived files** (EXIF often contains GPS coordinates of the user's home). Keep it only on the original, which is never publicly served.

---

# PART 7 — PDF RENDER PIPELINE

Runs as a background job triggered by R8.

```
1. Load Order, Book, layout, all Photos
2. Assert order.status == 'paid'; assert page count matches tier
3. For each page, sequentially:
     a. Create blank canvas CANVAS_W_PX x CANVAS_H_PX
     b. Open the ORIGINAL photo file (never display_key)
     c. Resize to the placed size in px, honouring `fit`
     d. Composite at the placement offset (+bleed origin shift)
     e. Draw text boxes at 300dpi, clamped to safe area
     f. Write the page into the PDF
     g. Explicitly free the page image        [memory — see below]
4. Write crop marks if the printer requires them
5. Convert to CMYK via Ghostscript + printer ICC   [ONLY if required]
6. Compute sha256, upload, create PdfArtifact
7. Render cover as a separate artifact
8. Transition order -> rendered
9. Enqueue notification via outbox
```

## Memory is the constraint, not CPU

One A5 page at 300dpi RGB is `1819 × 2551 × 3 bytes ≈ 13.9 MB` decoded. A 96-page book held in memory simultaneously is **~1.3 GB**, before counting the source images being resized, which are often larger.

**Therefore: process strictly one page at a time, write it into the PDF, and free it.** Never build a list of page images. Never `Image.open()` all photos up front.

Set the render worker's concurrency to 1–2 per container and give it a hard memory limit so a runaway render is killed rather than taking down the host.

## Cover is a separate artifact

A hardcover wrap is one wide sheet: `back + spine + front + wrap-around margin`. **Spine width is a function of page count and paper thickness and must come from the printer.** Model it as a lookup table in config:

```python
SPINE_MM = {16: 4.0, 32: 6.0, 48: 8.0, 96: 14.0}   # PLACEHOLDER — get real values
```

Do not guess these. A wrong spine width means the cover art wraps onto the wrong face and the entire print run is wasted.

## Determinism

Given the same book and photos, the render must produce a byte-identical PDF. That means: pin font files in the repo (do not use system fonts), set a fixed PDF creation date, and disable any random ID generation in ReportLab. Determinism is what makes the golden-file tests in Part 9 possible.

---

# PART 8 — PAYMENTS & NOTIFICATIONS

## Acquirer integration

Uzbek acquirers (Payme, Click, Uzum) each expose their own merchant protocol. Payme uses a JSON-RPC style Merchant API with methods such as `CheckPerformTransaction`, `CreateTransaction`, `PerformTransaction`, `CancelTransaction`, `CheckTransaction`; Click uses a two-step `Prepare` / `Complete` callback with a signature hash. **Verify the exact method names, signature algorithm, and amount units against each provider's current documentation before implementing — these protocols change and the details matter.**

Design for this regardless of provider:

```python
class PaymentProvider(Protocol):
    def verify_webhook(self, headers, body) -> bool: ...
    def parse_event(self, body) -> PaymentEvent: ...
    def build_checkout_payload(self, order) -> dict: ...
```

**Amounts.** Store `amount_minor` as an integer in the currency's minor unit and confirm what each provider expects (Payme, for example, works in tiyin — 1 sum = 100 tiyin). **Never use floats for money anywhere.** Convert at the provider boundary only.

**Verify the signature before parsing the body.** Reject unsigned or mis-signed callbacks with the provider's expected error shape, not a generic 400.

**Never trust the amount in the callback.** Compare it against the stored `Order.amount_minor` and reject mismatches. This is the standard payment-tampering vector.

## Transactional outbox for notifications

Do not call the Telegram API inside the request or inside the payment transaction. Write an `OutboxMessage` in the **same DB transaction** as the state change, and let a separate worker deliver it with exponential backoff.

Without this, a Telegram outage rolls back a successful payment, or a payment succeeds and the notification is silently lost. The outbox makes delivery at-least-once and independently retryable.

**Telegram sends a link, never a file** (R9). Generate a signed URL with a 7-day expiry.

---

# PART 9 — TEST STRATEGY

Tests are part of the deliverable, not an afterthought. Target ~85% coverage on domain logic; do not chase coverage on framework glue.

## 9.1 Unit tests — pure functions, no I/O

**Geometry**
- `mm_to_px` round-trips within 0.5px across 0–300mm
- Full-bleed placement `(-3,-3,154,216)` maps exactly to `(0,0,1819,2551)`
- Text clamping: a box at `x=1` clamps to `x=5`; at `x=140,w=20` clamps so `x+w<=143`
- A placement outside the canvas is rejected

**Property tests (hypothesis)**
- For any valid placement, the rendered rect is fully inside the canvas
- For any text box, the clamped result is inside the safe area
- `mm_to_px(px_to_mm(n)) == n` for all integers 0–3000

**Auto-place ordering (R2)** — this is the highest-value unit test in the suite
- Photos with `taken_at` sort ascending
- Null-`taken_at` photos come last, ordered by `uploaded_at`
- Mixed set: dated photos first in date order, then undated in upload order
- Identical timestamps break ties by `uploaded_at`, deterministically
- **Explicit assertion that output is never random**: run auto-place twice on the same input, assert identical output

**Resolution classification**
- 4000px wide on a full A5 page → `ok`
- 1000px wide on a full page → `warn`
- 600px wide on a full page → `block`
- 600px wide on a 40mm-wide placement → `ok` (small placement, high effective DPI)
- Boundary values at exactly 200 and 100 effective DPI

**Tier gating (R1)**
- 16 photos + tier 16 → eligible
- 10 photos + tier 16 → not eligible, `suggested_tier` is null, error names the shortfall
- 40 photos + tier 32 → eligible with surplus, `suggested_tier` = 48
- 200 photos + tier 96 → eligible with surplus, no larger tier suggested

**Order state machine**
- Every legal transition succeeds
- A representative set of illegal transitions raises (`draft → rendered`, `paid → pending_payment`, `delivered → paid`)
- Any transition into `paid` enqueues exactly one render job
- Transition into `locked` makes layout endpoints return 423

**Money**
- No float appears in any monetary path (assert types)
- Minor-unit conversion round-trips
- Amount mismatch between callback and order is rejected

## 9.2 Integration tests — real Postgres, real Redis, real MinIO via testcontainers

**Image ingest**
- JPEG upload → Photo row with correct dimensions
- PNG with alpha → flattened correctly
- **HEIC upload → converts to JPEG AND `taken_at` is populated** ← *the R5 regression test; commit a real iPhone HEIC fixture to the repo*
- EXIF orientation 6 (rotated) → derived JPEG is physically rotated, `orientation` stored as 1, `orig_width`/`orig_height` reflect the rotation
- Derived files contain **no** EXIF/GPS
- A 20000×20000 image is rejected before decode
- A `.jpg` file containing non-image bytes is rejected
- Same file uploaded twice into one book → flagged as duplicate

**Layout concurrency**
- Two `PATCH` calls with the same `If-Match` → second returns 409 with current layout
- Sequential correct-version patches both apply, version increments
- Patch on a `locked` book → 423

**Expiry (R6)**
- A draft older than 30 days is expired and its storage objects deleted
- A draft modified yesterday is untouched
- **An `ordered` book older than 30 days is NOT expired and its photos are NOT deleted** ← the dangerous case
- Expiry is idempotent when run twice

**Payment idempotency (R10)**
- The same webhook delivered twice → one state transition, one render job, identical response both times
- Out-of-order delivery (confirm arrives before create) is handled or safely rejected
- Invalid signature → rejected, no state change
- Amount mismatch → rejected, no state change
- Callback for an unknown order → provider-appropriate error, no crash

**Outbox**
- Committed in the same transaction as the state change
- Telegram failure → message stays `pending`, retried with backoff, never lost
- Delivery is at-least-once and the consumer tolerates duplicates

## 9.3 Render tests

**Correctness**
- 16-page book → PDF with exactly 16 pages
- Every page measures 154 × 216 mm ± 0.1mm
- Rendered PDF references original files, not `display_key` (assert by resolution: rasterise a page and confirm it exceeds `display_key`'s pixel dimensions)
- Text renders inside the safe area
- Cover artifact has the correct total width for its spine value

**Golden-file / visual regression**
- Commit a fixture book (fixed photos, fixed layout). Render it, rasterise each page at low DPI, compare against committed reference images with a perceptual diff and a small tolerance.
- Assert byte-identical PDF output across two runs (determinism)
- **When a golden test fails, look at the image before updating the reference.** These tests exist to catch silent layout drift, which is invisible in unit tests.

**Resource limits**
- A 96-page render completes under a defined time budget
- **Peak RSS during a 96-page render stays under 512MB** ← proves the one-page-at-a-time discipline; this test is the reason that discipline survives future refactoring
- A render that exceeds the limit is killed and the order lands in `render_failed`, not a zombie state

**Failure handling**
- A missing source photo → job fails cleanly, order → `render_failed`, alert emitted
- A corrupt photo → same
- Retry after a transient failure produces a valid PDF
- Render is idempotent: running it twice does not create two artifacts

## 9.4 Smoke tests — run against every deployed environment, under 30 seconds

```
1. GET /health returns 200
2. GET /ready returns 200 with all dependencies green
3. POST /books creates a book and returns a token
4. Presigned upload URL is issued and is actually writable
5. A single-page render completes end to end
6. Telegram credentials are valid (getMe), without sending a message
7. Alembic head matches the DB's current revision
```

If any smoke test fails after a deploy, roll back automatically.

## 9.5 End-to-end test — the full journey, one test, run in CI

```
1.  Create book, tier 16
2.  Upload 16 photos (mixed JPEG + HEIC + one rotated EXIF)
3.  Wait for ingest to complete
4.  Auto-place; assert chronological order
5.  Add a text box near the page edge; assert it was clamped
6.  Check eligibility → eligible
7.  Request preview; assert 16 watermarked pages
8.  Checkout WITHOUT confirmed_preview → rejected
9.  Checkout WITH confirmed_preview → book locked, order pending_payment
10. Attempt layout patch → 423
11. Send payment webhook → order paid, render enqueued
12. Send the SAME webhook again → no duplicate effects
13. Wait for render → PDF artifact exists, 16 pages, correct dimensions
14. Assert outbox message created; assert the Telegram payload contains a
    URL and does NOT contain file bytes
15. Public status lookup by human_ref + phone returns the correct state
```

Also run the **unhappy path** end to end: 10 photos into a 16-page tier, blocked at checkout with a correct structured error and no order created.

## 9.6 Load test (before launch, not during development)

- 50 concurrent uploads
- 10 concurrent 96-page renders — measure queue depth, memory, completion time
- Establish how many render workers one container can support. This number determines your infrastructure cost and your peak-season capacity.

---

# PART 10 — BUILD MILESTONES

Implement in this order. Each milestone must have passing tests before the next begins.

| # | Milestone | Contents |
|---|---|---|
| 1 | **Skeleton** | FastAPI app, config, structlog, `/health`, `/ready`, Docker Compose (Postgres + Redis + MinIO), Alembic initialised, CI running pytest |
| 2 | **Domain core** | Geometry constants, mm/px conversion, clamping, resolution classification, auto-place ordering, tier gating, state machine. **Pure Python, zero I/O, fully unit-tested.** Do not touch the DB in this milestone. |
| 3 | **Books & layout** | Models, migrations, CRUD, JSONB layout, optimistic concurrency, edit tokens |
| 4 | **Photo ingest** | Presigned uploads, ingest worker, HEIC, EXIF, derivatives, validation, dedupe |
| 5 | **Auto-place & eligibility** | Wire domain core to real data; eligibility endpoint |
| 6 | **Render pipeline** | ReportLab interior render, memory discipline, golden tests. *Ask the printer the two questions first.* |
| 7 | **Preview** | Low-res watermarked render, reusing the pipeline at 72dpi |
| 8 | **Checkout & orders** | Locking, order creation, confirmation gate |
| 9 | **Payments** | Provider abstraction, one real provider, webhook idempotency, signature verification |
| 10 | **Cover render** | Spine table, wrap geometry |
| 11 | **Outbox & Telegram** | Transactional outbox, delivery worker, signed links |
| 12 | **Lifecycle jobs** | Expiry, storage GC, reminder emails |
| 13 | **Hardening** | Rate limiting, error envelope audit, load test, smoke suite in CD |

> **▶ FOUNDER NOTE.** Milestone 2 is the one to be strict about. It is pure functions with no database, no network, and no framework — which means it can be tested exhaustively in milliseconds and is where every rule that actually defines your product lives. If auto-place ordering, tier gating and geometry are correct and locked down here, the rest of the system is plumbing. Most projects skip this separation, bury these rules inside endpoint handlers, and can never test them properly afterwards.

---

# PART 11 — OPERATIONAL & SECURITY REQUIREMENTS

**Security**
- Rate limit by IP: book creation, upload-URL issuance, webhook endpoints
- `edit_token` is a 32-byte URL-safe random value, compared in constant time
- Presigned URLs: 15 min for upload, 7 days for artifact download
- Storage bucket is private; no public read
- Validate `Content-Type` and magic bytes on upload, not the extension
- Set `Image.MAX_IMAGE_PIXELS` explicitly
- Customer phone and address are PII: restrict access, never log them, exclude from error reports
- Webhook signature verification before any parsing
- Log payment payloads with card-like fields redacted

**Observability**
- Structured JSON logs with a `request_id` propagated into background jobs
- Metrics: render duration, render peak memory, queue depth, ingest failure rate, webhook duplicate rate, orders by status
- Alert on: any `render_failed`, outbox messages older than 30 minutes, queue depth above threshold, `/ready` failing

**Data**
- Migrations are forward-only and reviewed; never edit an applied migration
- Nightly Postgres backup, tested restore
- Originals in storage are immutable and retained until the order ships
- Document a deletion path for customer data requests

---

# PART 12 — SEAMS FOR FUTURE FEATURES

Design these in now; implement none of them.

| Future feature | Seam to leave |
|---|---|
| AI photo enhancement | An `enhancement` field on Photo and a `PhotoProcessor` protocol in the ingest chain. The render reads whichever derivative is marked canonical. |
| Multi-photo pages | `page.placement` is singular today. Make it `page.placements` (a list) in the JSON schema from day one, with a validator enforcing `len == 1` in MVP. **Changing this later means migrating every stored layout.** |
| User accounts | Book ownership is already indirected through `edit_token`. Adding `user_id` is additive. |
| Other formats (A4, square) | Geometry constants are already centralised. Make them a `Format` object rather than module-level constants when the second format arrives. |
| Discounts | Price calculation lives in one pricing module with a single entry point. |
| Multiple print partners | Keep fulfilment behind a `ProductionTarget` protocol; Telegram is just the first implementation. |
| International payment | The `PaymentProvider` protocol already abstracts this. |

> **▶ FOUNDER NOTE.** The `placements` list is the one that will hurt if skipped. Every other item here is additive. That one requires rewriting stored JSON documents for every book in the database, and you will want multi-photo pages — it is the most requested feature in this category.

---

# PART 13 — DEFINITION OF DONE

The backend is done when:

1. All tests in Part 9 pass in CI
2. The end-to-end test passes against a real Docker Compose stack
3. A 96-page render completes within budget under 512MB peak RSS
4. A duplicated payment webhook provably causes no duplicate side effects
5. An expiry run does not touch photos belonging to ordered books
6. Smoke tests run automatically after deploy, with rollback on failure
7. A HEIC photo from a real iPhone produces a correctly ordered, correctly oriented page
8. `README.md` documents local setup in under ten commands
9. Every environment variable is documented in `.env.example`

---

*Spec v1.0, 5 August 2026. Provider protocol details (method names, signature algorithms, amount units) must be verified against each acquirer's current documentation before implementation.*
