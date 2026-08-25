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

**A31 — Checkout also requires complete pages**, not just the R1 photo count:
every page must hold a placement referencing a usable photo
(`PAGES_INCOMPLETE` otherwise). R1 alone would let a user with 16 uploaded
photos but 3 empty pages pay for a book the render preflight would then
refuse — better to block before money moves.

**A32 — Prices are config PLACEHOLDERS** (`PRICE_MINOR_*`, tiyin): 299k/399k/
499k/799k UZS for 16/32/48/96 pages. Set real prices before going live.
Pricing has one entry point (`services/pricing.py`) per the Part 12 seam.

**A33 — `cancelled → pending_payment` is legal**: re-checkout of the same
book reuses its single order row (the spec's unique `book_id` constraint)
with refreshed customer details and a full audit trail. The alternative —
a second order row — would violate the one-order-per-book invariant.

**A34 — The public status endpoint returns no PII** (no name, address or
email) and a wrong phone is byte-identical to an unknown reference.

**A35 — Real acquirer integration is deferred (founder decision, 5 Aug
2026).** The "dev" provider treats any webhook carrying the shared-secret
signature header as a completed payment. Everything around it is the
production machinery — signature-before-parse, amount verification against
the stored order, (provider, event_id, method) idempotency, paid-triggers-
render — so Payme/Click/Uzum later replace only `app/payments/dev.py`.
`DEV_PAYMENTS_ENABLED=false` removes the provider entirely.

**A36 — A pay event for an already-paid order is acknowledged, not
re-executed** (`duplicate: true` in the response), even under a new event id —
acquirers retry with fresh ids. A cancel after payment is an ILLEGAL_TRANSITION.
Amount-mismatch events are recorded in the audit table but change nothing.

**A37 — Render failure does not fail the webhook.** The payment is accepted
(200), the order lands in `render_failed` with the operator alert logged, and
`render_failed → rendering` remains the retry path. Spec's "render fails 3×"
retry counter is left to the RQ worker's retry policy at deploy time.

**A38 — Cover design and geometry (MVP).** The wrap sheet is
[wrap 16mm][back][spine][front][wrap 16mm]; the 16mm turn-in is a PLACEHOLDER
to confirm with the printer alongside the spine table. Front art fills the
front panel plus the right/top/bottom wrap so turned-in edges continue the
design; the back panel and spine stay white in MVP. Title/subtitle are vector
text centred on the front panel (white with a soft shadow over a photo, dark
on white otherwise). `rendered` now requires BOTH artifacts; one render
produces exactly one interior and one cover.

**A39 — Outbox delivery model.** `enqueue` only adds the row; the caller's
commit makes the state change and the message atomic. Delivery: exponential
backoff 30s·2^n capped at 1h, gives up (`failed`) after 8 attempts with the
error recorded. In eager mode a delivery pass runs right after fulfillment;
in production `python -m app.workers.outbox` polls every 10s. Presigned
artifact links are generated at DELIVERY time so retries carry fresh 7-day
URLs, not expired ones.

**A40 — The Telegram payload contains PII (name, phone) and is never
logged**; log events carry only the order reference and message id.
Credentials missing = delivery failure = retry, so messages queued before
the bot is configured are sent once it is.

**A41 — Email transport is a seam.** No SMTP/API provider is integrated;
`send_email` raises, so reminder deliveries retry through the outbox and end
in `failed` with "not configured" until credentials exist — nothing is lost.
Reminders flow through the outbox to inherit at-least-once + backoff, and the
sent-flags commit atomically with the outbox row (R7 idempotency).

**A42 — Expiry ordering.** The expired status commits BEFORE storage objects
are deleted: a crash between the two leaves a re-runnable cleanup, never a
live draft with missing photos. Photo/order rows are kept after expiry for
audit; only storage objects are removed.

**A43 — Rate limiting is in-process** (per-IP sliding window, per-endpoint
limits in config). Sufficient for a single-instance MVP; the dependency
surface stays identical when the backing store moves to Redis for horizontal
scaling. Tests disable it globally and re-enable it in dedicated tests.

**A44 — Smoke scope.** The deploy smoke covers health/ready, book creation,
a real presigned PUT + ingest, Telegram getMe and `alembic check`. The
spec's "single-page render end to end" is intentionally NOT smoked: rendering
triggers only via payment (R8), and a dev-payment smoke would create paid
orders in production. Render health is covered by CI's full pipeline tests
and the render_failed alerting path.

**A45 — The editor (`../editor`) is a static, no-build vanilla-JS app.** Same
stack as the marketing site: no framework, no bundler, ES modules straight to
the browser, deployable to GitHub Pages next to the site. The API base URL is
deploy-time config (`editor/config.js`), overridable per browser with
`?api=…` for staging. One JS payload serves all five languages (shared
`sb-lang` choice with the site).

**A46 — Editor MVP scope mirrors the backend MVP.** One placement per page
(full-page / with-margin presets + fill/fit toggle) matching the ≤1-placement
layout rule; free drag-and-resize of placements arrives with multi-photo
pages. Text boxes are draggable and clamp client-side to the same safe area
the server enforces. Autosave PATCHes the whole layout with `If-Match`; on
conflict the server document wins (single-user drafts make real conflicts
rare).

**A47 — The dev "simulate payment" button lives in the ORDER screen, not the
API.** It posts the same dev webhook an acquirer would, using a signature the
operator types (or `devPaymentSecret` in `config.js` for local dev only). No
secret ships in the deployed editor; with `DEV_PAYMENTS_ENABLED=false` the
button's webhook is refused like any other unsigned call.

**A48 — devserver CORS shim.** `scripts/devserver.py` strips the query string
from `OPTIONS` requests before they reach moto: real S3/MinIO never
authenticate CORS preflights, moto does (and 403s, since the presigned
signature is bound to PUT). Dev-only; production storage needs a bucket CORS
rule allowing `PUT` from the editor origin instead.

**A49 — Free-form editing and colours.** Pages and the cover carry
`bg_color` (and the cover `title_color`) — schema-validated `#rrggbb`,
defaulting to white so pre-existing layouts and the golden-raster test are
byte-identical. The renderer fills the page canvas, contain-letterboxing and
rotation gaps with the page colour; an explicit cover `title_color`
overrides the automatic white-over-photo/ink-over-plain choice. In the
editor, photos drag and corner-resize freely within the bleed canvas
(client-side clamps mirror `validate_placement`), text boxes drag by their
body and resize in width, and a double-click/double-tap creates a focused
text box at that point ("type anywhere"). The autosave engine only adopts
the server's clamped document between edits — never while a caret, colour
input or drag holds references into the layout tree.

**A50 — Font families are coverage-gated.** A font ships only if it covers
every script a customer can type: Latin, Russian Cyrillic, Uzbek Latin
(okina U+02BB), Uzbek Cyrillic extensions (қ ғ ҳ ў) and Karakalpak
(á ǵ ı ń ó ú) — enforced by a fontTools cmap test over every bundled TTF.
Six families pass and ship (DejaVu Sans/Serif/Mono, Inter, Montserrat,
Noto Serif); popular candidates that miss glyphs (Playfair, Lora, Caveat,
Comfortaa, PT Serif, Nunito, Rubik) are rejected rather than risking tofu
boxes in a printed book. "Inter" — the historical stored default — now
resolves to the real Inter family; the golden raster was regenerated and
visually inspected for that change. The editor serves the same fonts as
woff2 so the canvas, the watermarked preview, and the print PDF all show
identical glyphs.

**A51 — Text rotation.** Text boxes carry `rotation` (clockwise degrees
about the box centre, the CSS convention; ±360 range). The interior PDF
rotates the same vector text via a canvas transform — the unrotated path is
byte-identical to before, keeping existing renders and the golden raster
stable — and the 72dpi preview rasterises the box onto a transparent layer,
rotates, and composites at the centre. The safe-area clamp applies to the
unrotated box: a rotated box's corners may extend slightly past the safe
margin, accepted for MVP. In the editor, a ⟳ handle rotates (snapping
within 5° of the compass points) and a corner dot scales the font and box
together about the centre.

**A52 — Free cover title + touch gestures.** The cover title/subtitle block
carries an optional centre position (`title_x_mm`/`title_y_mm`, front-panel
trim mm) and `title_rotation`; when unset the renderer keeps the classic
fixed layout byte-identical, when set it translates/rotates the same vector
text about that centre. In the editor the block drags anywhere, rotates via
the ⟳ handle and scales via the corner dot, exactly like page text. Touch:
a two-finger pinch resizes photos (about their centre) and scales text /
the cover title, with the twist of the same gesture rotating text — built
on pointer events so single-finger drags stand down while a pinch is live.

**A53 — Split storage endpoints (internal vs public).** The backend talks
to object storage via `S3_ENDPOINT_URL` (in Docker: `http://minio:9000`
over the compose network) while browser-facing presigned URLs are signed
against `S3_PUBLIC_URL` (empty = same as the internal one, which keeps
bare local dev unchanged). This matters whenever the public address is not
reachable — or only slowly reachable — from inside the containers: with a
tunnel or a domain in front of MinIO, ingest/preview no longer hairpin
every photo through the internet, they read the object store directly.
Presigning is region/keys-based, not a network call, so signatures from
the public-URL client stay valid for the same bucket. The editor also
retries each storage PUT three times with backoff — tunnels and mobile
networks drop connections mid-upload, and one flaky request should not
red-flag the whole file.

**A54 — Card-transfer pilot payments.** Until a real acquirer is
integrated, the order page shows a configured card (`PAY_CARD_NUMBER` /
`PAY_CARD_HOLDER`, rendered as a bank card with a copy button) while the
order is `pending_payment`; the block is driven by the public status
payload and disappears the moment the order is paid. The operator matches
an incoming transfer with `scripts/confirm_payment.py --list` and confirms
with `scripts/confirm_payment.py REF`, which POSTs the signed dev-provider
webhook to the running API — signature, amount check, idempotency and the
render trigger are exactly the acquirer path, so swapping in Payme/Click
later changes nothing about fulfilment. Telegram credentials are wired
with `scripts/telegram_check.py` (getMe + test send; lists visible chat
ids when TELEGRAM_CHAT_ID is empty).

**A55 — Book occasion travels to the printer.** The editor's occasion
picker (love/travel/birthday/memory) is stored on the book
(`books.book_type`, nullable — older books have none) and rides the
rendered-order payload into the Telegram notification, alongside the
customer's delivery address and email. The message shows a human label
("✈️ Travel book"); an unset type simply omits the line.

**A56 — Operator cancellation in the trust-first pilot.** Because
auto-confirmed orders skip `pending_payment`, the state machine now allows
`cancelled` from paid/rendering/render_failed/rendered — i.e. any time
before `sent_to_production` — and an `ordered` book may return to `draft`.
The power belongs to the operator CLI (`order_status.py REF cancelled`,
which also unlocks the book for editing/re-ordering); the payment webhook
still refuses to cancel anything but a pending order, since money that
already moved is a refund, never a webhook cancel. Re-checkout after an
operator cancel auto-confirms again through the same deterministic
`auto-<order-id>` event.

**A57 — Stickers are vendored, never hotlinked.** The editor offers a
curated sticker catalog (~155 assets, 8 categories) that ships in the repo
and the image exactly like the render fonts — chosen over runtime sticker
APIs (GIPHY/Tenor), whose licenses forbid print-for-sale use and whose
rasters break at 300 dpi. Sources, all print-safe and pinned in
`scripts/vendor_stickers.py`: decorative packs from Noto Emoji SVGs
(Apache-2.0); country flags from the region-flags set inside the same
release (Wikipedia-sourced, Public Domain); country map silhouettes
GENERATED by us from Natural Earth 1:50m data (public domain) — 41 curated
countries, far-off overseas territories dropped so silhouettes read as
their country. Layouts store `StickerDoc {sticker_id, centre x/y_mm, w_mm,
rotation}` on pages and the cover (JSON — no migration); unknown ids fail
validation. Print embeds the 1024px PNGs (sharp beyond any allowed sticker
size); stacking is photo → stickers → text everywhere; cover stickers are
clipped to the front panel + right wrap. Stickers may hang off page edges
deliberately — the bleed clips them, scrapbook-style.

**A58 — The browser downscales before uploading.** Phone photos are 3-12MB
and uploading them untouched was by far the slowest part of making a book.
The editor now re-encodes each file to a 3500px long edge at JPEG q0.85
before it leaves the device. That bound is set by print, not by taste: a
landscape 4:3 photo cropped to a full-bleed portrait A5 page still yields
~1870x2625px against the 1819x2551px that 300dpi demands, so nothing the
customer sees in the preview degrades on paper. Files under 900KB are sent
untouched (re-encoding would only lose quality), and any decode failure —
HEIC outside Safari, an exotic profile — falls back to the original bytes:
a slower upload always beats a lost photo. Because a canvas re-encode drops
EXIF, the client parses DateTimeOriginal from the original file and sends
it with `complete`, where the server parses it with the same helper the
EXIF path uses; a real EXIF date inside the uploaded file still wins. EXIF
orientation is baked into the pixels, and the client verifies the browser
actually applied it by comparing the decoded size against the JPEG's SOF
frame — trusting `imageOrientation: 'from-image'` blindly would silently
print sideways photos on engines that ignore it.

**A59 — Page layouts.** `PageDoc.layout` names a slot grid from
`app/domain/layouts.py` (full, inset, two-h, two-v, three-v, four,
big-top); placements fill slots in order, so `placements[i]` is `slots[i]`
and the trailing slots are the empty ones — the document can never describe
a hole, at the cost of compacting when a middle photo is removed. The
renderer needed no change: it has looped over `placements` since day one,
which is exactly what the list seam was for. The editor mirror
(`editor/js/layouts.js`) is generated by `scripts/gen_layouts.py` and a test
fails if the two copies drift. In a grid the slot rectangle belongs to the
layout — dragging a photo swaps it with the slot under the pointer instead
of moving it freely, and corner/pinch resize is offered only on single-slot
pages. Auto-place fills every slot, so a 4-up page consumes four photos.

**A60 — Centre snapping and swatch colours.** Dragged elements latch to the
page centre within 9px and only release past 22px, with guide lines while
held — finding the exact centre by hand on a phone is otherwise luck. The
native colour input is replaced by a grid of large swatches (the OS colour
dialog is painful on phones); the native picker stays behind "Custom" for
an exact shade.

**A61 — Static assets declare their caching.** The editor is a no-build ES
module app, so index.html and the JS it imports are separate cached
resources. With no `Cache-Control` header browsers apply *heuristic*
caching and mobile browsers hold JS for hours — a freshly fetched
index.html then runs stale app.js/i18n.js, which looks exactly like broken
features: new buttons wired to nothing, labels rendering raw translation
keys (reported in production for the layout button). `WebAssets` therefore
serves markup/code with `no-cache` (kept, but revalidated — Starlette
answers unchanged files with an empty 304) and media with a one-week
max-age, since sticker/photo assets are numerous and effectively
immutable. Module URLs also carry a one-time `?v=` stamp to break browsers
out of caches poisoned before this rule existed; the header makes further
bumps unnecessary.

**A62 — The customer frames the crop.** A photo almost never shares its
slot's aspect ratio, so "cover" framing has to discard part of it — with
grid layouts that read as an arbitrary zoomed-in cut. `PlacementDoc`
therefore carries `zoom` (1.0–4.0, 1.0 = just covers the slot) and
`focus_x`/`focus_y` (0–1 across the overflow, 0.5 = centre). The defaults
are exactly a centred crop and the renderer arithmetic reduces to the
original expression at those values, so every book laid out before this
renders byte-identically. The editor positions the photo inside its frame
with the same arithmetic as `_fit_cover`, so the framing on screen is the
framing that prints: a ⠿ handle on the selected photo pans it, −/+ zoom,
pinch zooms inside a fixed grid slot, and "Fit" still shows the whole
photo letterboxed for people who want nothing cropped at all.

**A63 — The customer buys sheets, the system counts pages.** A sheet of
paper carries two printed sides with ordinary double-sided printing, so the
tier the customer picks (16/32/48/96 **sheets**) yields twice as many
designed pages — a 16-sheet book is 32 pages. `page_count` remains the
internal unit for the layout, renderer and PDF; only the picker and prices
speak sheets. `SIDES_PER_SHEET` carries the assumption: set it to 1 if the
printer uses photo-mount lay-flat binding, where sheets are printed on one
side and glued back-to-back (the backs are the glue surface and cannot hold
photos), and every tier returns to its original page count with no code
change. Prices are keyed by sheet tier so the .env names still match what
the customer chooses; books created before sheet-counting keep validating
and price by their own page count, and a book with the same number of
printed sides costs the same however it was created.

**A64 — Preview shows facing pages.** A bound book opens in spreads: page 1
stands alone on the right, then (2,3), (4,5)… and the final page alone on
the left. The preview groups the rendered pages that way so the customer
confirms the book as it will actually open, rather than as a flat list.
Editing is still page-by-page; photos spanning the gutter are not built yet.

**A65 — A photo may cross the fold.** Pages are rendered one at a time, so
a photo spanning a spread is stored on BOTH pages: the same rectangle,
shifted by exactly one trim width (148 mm), each page showing the half that
falls on it. Because one trim width is exactly 1748 px at 300 dpi, the two
printed halves butt together with nothing repeated or dropped — asserted by
rendering both pages and comparing their overlapping columns. Placement
validation therefore allows horizontal overhang (bounded by a spread width,
and required to touch the page) while still refusing vertical overhang,
since there is no facing page above. The two halves share a `spread_id` so
the editor treats them as one object: cropping, zooming or deleting one
updates the other, and choosing a grid layout ends the span. Pairing
follows the binding — page 1 stands alone on the right, then (2,3), (4,5)…
— and the editor shows the facing page beside the one being edited, as a
picture that can be tapped to move editing there.

**A66 — Gutter guide on the bound edge.** Every interior page is bound
along one edge — page 1 on its left, then alternating — and paper curves
into the spine there, so a face placed in that strip disappears into the
fold. The editor hatches the bleed plus a **5 mm gutter allowance**
(`GUTTER` in the editor) along each page's bound edge; in spread view the
two guides meet to form one strip down the fold. It is advisory only: the
guide never blocks a drag and nothing is clamped, because a background
photo is *meant* to run through the gutter. The 5 mm is a PLACEHOLDER
pending the printer's own figure (printer-questions.md, question 13).

**A67 — Enough photos means enough to fill the pages, not one each.** R1
was written when a page held exactly one photo. A grid page now holds up to
four and a photo across the fold fills two (A65), so counting photos
against pages both refuses complete books (16 spread photos genuinely fill
a 32-page book) and accepts incomplete ones (32 photos poured into four-up
pages leave 24 pages bare). The gate is therefore `empty_pages >
unplaced_photos` — every page with nothing on it needs a photo still spare
to put there — computed from the live layout by `layout_progress()` and
used by both checkout and `/checkout-eligibility`. A photo counts as used
wherever it appears, including on both halves of a spread and on the cover.
`/checkout-eligibility` stays a **tier** question: with nothing placed yet
its defaults reduce to the old `photo_count >= page_count` rule, so an
untouched book with enough photos still reads as eligible. Nagging about
unplaced photos belongs to the editor banner, and refusing a genuinely
blank page belongs to checkout's own `_require_complete_pages` — which is
unchanged and remains the hard gate.

**A68 — Print sharpness is a property of the placement, not the photo.**
The tray badge asks one question at upload time — "would this photo fill a
whole page?" — and that became the wrong question once a page could hold
four photos and a photo could be zoomed 4× across a spread. It over-warned
about a photo destined for a quarter-page slot (tempting the customer to
delete a perfectly good picture) and said nothing at all about zoom, which
is where the sharpness actually goes: cropping in at zoom Z prints 1/Z of
the photo across the same paper, so 4× zoom costs exactly what making the
placement four times wider costs. `resolution_status` therefore takes
`zoom` and `fit`, and the 800 px full-page floor divides by zoom too.
"contain" is exempt from that floor and measured on its better axis: it
letterboxes, so the photo prints smaller and is never asked to fill the
page. The editor recomputes per placement with the same thresholds (a test
fails if the two copies drift), badges the placement itself while the
customer can still zoom out or pick a smaller frame, and repeats the count
on the preview screen — the last moment before the preview becomes the
contract. It stays advisory: nothing blocks checkout on resolution, because
refusing someone's only photo of a moment is worse than printing it soft
with fair warning. The tray badge survives, reworded to "small photo",
since a genuinely small file is still worth knowing about on arrival.

**A69 — The editor lays photos out in percentages, never measured pixels.**
`applyCrop` used to read the live canvas width to size a photo inside its
frame. On a phone `renderCanvas` runs while the canvas is still narrower
than it ends up, so photos were laid out against a stale width and stopped
short of the page edge — on screen only, since the renderer fills the frame
regardless. A WYSIWYG editor showing a margin that will not print is the
one lie it must not tell. The cover fit is now expressed as ratios of the
frame (`cropRatios`: source aspect, frame aspect from the placement's own
mm, and zoom) and written as CSS percentages, which the browser resolves
against whatever the frame turns out to be. Nothing is measured, so nothing
can go stale, and it is resolution-independent for free. Pointer maths
still needs real pixels, so `cropOverflow` takes the element and measures it
at drag time, when the layout has settled.

**A70 — Cover templates are compositions, not designs-with-opinions.** A
customer who uploads one photo should get a finished cover without
designing anything, so the cover offers five named compositions — full
photo, framed, photo on top, title on top, square — behind the same
"Layout" button an inside page uses. A template writes *geometry only*: the
photo rectangle and the title's place and size. It is deliberately silent
about colour and content, so the occasion theme's cover colour survives,
trying all five costs nothing, and every field it writes stays draggable
afterwards. Switching templates is exactly reversible, which a test asserts
rather than a comment claiming it.

The registry (`app/domain/cover_templates.py`) is the single source of
truth and is copied into `editor/js/cover-templates.js` by
`scripts/gen_cover_templates.py`, with a drift test — the same arrangement
page layouts already use. `CoverDoc` stores the template *id* (so the
picker can show which is active) **and** the resolved rectangle (so the
book keeps its look even if a template is later redrawn), again mirroring
how `PageDoc` stores both a layout id and real placements. An unknown
template id falls back rather than rejecting: a cover naming a design we
have retired must still open, and its stored geometry is what renders
anyway.

Rectangles are front-panel TRIM mm, and one reaching a trim edge means
"bleed off that edge". Each surface then supplies its own overhang, because
they genuinely differ: 3mm of bleed in the editor and the preview, a 16mm
turn-in on the printed sheet — and never on the left of the printed sheet,
where the spine is rather than a turn-in, so art can't appear on the closed
book's back. The default full-panel rectangle therefore reproduces the
original hand-written "front panel plus the right wrap, full height" paste
exactly, and a cover saved before templates existed renders byte-identically
(asserted). The editor and the preview share the 3mm rule, so what the
customer confirms is what they framed; the printed sheet's outer edges are
cropped slightly differently, but those edges are wrapped around the board
and never seen.

The cover photo also gained `photo_zoom`/`photo_focus_*`, matching
placements, and the editor renders it through the same `placeRect`/
`applyCrop` path a page photo uses — so the print-sharpness warning (A68)
now covers the cover, where a small photo blown up is the most visible
defect of all.

Two rules had quietly been standing in for geometry. "Is the title over the
photo" was really "is there a photo at all", which was the same question
only while every photo filled the whole front; it is now an actual
containment test, so it also stays right when the customer drags the title
off the picture. And the automatic title ink was a flat dark grey, which
disappeared on the dark cover colours the occasion themes set; it is now
chosen by background luminance. Both live in one place and are used by the
print renderer, the preview renderer and the editor alike.

**A71 — Ready-made cover designs are content, not code.** Page layouts and
the built-in cover compositions (A70) ship with a release; a *design* is
artwork the founder uploads, names, reorders and retires from the server
with no deploy. So it lives in a table and in object storage, not in a
Python dict. The customer's flow gains a third question after occasion and
size: which ready-made cover — a gallery the **backend** filters by
occasion, so adding a design or changing which occasions it suits never
touches the frontend.

A design carries geometry as well as artwork, because a design is one whole
thing: this picture, with the customer's photo *here*, and the title
*there*. It reuses A70's front-panel-trim-mm rectangle, so the renderers,
the editor and the admin script all speak the same coordinates.

**Artwork covers the front panel plus its turn-in — 164×242 mm, 1937×2858 px
at 300 dpi — and not the whole wrap.** The back panel and spine print in the
design's own flat colour. That is the decision that lets ONE file serve all
four book sizes: the spine width changes with the tier, so a full-wrap image
would have to be redrawn four times per design, which is four times the work
for a solo founder and four chances to ship the wrong one. Wrap-around art
remains possible later as a per-tier variant; it is not built.

`book_types` is a comma-delimited string filtered in Python, not a JSON array
or a join table. There will be tens of designs, not thousands, and a plain
string stays readable in a psql session and in the admin command. Empty means
"suits every occasion" — the point of leaving it blank. A request with no
occasion at all applies no filter, because that is the browsing case and an
almost-empty shelf would be confusing.

Three failure modes are handled deliberately, because a cover renders **after
the customer has paid**:
- A cover naming a **retired** design still renders with its artwork. Retiring
  is a shop-window decision; it must not alter a book someone has confirmed.
- A design row or storage object that has **vanished** renders the cover on
  its background colour rather than raising. A missing decoration is not
  worth failing a paid order over.
- A **malformed** `design_id` — from a hand-edited document — is treated as
  no design. `CoverDoc.design_id` is therefore never validated against the
  catalogue.

The print artwork is never handed to the customer: the gallery serves a
thumbnail and a display-sized copy, and the renderer reads the full-resolution
file server-side. Design names are not translated (the founder types one
name); thumbnails carry the meaning, and the alternative is asking a solo
founder for five translations per design.

**A72 — The admin console, and the lock on it.** Managing the cover
catalogue over SSH does not scale past the first few designs, so the same
operations are a web console at `/admin`. One decision matters more than the
rest of the feature: **an empty `ADMIN_TOKEN` disables the admin API
entirely.** A deploy that forgets to set it fails closed — every admin route
answers 404 — rather than shipping an open door on a public domain. A test
asserts that for every route, and the route list in the test is the thing a
future route has to be added to.

Failures are 404, never 401: a wrong token, a missing token and a
switched-off admin are indistinguishable, so the console is not an oracle
for whether an admin API lives at this host. Comparison is constant-time and
attempts are rate-limited per IP.

That secrecy costs the console one thing, so it pays for it explicitly: a
token revoked mid-session is indistinguishable from "no such design". Every
handler therefore routes its failure through one helper, which on a 404 asks
`/admin/ping` whether the session is still good and, if it is not, says so
and signs out. Without that, a revoked operator would spend the afternoon
reading "not found" and concluding the catalogue had vanished.

The token is a single shared secret in `.env`, not accounts — there is one
operator, and a login system would be more code to get wrong than it would
protect. It rides in `X-Admin-Token` and is kept in localStorage, which is
readable by any script that gets into the page; the console renders no
user-supplied HTML, so that risk is bounded, and revoking is an `.env` edit
plus a restart. If a second operator ever needs access, this is the piece to
replace.

The console is **English only**, deliberately. The five-language rule exists
for people buying books; the audience here is the founder.

The reason it is worth a UI rather than a nicer CLI is the **preview**:
placing a photo window by typing `19,24,110,110` and discovering the result
at print time is precisely the loop this removes. The photo window and title
are dragged and resized over the real artwork, and the preview computes
framing, the safe margin and the automatic title ink exactly as the print
renderer does. Upload validation is shared code (`build_renditions`), not a
second implementation, so the console and the CLI cannot disagree about what
artwork is acceptable — the alternative is learning the difference from a
printed book.

The slug is editable while creating a design and locked afterwards. It names
the artwork in storage and is what `POST /cover-designs` upserts on, so a
typed-over slug would either create a second design or overwrite an unrelated
one — and `PATCH` does not carry it at all, meaning an editable field would
have accepted a new value, reported "Saved", and changed nothing. A field
that lies about what it did is worse than a field that is disabled, so it is
disabled, with a line of text saying why and pointing at the name instead.
The console applies the same rule to its own inputs generally: a control that
cannot take effect is greyed out, and a refused save names the field it
stumbled on rather than failing silently.

Uploads are `multipart/form-data` to the API rather than a presigned PUT.
Photos use presigned PUTs because customers upload dozens at a time from
phones; artwork is one file, occasionally, from a laptop, and routing it
through the API keeps validation and the storage layout server-side.

**A73 — The orders section runs the same machinery the scripts did.** The
daily job — see what came in, confirm the transfer, hand the printer the
files, move the order along — moves from three SSH scripts into the console.
What matters is that it is the *same* job, not a parallel one: every status
change goes through `apply_transition`, so the state machine and the
append-only audit trail apply exactly as they do to an acquirer's webhook,
and nothing assigns `order.status` directly.

Three properties were built in rather than left to the page:

* **The console never decides what an order may become.** `next_statuses`
  comes from `ORDER_TRANSITIONS` on the server, intersected with the moves a
  person should be driving. A page holding its own list of statuses would
  drift away from the machine and start offering steps that get refused.
* **`paid` is not an operator target.** Becoming paid locks the book and
  enqueues the render, so it has its own action rather than being reachable
  through the generic "set status" one. `_handle_pay` and the console's
  confirm now share `mark_paid`, so an acquirer callback and a human seeing a
  bank transfer produce identical consequences — including the render
  enqueued exactly once. Confirming twice is a no-op, not a second print run.
* **There is no delete.** Not for orders (the audit trail is the record of
  what happened to someone's money) and not for cover designs (books already
  using one must keep printing). Retiring is the only removal in the system.

Cancelling from the console goes through `cancel_order`, which also unlocks
the book — the operator's cancel is usually "they never paid", and stranding
the customer's book would be the wrong half of that.

The section shows customer names, phones and addresses, and hands out signed
links to the print PDFs. That is the job; it is also why the lock in A72 is
the load-bearing part of the feature. The public order page still refuses the
print files outside dev environments, and a test asserts that specifically.

Phone search compares digits on both sides. Numbers are stored as the
customer typed them ("+998 90 123-45-67") and the operator will type them a
different way, so both are reduced to digits in SQL. A normalised column
would be faster and is the right answer at a scale this pilot will not reach.

**A74 — The shop is shut until somebody says the prices are real.** The
founder's decision was to leave `PRICE_MINOR_*` at its placeholder numbers
for now. That is fine as a decision and dangerous as a state: a placeholder
is a perfectly valid integer, so no code downstream can tell "299,000
because that is the price" from "299,000 because the spec needed a number",
and the checkout path would charge either one just as happily. The gap is
real money — sheet-counting (A63) doubled what a tier delivers without
touching what it costs, so today's placeholders would sell a 32-page book at
the old 16-page price.

So the confirmation is a separate switch: `PRICES_CONFIRMED`, off by
default. While it is off, `POST /checkout` refuses with 503
`PRICES_NOT_CONFIRMED` before it looks anything up, and no order row, no
lock and no charge results — the customer's book is untouched and orderable
the moment the flag flips.

It is a second variable rather than "empty means unset" because a price of
zero and a price nobody has checked are different problems, and because the
question it answers is not about any one number: it is "has a human been
through the pricing". Nothing but a human can answer that, so nothing but an
explicit flag should encode it.

**Off by default is the whole design.** Forgetting to set it costs a deploy
and an obvious symptom — no orders, loudly, in a way the founder finds in
minutes. The other polarity costs the margin on every book sold until
somebody reconciles a bank statement. This is the same fail-closed reasoning
as `ADMIN_TOKEN` in A72, applied to the other direction of the money.

The price list still quotes the numbers, with `"confirmed": false` alongside.
Hiding them would leave the tier picker blank and teach the customer
nothing; quoting them silently would let someone build a whole book and
discover at the last step that nobody can sell it to them. The editor shows
the figures with a notice above them, in all five languages, and the 503 is
handled at checkout too in case the flag changes mid-session. Dev and the
test suite set the flag on, since the thing they are testing is checkout.

**A75 — A fresh VPS is reproducible from this repository, and that is
tested.** The founder's choice was to harden the deploy, and the first thing
that exercise found was a real hole: `ADMIN_TOKEN` appeared nowhere in
`.env.prod.example` and `bootstrap.sh` never generated one, so every fresh
deploy came up with the admin console answering 404 on every route. Nothing
was broken — A72's fail-closed rule was working exactly as written, on a
machine where nobody had been given the chance to set the token — and
nothing said so, because 404 is also what a wrong token returns. The console
would simply not have existed, silently.

That class of defect is invisible to the rest of the suite, because every
other test builds its own configuration. `tests/test_deploy_config.py`
instead reads the deployment files the way a deployer does and asserts the
properties that make a fresh machine work:

* every field in `Settings` is either in `.env.prod.example` or on an
  explicit exemption list with a reason (and the exemption list is checked
  for names that no longer exist);
* no key in the example is one the backend never reads — a typo there is
  otherwise completely silent;
* every `CHANGE_ME_*` placeholder is substituted by `bootstrap.sh`, so none
  can reach production as the literal string;
* every long-running service restarts itself, and only Caddy publishes ports.

**Log limits are part of this, not housekeeping.** Docker's default
json-file driver has no size cap at all. One chatty container fills the
partition, and the symptom is every service failing at once for reasons that
look nothing like logging — a genuinely expensive afternoon. 10 MB × 3 files
per service bounds the whole stack at roughly 250 MB.

**Backups go off-box, deduplicated, encrypted, and rehearsed.** restic
rather than `tar` + `scp` because the photos are the bulk of the data and
barely change between nights: the second backup of a 20 GB store costs
megabytes. The database dump is written to a file and decoded in full
(`pg_restore -f /dev/null`) *before* it enters the repository — `--list`
reads only the table of contents at the front of the archive and passes a
dump that was cut off halfway, and piping `pg_dump` straight into restic
stores a truncated stream as a perfectly good snapshot. Failures are
reported to the operator's Telegram, because a backup nobody is told has
stopped is indistinguishable from no backup. `restore.sh --drill` exists so
the restore path is exercised on a normal Tuesday rather than discovered on
the worst day of the year.

**A76 — Nothing on the money path fails quietly.** The state machine has
always declared what entering a status *means* (`EFFECTS_ON_ENTER`) and left
the doing to the service layer. That split is right. It has exactly one
failure mode, and the codebase had it: **`Effect.ALERT_OPERATOR` was
declared on entering `render_failed` from the first day and executed by
nothing.** The single place that received it wrote a log line and a comment
promising the wiring later. A customer's paid order could fail to render and
the only trace was a log nobody reads.

Three ways a paid order could stop moving in silence, all now closed:

* **The render raised.** The order went to `render_failed` and the declared
  alert went nowhere.
* **The render worker was killed** — OOM, a deploy, a reboot. The order sat
  in `rendering` with nothing to finish it, nothing to retry it, and nothing
  to notice. It looks busy forever.
* **The message to the printer gave up.** After eight attempts the outbox
  abandons a message. The order stays `rendered`, which looks entirely
  healthy, and the printer has heard nothing.

**Effects are executed from a registry, not by hand at each call site**
(`app/services/effects.py`), and a test asserts every declared effect has an
executor. Declaring an effect nobody runs now fails the suite, which is when
the mistake is cheap. The registry also records *when* each effect runs,
because two of them sit on opposite sides of one commit and putting either on
the wrong side is a silent race rather than an error: an outbox row must be
written in the same transaction as the status it announces, and a queue job
must not be dispatched until that transaction is durable — enqueue first and
the worker can read the order in its pre-paid state and quietly do nothing.

**The watchdog re-labels; it does not kill.** A render past
`RENDER_STALL_AFTER_S` is moved to `render_failed`, which is retryable and
loud. The threshold is therefore a "certainly dead" figure, not a deadline —
30 minutes against real renders measured in a couple of minutes. It will
still occasionally be wrong about a job that is merely slow, so a render that
finishes after being declared stalled **walks itself back through
`rendering`**, the legal route, rather than overwriting the watchdog's status
behind its back. Without that the finishing job raises `IllegalTransition`
and the completed render is lost; the test that covers it fails exactly that
way when the walk-back is removed.

**The console carries its own view, and this is the load-bearing part.** An
alert cannot report that alerting is broken. If the bot token is wrong or the
network to Telegram is down, every alert retries and is abandoned, including
the one carrying the print files. So `/admin/attention` reads the database
directly — failed renders, stalled renders, and outbox messages that gave up
— and the console shows it above the orders list. It is **hidden entirely
when there is nothing wrong**: a panel that is always on screen is one the
operator stops seeing, and this one has to be believed on the day it finally
says something. Abandoned messages are described by what they mean ("the
printer was never sent this order's files"), not by their topic —
`order.rendered` reads like good news.

Alerts carry the order reference and no other customer PII. A Telegram chat
is not an authenticated surface; the console is, and it is one tap away.

**The lock test now derives its route list from the router.** It used to be
typed out by hand under a comment promising that no new route could skip the
lock. The orders section (A73) then added six routes and none were added to
the list, so the most important assertion in that file had not run against
the endpoints that hand out customer addresses and print files. Deriving the
list drops the promise and keeps the property: 5 routes covered before, 11
after.

**A77 — Every route is throttled or exempt on purpose.** `GET
/api/v1/orders/{ref}?phone=` shipped unauthenticated and unthrottled. By
design a wrong phone answers exactly like an unknown reference — the same
principle as the 404s in A15 and A72 — which is right, and which makes the
request rate the whole security boundary: an attacker has no signal to work
with and nothing to do but try again, quickly. Unthrottled, that is a free
oracle over reference × phone, and Uzbek mobile numbers are not a large
space.

An indistinguishable-answer design and a rate limit are two halves of one
control. Shipping either without the other is the mistake.

The limit is 20/minute per IP — a customer refreshing their own order does it
a handful of times — and per IP rather than global, so one attacker cannot
take the order page away from everyone who has paid. `test_rate_limit_
coverage.py` reads the router and requires every route to be either throttled
or on an EXEMPT list with the reason guessing at it is not a volume problem.
That is deliberately the same shape as the admin lock test: a route inventory
written in prose goes stale, and this one names the two exemption classes
(a 32-byte edit token, and public data identical for everybody) instead of
promising completeness.

**A78 — An expired book says it expired.** `ErrorCode.BOOK_EXPIRED` was
mapped to 410 from the first milestone and raised by nothing. An expired
draft answered `BOOK_LOCKED` — "book is locked and can no longer be edited" —
which is what a book says after it has been *bought*. A customer returning to
an abandoned draft was told, in effect, that they had already ordered it. The
editor has carried three branches handling BOOK_EXPIRED all along; none could
fire.

410 rather than 404 because R6 has already deleted the photos: there is
nothing left to serve, and "not found" invites the customer to go hunting for
a link that will never work again. Authentication still comes first, so a
wrong edit token answers 404 exactly as before — expiry must not become an
oracle for which book ids exist.

**A79 — The low-resolution rule classifies; it does not refuse.** Its
docstring used to claim it "prevents printing a visibly blurry book". It
prevented nothing: `placement_resolution()` was called only by its own tests
and `RESOLUTION_TOO_LOW` was raised nowhere.

**Refusing is still the wrong answer, and that is a decision rather than an
omission.** The threshold cannot tell a careless crop from the only
surviving photograph of somebody's grandmother, and the customer is warned
clearly — the editor names the pages that will print soft, on the preview
screen, above the confirm box they must tick. What the system owes them is
that nobody is surprised, not that the choice is taken away.

What was missing is the third reader. The customer sees it before paying; the
system knew it at render time; the person about to put ink on paper — the
last one for whom it is a cheap problem — was told nothing. The production
notification now names the pages above the file links, and the console shows
the same on the order, both saying explicitly that the customer saw the
warning and confirmed, so the printer's first instinct is not to stop and
ask.

**The editor's copy of the rules is now tested against this one.** It
reimplements the arithmetic in JavaScript under a comment calling itself an
exact mirror "thresholds and all", and nothing checked. Drift is not
cosmetic: the editor's numbers decide what the customer is warned about, the
Python decides what the printer is told, and a disagreement means someone is
told the wrong thing invisibly. The test asserts the constants exactly and
the formula by shape — zoom still divides, contain still takes the better
axis and cover the worse, contain stays exempt from the 800px floor, an
un-ingested photo is still skipped rather than condemned. Parsing rather than
running: a JS engine in the backend suite would cost more than it protects,
and these are the edits that realistically happen.

**A80 — A book that has been paid for keeps its photos.** `photos.py` had no
mutability check of any kind. Every other layout mutation runs through
`_require_mutable`; `books.py` opens with a docstring saying every one of
them does; `checkout` tells the customer, in those words, that "after payment
the book cannot be edited". Deleting a photo — the most destructive edit in
the product, since the row and the object both go — was the one path with no
gate at all.

The sequence that mattered: check out, pay, and then delete a photo while the
render is still running. Preflight finds a placement pointing at a photo that
is not there, the order lands in `render_failed`, and the file is not coming
back. The customer's own edit link was enough; no attacker required, just a
second browser tab and a change of mind. Upload issuance and completion are
gated the same way, because a book somebody has paid for is finished.

**Deleting a photo now removes its placements, server-side, in the same
transaction.** The editor already tidied up and autosaved, so the invariant
held for exactly as long as that one request landed. When it did not, the
result was a book that could neither be ordered nor repaired: checkout
refuses with `PAGES_INCOMPLETE` naming a page that still has a placement on
it, so the page does not read as empty, and "take me to the first empty page"
went somewhere else. Cleaning up in the layer that owns the data removes the
whole failure mode rather than narrowing the window.

The layout version is bumped with the cleanup, so an editor holding the old
document loses the If-Match race instead of saving the deleted photo back —
and is left alone entirely when the photo was not placed anywhere, so tidying
the tray does not cost an open editor its next save.

Books already in production may still carry a dangling reference from before
this. The editor's "first page that needs a photo" therefore counts a
placement whose photo is missing as unfinished, which repairs the dead end
for those without a migration.

**A81 — The launch checklist is a program.** Every placeholder in this
product was tracked in prose: a comment here, a line in a deployment guide
there, a paragraph in this file, a sentence in a chat message. Prose is how
`ADMIN_TOKEN` came to be missing from the production env template (A75), how
the admin lock test came to cover five routes out of eleven (A76), and how
`Effect.ALERT_OPERATOR` sat declared and executed by nothing for the life of
the state machine. All of those were found by reading. `scripts/launch_
check.py` exists so the next one does not have to be.

It reads the real files — `deploy/.env` if the machine has one, the site's
own HTML, the shipped defaults — and prints what stands between here and
taking money, with the fix beside each, exiting non-zero while anything
blocks.

**It does not check that the numbers are right, and cannot.** Only the
printer knows the spine width; only the founder knows the price. What it
checks is that somebody has been *asked*, which is the failure that actually
happens — the spine values are still the ones the specification invented, and
they will stay plausible-looking forever unless something counts them.

Two design points worth keeping:

* **Absent reads as not-done.** A missing `PRICES_CONFIRMED` is not
  permission, and empty `SPINE_MM_*` means the defaults, which are the
  guesses. A checklist that treats silence as a pass is the same false
  confidence as a backup job that runs nightly and stores nothing.
* **No backups warns; it does not block.** Selling without backups is
  serious and is not a reason to refuse to sell. Keeping that distinction is
  what stops the STOP list becoming background noise.

Every check is tested in both directions — it must fire on the placeholder
and go quiet on a real value — because the failure mode of a checklist is
saying "all clear" too readily. Writing those tests immediately caught a
bug in the card check: `"8600000000000000".strip("0")` is `"86"`, not
`"8600"`, so the placeholder card was only being caught by its placeholder
holder name.

The site contacts are on the list for a reason beyond tidiness. They render
as working links: a visitor who taps the phone number or the Telegram handle
on the live site reaches a dead end, which reads worse than no link at all.

The physical test book is on the list too, and no program can verify it. It
stays outstanding until a human explicitly says otherwise by creating
`docs/.test-book-printed`. Every geometry number in this system is unverified
against paper until then, and a checklist that quietly omitted the one item
it could not measure would be worse than useless.
