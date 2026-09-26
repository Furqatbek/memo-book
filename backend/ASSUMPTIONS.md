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

**A82 — The API documentation does not publish what A72 hides.** A72 makes
the admin API deliberately unfindable: every refusal is a 404 so a wrong
token, a missing token and a switched-off admin are indistinguishable, the
comparison is constant-time, and attempts are rate-limited per IP. That
reasoning is written out, tested per route, and load-bearing.

`/openapi.json` published all nine admin routes — paths, methods, parameter
names, request schemas — unauthenticated, on the same host, **with
`ADMIN_TOKEN` empty and every admin route answering 404**. The lock was
excellent and the key was taped to the door.

The interactive docs and the schema behind them are now dev-only, on the same
`ENV=dev` gate as the simulated-payment config. Losing them in production
costs one environment variable; keeping them costs A72 its entire point.
`/health` and `/ready` stay public, because a load balancer, an uptime
monitor and `bootstrap.sh` all need them, and a test asserts that hiding one
did not hide the other.

Two smaller things found in the same sweep:

* **Shrinking a book asked about two kinds of content and dropped three.**
  `reflow_layout` counts placements, text boxes and stickers in its warning —
  the API warns, it never silently drops (R3) — but the editor's confirmation
  prompt tested only placements and texts. A customer whose trailing pages
  held nothing but stickers lost them without being asked. Same drift as the
  resolution mirror: two implementations of one rule, with a promise instead
  of a test.
* **The storage host sent no `X-Content-Type-Options`.** Everything it serves
  is a file a stranger uploaded. Uploads are already restricted to
  JPEG/PNG/HEIC and the presigned PUT signs the content type, so this is
  belt-and-braces — but it is free, and what it prevents is a stored file
  being interpreted as markup.

**A83 — `robots.txt` and `sitemap.xml`, and a test that they actually
ship.** A five-language site with `hreflang` clusters and no sitemap is
leaving the clearest signal it has on the table, and no `robots.txt` meant
crawlers walking `/editor/` and `/admin/` — both already `noindex`, so
nothing was being indexed that should not have been, but the trip was
pointless and the requests hit the API.

The sitemap repeats the full alternate set on every URL, itself included,
because a cluster is only valid if each member points at every member. The
codes match the pages' own tags exactly, `uz-Cyrl` capital included: a
sitemap that disagreed with the markup would be worse than neither, and a
test compares the two rather than trusting that they match.

**No `<lastmod>`.** The file is hand-written, so any date in it is wrong the
day after the site next changes, and a lastmod that cannot be trusted is
ignored at best.

The part worth more than the files: **three places enumerate the marketing
site by hand** — the Dockerfile's COPY list, the Pages workflow's `cp -r`
line, and that workflow's `paths:` trigger. A file added to the repository
and to only one of them is served by one route and silently missing from the
other, and "silently missing" for a `robots.txt` is a thing nothing in the
product would ever complain about. `tests/test_site_deploy.py` derives both
lists and requires them to agree, including that editing either file
triggers a redeploy — otherwise it would sit correct in the repository and
stale on the site.

`.txt` and `.xml` join the revalidating suffixes in `WebAssets` (A58). They
are small text files whose entire purpose is being re-read; the media branch
would have given them a week of caching on the one thing you might need to
change in a hurry.

**A84 — The screens on the way in and out are a shop window, not a form.**
The four customer-facing screens outside the editor — start, preview,
checkout, order — carry none of the customer's own photos yet, so everything
they convey about whether this is worth an evening and 299 000 UZS has to
come from the page itself. They were plain, and the feedback was that they
looked it.

Three decisions, in the order they matter:

**A sheet.** Everything to read or decide sits on one piece of paper, lifted
off the background with a two-layer shadow and a hairline of gold along its
head. Without a surface, a form on an illustrated background reads as an
accident rather than a design; with one, the background is free to be
scenery. The perk row and the "track an order" link carry quieter surfaces
of their own for the same reason — they are the parts that land squarely on
the drawing, and no amount of translucency stops a 2px ink line reading
through a sentence.

**Two real families, both self-hosted.** `EB Garamond` for display and
`Montserrat` for the interface, so there is no third-party request — which
matters more than usual when the customers are in Tashkent and the CDN is
not. A Garamond revival is a book face for a book product, and it gives the
interface a voice of its own instead of borrowing the operating system's.

The constraint that decided it was **glyph coverage, not taste**: of the
display serifs considered, Playfair Display has no Uzbek Cyrillic `Ҳ/ҳ`, and
Cormorant, Spectral, Bitter, Alegreya and Source Serif 4 have no Karakalpak
`ǵ`. A missing glyph falls back *per character*, so one word renders in two
different typefaces — visible, and invisible to anyone testing in English.

The shipped files are subset to a few hundred characters (23 KB a weight
rather than ~380 KB), and a subset is a promise about coverage that quietly
stops being true the first time someone adds a string. So the character set
is **derived once**, in `scripts/subset_web_font.py`, from `editor/js/i18n.js`
and `editor/index.html`, including both cases of every letter because
`text-transform: uppercase` is invisible to a scan of the strings; and
`tests/test_web_fonts.py` imports the same function rather than keeping its
own list. Its first run found two characters already missing on screen: the
non-breaking space `toLocaleString('ru-RU')` puts inside every price, and
the `·` between the book type and the "change" link.

**A drawing, not a photograph.** `editor/img/dream.svg` — an open book lit
from inside on a hillside, its pages lifting away as photographs into a
night sky — costs 6 KB, scales to any width and needs no third-party
request. The book sits in the **left third on purpose**: centred, it landed
behind the middle of the perk row at every viewport width.

The editor itself is deliberately untouched. Its job is to disappear behind
the photos, and every token above is additive for that reason.

**`tests/test_editor_assets.py`** covers the class of bug this work could
introduce: the editor is a no-build frontend, so a renamed illustration or a
mistyped `?v=` stamp is a runtime 404 that nothing fails on — the page still
renders, just without its background, its font, or the module that wires up
a button. The test reads the markup, the stylesheet and the modules and
requires every same-origin URL they name to exist.

**A85 — A button you can press and that does nothing is worse than one you
cannot.** The admin console's order actions ran through `act()`, which sets
`S.busy = true`, disables the buttons, and then — as soon as the transition
returns — calls `renderDetail()`. `renderDetail` rebuilds the action buttons,
**enabled**, while `act()` is still busy for two more round trips: the order
list, then the attention panel. Every click in that window hit the
`if (S.busy) return` guard at the top of `act()` and did nothing at all. No
move, no error, no toast. The operator presses "Shipped" and the order does
not ship.

`renderActions` now disables the set whenever `S.busy`, and `act()` renders
them once more in its `finally`, so the buttons are live again exactly when
the console is ready to act on them.

This surfaced as a flaky browser check — `ordersadmin` timing out waiting for
a status that was never going to change, then passing on a re-run. The
tempting fix was to raise the timeout. It would not have worked: the click
had been swallowed, so nothing was in flight and no amount of waiting would
have produced the transition. **A retry that passes is evidence about
timing, not evidence that nothing is wrong.**

The check now waits for the end of the action cycle rather than the first
repaint, and asserts the invariant directly. Making it a real regression test
needed one more step: on an idle machine the busy window is a few
milliseconds, so the check passed even with the bug reinstated. It now holds
the order-list request back deliberately (`page.route`) to force the window
open, and fails with the button it was offered. Verified in both directions —
the check fails with the fix reverted and passes with it in place.

Timeouts in that check were raised too, where they were genuinely tight
rather than racy: placing an order renders 32 pages inline and gets the same
240s budget as `checks/shots.js`, which walks the same path; the list and
search waits went from 20s to 30s.

`tests/test_editor_assets.py` now covers the admin console as well as the
editor — same no-build structure, same silent-404 risk — and additionally
requires a `?v=` stamp on module-to-module imports, not just the ones in the
markup. `app.js` importing an unstamped `orders.js` is the same stale-code
trap one level down (A61).

**A86 — `/admin` and `/editor` without the trailing slash.** Typing
`rspixel.uz/admin` into a browser answered `{"detail":"Not Found"}` in
production. `/admin/` was fine; the slash was the whole difference.

Starlette matches a mounted app on `^/admin(?P<path>/.*)$`, so a bare
`/admin` does not match it. Starlette has a redirect-slashes fallback for
exactly this, but it only fires when **nothing** matched — and the site mount
at `/` matches everything. So `/admin` fell through to the site, which went
looking for a file of that name and 404'd. `/ru` worked (307) only because it
is a directory *inside* that mount, where StaticFiles does its own redirect.

The two paths this hit are the two most likely to be typed by hand rather
than followed from a link, which is why it survived: nothing in the product
ever links to `/admin` without the slash, and no check typed it.

Fixed with an explicit `GET /admin` -> `/admin/` (and the same for
`/editor`), registered only when the corresponding mount exists — a redirect
to a mount that was never registered would answer 307 and then 404, which is
worse than the honest 404. Query strings are carried across: the address
someone pastes may well have one. 307 rather than a permanent redirect,
matching what the site already does for `/ru`, so nothing is cached forever
by a browser if these paths ever move.

The admin console is at **`/admin/` on the main domain** — there is no
`admin.` subdomain, and the Caddyfile serves four names only: `DOMAIN`,
`api.DOMAIN`, `www.DOMAIN` (redirect) and `storage.DOMAIN`.

**A87 — `admin.DOMAIN`, on request.** The operator console now has a
hostname of its own. The backend still serves it at `/admin`, so the
subdomain is a second door, not a move: `https://DOMAIN/admin/` keeps
working, and every bookmark, doc and note that points there stays correct.

`handle` blocks rather than a bare rewrite, because the ordering is the
whole trick. The console talks to the API with **absolute** paths
(`/api/v1/admin/...`), so those must reach the backend untouched; rewriting
them into `/admin/api/...` would leave a page that loads perfectly and then
does nothing at all. `/api/*` is handled first, everything else is rewritten
to `/admin{uri}` — `{uri}` and not `{path}`, because every module the page
imports is stamped `?v=...` (A61) and dropping the query would serve stale
code from a browser cache.

**What it costs, which is worth stating plainly.** Every certificate Caddy
obtains is published in the public Certificate Transparency logs, which
anyone can search. A72 goes to some length to make the admin API
*unfindable* — every refusal is a 404, so a wrong token, a missing token and
a switched-off admin are indistinguishable — and a hostname called `admin.`
announces that a console exists. That is a real reduction in obscurity. It
is not a reduction in security: the token was always the thing protecting
this, and it still is. Deleting the block restores the quiet address.

No robots.txt on that host, deliberately. `X-Robots-Tag: noindex, nofollow`
goes on every response instead: robots.txt asks a crawler not to *fetch*,
which does not stop a URL being indexed from someone else's link, and the
file is itself a public list of what you would rather nobody looked at.

Verified by running it, not by reading it — Caddy 2.8.4 against the real
backend, checking that the console loads at the root, that its stylesheet
and modules resolve with their cache stamps intact (`Cache-Control:
no-cache`), that `/api/v1/prices` comes back byte-identical to a direct
request, and that `/admin/` on the main host still answers 200.

The test that came out of this found a live gap on its first run: the
Caddyfile served a hostname `deploy/README.md` never told the deployer to
create a DNS record for. A missing record fails *quietly* — Caddy simply
never gets a certificate for that name and it stays unreachable while
everything else works — so the README list and the Caddyfile are now
compared to each other rather than maintained side by side.

**A88 — the turn-in is on three sides, and both documents said four.**
Asked what size a cover template should be, the honest answer needed
checking rather than repeating: `docs/cover-designs.md` and
`cover_design.py spec` both said "16 mm all round folds out of sight" and
"only the middle 148 x 210 mm is seen on the closed book". Measured against
the renderer, neither is true.

The artwork is 164 x 242 mm because it is the 148 x 210 front panel plus
**one** 16 mm turn-in in width and **two** in height. The left edge is the
spine fold — `photo_box_px` says so in as many words ("the left edge is
never extended: the spine is there, not a turn-in") — so the visible panel
sits flush against the left of the file, not centred in it.

Rendering a cover and measuring each edge gives 0 / 16 / 16 / 16 mm for
left / right / top / bottom. A designer following the old text would have
kept a 16 mm margin that does not exist on the left, losing that much usable
width, and centring a subject in the file would put it **8 mm off-centre on
the printed book** — findable only from a printed proof, which is the most
expensive place to find anything.

Both documents now state the per-edge margins and where the real centre is
(x = 74 mm from the file's left edge). `tests/test_cover_artwork_guidance.py`
derives those margins from the renderer's own paste box and requires both
documents to state them, including refusing the exact phrases that were
wrong. Prose about geometry, checked against the geometry.

The px→mm arithmetic lands a fiftieth of a millimetre short because the
paste box is computed in whole pixels; the test rounds that away but asserts
first that the error really is sub-pixel, so a genuine half-millimetre drift
could not hide inside the rounding.

**A89 — an empty cover title looked exactly like a title that would not
clear.** A new book arrives with the title filled in ("Our travels" for a
travel book) — a starting point, not a decision. Clearing it worked
perfectly: the editor emptied, the server stored `""`, a full reload kept it
empty, and the renderer draws nothing (`if title:`). Every layer was right.

The screen said otherwise. The placeholder sat in the title's own position,
at the title's own weight and size, at 75% opacity, reading "Title". Nothing
distinguished it from printed text. It was reported as a bug by the person
who built the product, which is about as clear a signal as a UI ever gives.

Two changes, and neither hides the affordance — the placeholder is the only
thing telling a customer they may put a title there at all, and hover does
not exist on a phone:

* **It asks instead of naming.** "Title" → "Add a title", in all five
  languages. A bare noun in the title's own style *is* a title; an
  instruction cannot be read as one.
* **The empty field is outlined as a field** — a dashed rule, italic,
  quieter. No printed cover has a dashed box on it.

`browser-tests/checks/covertitle.js` holds the whole chain: prefilled,
cleared, stored empty, still empty after a reload, still rendering — plus
that the placeholder is a phrase rather than a noun and that the empty field
carries a dashed outline. Verified it fails when the wording is reverted.

The general point, and the reason this is written down rather than just
fixed: **every layer being correct is not the same as the product being
correct.** Nothing here was broken except what the customer could see, and
that was the only part that mattered.

**A90 — a cover design could not say "this artwork already has its own
lettering".** The admin console's design form offered the title as three
numbers — x, y, size — and nothing else. Every design it saved carried a
title block, whether the art wanted one or not. Upload a cover with the words
already drawn into it and the renderer put a second title on top; there was
no way to say no.

Nothing underneath was missing. `upsert_design` has always stored
`title_x_mm = title["x_mm"] if title else None`, the serializer omits the
`title` key entirely when there is none, and `cover_design.py --title` is
optional. **The console was the single place that could not express a
capability the rest of the system already had** — and the console is what a
person actually uses, so in practice the capability did not exist.

The photo window next to it had the control all along: a checkbox, "This
design has a window for the customer's photo", with `readRect()` returning
null when it is off. The title now mirrors it exactly — same markup shape,
same `.numbers.off` styling, same null return — which is why the fix is four
small edits rather than a new mechanism.

`checks/admincheck.js` covers the round trip: unticking hides the title from
the live preview, saving produces a design the API returns with no `title`
key at all, and ticking it back puts one there again — a setting, not a
one-way door. Verified it fails when `readTitle()` loses its null return.

Worth noticing as a pattern: this is the second defect this session where
every layer was correct and only the surface was wrong (A89 was the first).
Both were found by a person using the product, neither by a test, because
every test asserted the layer it owned and all of those layers were fine.

**A91 — the back cover holds photos.** It was a flat colour and nothing
else. It now takes the same slot grid an interior page uses: `cover.back`
carries a `layout` id and a list of `PlacementDoc`, the type interior pages
already use, so crop, zoom, focus and rotation arrive without new code and a
customer learns nothing new to use it.

Blank stays the default, and blank is a *finished* state — not a to-do.

**The one genuinely new thing is geometry, and it is a mirror.** The front
bleeds RIGHT into the turn-in and stops LEFT at the spine fold, so the back
must bleed LEFT and stop RIGHT. Reflecting that wrong pushes art across the
spine onto the other face of the closed book: visible on every printed copy,
invisible on screen until somebody folds one. `back_box_px` is the mirror,
and the tests assert the mirror *property* against `photo_box_px` rather
than the arithmetic I happened to write.

Photos only. Interior pages carry texts and stickers too, but the back is
the one surface nobody turns to while reading, and the two buttons that
would do nothing there are hidden rather than left dead (A85, A90 — the
third time this session). Adding them later is a field, not a migration.

The editor reaches it through one accessor. `pageDoc(index)` returns the
back as a page-shaped **live view** — `placements` is the real array, the
colour reads and writes the cover's own because the back and the front are
one printed sheet in one colour, and `texts`/`stickers` are frozen empties
so a stray push throws here instead of being dropped on the way to the
server. Eight call sites indexed `layout.pages[S.page]` directly; the three
reachable from the back now go through the accessor and the rest are
guarded by `facingPage()` already returning -1.

**Two mistakes the checks caught, both mine, both design rather than code:**

* The gutter guide drew on the left. The back hinges on its RIGHT — the
  spine is between it and the front — so it was telling the customer to
  keep clear of the wrong edge.
* `e2e` hung waiting for no `.empty` filmstrip item after auto-fill. The
  back was marked empty, auto-fill correctly does not touch it, so the
  condition could never be met. The fix was the product's, not the check's:
  a blank back is finished, and nothing should nag about it.

The preview shows the back whenever it carries anything, and no tile when it
does not — `back_url: null`. That is not decoration: **the preview is the
contract**, so anything a customer can put on the book has to be there to be
confirmed. It renders through `render_preview_page`, because the panel is
148x210 with a slot grid and placements — an interior page in every respect
the preview cares about — rather than a near-copy that could drift.

The front cover's own trade-off is inherited unchanged (A70): print bleeds
into the 16mm turn-in while the editor and preview show a 3mm bleed, so the
crop within the visible panel differs very slightly between screen and
paper. Consistent with the front rather than a new inconsistency, and the
same magnitude.

**A92 — `+ Text` was dead on the front cover, and always had been.**
`addTextBoxAt` returned early for the cover from the day it was written, so
pressing the button did nothing at all. Not a regression: the cover has
never had anywhere to put a text box. `CoverDoc` has no `texts` field, the
cover PDF draws none, and the cover preview draws none.

Hidden rather than implemented, and the reason matters. The cover already
has words: a title and a subtitle, a block that moves, rotates, restyles and
recolours. A third text mechanism on the same panel would mean a schema
field, a renderer, a preview and an editor surface, to give a customer a
second way to do something they can already do — and two ways to put text on
a cover is a question the customer then has to answer. Inside pages are
freeform; the cover is a designed object. That distinction was deliberate,
and the dead button was the only thing contradicting it.

`+ Sticker` stays on the cover: stickers genuinely print there
(`cover.py` draws them). The back offers neither (A91).

Third dead-button fix of the same session (A85, A90), so the check now
asserts the *rule* rather than this instance: on the cover, an inside page
and the back, every button on offer is one that does something, and pressing
`+ Text` on an inside page really does add a box. Verified it fails when the
guard is loosened back.

**A93 — every customer with an iPhone got a failed preview.** Reported from
production: HEIC photos upload, the tray looks perfect, and the preview
fails.

The chain, and every link of it was individually reasonable:

* the browser uploads the ORIGINAL file straight to storage, so an iPhone
  gives us HEIC;
* ingest writes JPEG `display` and `thumb` copies — which is why the tray
  looked right and nobody suspected the photos;
* `original_key` is never rewritten, and both the preview and the print
  render read the ORIGINAL, correctly, because the display copy is too small
  to print from;
* `pillow_heif.register_heif_opener()` lived in
  `app.services.image_processing`, the module that makes thumbnails, which
  the render path does not import;
* registering a codec is process-wide, so it only helps a process that has
  imported that module.

**Why no test caught it.** In development `TASK_EAGER` runs ingest, preview
and render inside the one API process, which imports the photos service, so
the opener was always registered. Production runs an RQ worker that forks
per job: the preview child imported the render path alone and `Image.open`
raised `UnidentifiedImageError`. The bug existed only where the processes
were separate — and every fixture was a JPEG besides.

Registration moved to `app/__init__.py`. Python imports parent packages
first, so any `import app.anything` has already run it: there is no longer a
way to reach our imaging code without it. One home, not two.

**The test is a subprocess, deliberately.** Inside pytest the registry is
already populated by other tests' imports, so an in-process assertion passes
no matter where the registration lives — which is exactly the blindness that
let this ship. `tests/render/test_heic_pipeline.py` runs the compositor and
the cover renderer in fresh interpreters that import nothing else, asserts
`app.services.image_processing not in sys.modules` before it starts, and
includes a test that bare Pillow CANNOT open HEIC — so if that ever begins
to pass, the others have quietly stopped proving anything.

**`checks/heicflow.js` does not guard this**, and says so in its own header.
Measured, not assumed: with the original fault restored, the browser check
passes end to end, because the dev server is eager. It covers the other half
— that a real HEIC survives upload, layout changes, preview and the road to
checkout.

**A94 — a failed preview said "the layout changed".** The stale banner was
toggled inside the `ready` branch of the poll alone, so when a re-render
FAILED the previous poll's banner stayed on screen. The customer was told
their layout had changed and sent to fix the wrong thing; the truth was that
the preview could not be built at all. This is how A93 was reported, and the
misdirection cost more than the failure did.

Now cleared on every poll, before any branch decides what to say. The
general shape is worth keeping in mind: **a banner that is only ever turned
ON inside a conditional will eventually be shown next to a state that
contradicts it.**

**A95 — a design can carry back-panel artwork too.** A ready-made design was
one file, the front, and the back printed in the flat `bg_color`. Designs
that want a decorated back — a pattern, a colophon, a border that continues
round the book — had no way to say so.

A design now takes an optional SECOND file for the back. Deliberately a
second file rather than one wide back-spine-front image: the spine is the
only part of the wrap whose width varies between the four sizes, so keeping
it out of both files is precisely what lets one design serve all four. The
spine keeps the flat colour either way.

**The back file is the mirror of the front**, and mirrors are the thing to
be careful about here. It is 164 x 242 mm like the front, but the turn-in is
on the LEFT, top and bottom, and the RIGHT edge is the spine fold. That is
the back cover as you see it on a closed book, so the file reads the right
way round — and it reuses `back_box_px` (A91) rather than a second copy of
that geometry, so if the mirror is ever corrected both are corrected.

Getting it backwards is not cosmetic: art past the spine fold prints on the
*front* face of the closed book, over the design, on every copy — and looks
perfectly fine on screen until someone folds one. So the tests assert where
the ink lands in pixels on the real sheet, and were checked by deliberately
pasting the back through `photo_box_px`: five of them fail.

Three states, not two: **set it, clear it, leave it alone.** Re-uploading a
corrected front must not silently discard the back, so `upsert_design` only
touches the back when explicitly told to. The console gets a dedicated
`POST .../back-artwork` endpoint for the same reason — adding a back to a
finished design would otherwise mean re-uploading an unchanged front, and a
re-upload that is only a formality is exactly the step that eventually gets
done with the wrong file.

Two consequences worth naming:

* **A designed back earns a preview tile.** `_back_as_page` used to return
  None unless the customer had put photos there, which was right when the
  alternative was a flat rectangle. A back can now be fully designed and
  carry no photos, and the preview is the contract — a customer must not
  confirm a panel they were never shown.
* **`compose_page` grew a `bg_image_bytes` argument**, so the back panel
  still renders through the same function a real page does rather than a
  near-copy that could drift from it. Interior pages never pass one, and a
  test asserts that passing None is byte-identical to not passing it at all.

**A96 — the Telegram bot can be told to do things, if you switch it on.**
The bot could always talk: print notifications and attention alerts go out,
and everything else meant opening the console. Now each print notification
can carry buttons that move the order — sent to printer, shipped, delivered,
cancel — with `/orders` for anything that has scrolled out of reach.

**This reverses a judgement A76 made, so it is guarded accordingly.** A76
withholds customer PII from the attention alert on the explicit grounds that
"unlike this chat the console is authenticated". Making that chat a place
where orders can be *moved* needs three independent things, and is off until
all of them are true:

1. `TELEGRAM_WEBHOOK_SECRET`, compared constant-time against the header
   Telegram sends, so guessing the URL is not enough;
2. `TELEGRAM_CONTROL_USER_IDS`, an allowlist of Telegram USER ids, so being
   in the chat is not enough. This is the one worth restating: the chat
   holds 7-day signed links to every print file, so its readers are already
   a wider circle than its operators, and reading must not imply cancelling.
   An unparseable id is dropped, never guessed at — a typo must narrow the
   set, never widen it;
3. the state machine, unchanged. Presses go through `admin_orders.set_status`,
   the console's own path, so there is no "set it to whatever I say" here any
   more than there is there.

With either variable unset the route answers **404**, not 401 or 403 — the
admin API's property (A72), for the same reason: the endpoint is not an
oracle for whether an RS Pixel bot lives here. Every deployment that has
never heard of this feature therefore has no new surface at all, and a test
asserts the print notification is byte-for-byte unchanged in that state.

Three things a keyboard on a phone forces you to think about:

* **It is a cache of the order's state.** It can be stale — someone used the
  console meanwhile — or pressed twice. Neither may become a wrong write, so
  the press is re-checked against the live order and the keyboard is
  rewritten with whatever was actually true. A refusal refreshes the buttons
  too, because a refusal usually means the picture is out of date.
* **Telegram retries anything that is not a 200.** An exception in the
  handler would become an infinite redelivery loop rather than one failure,
  so `handle_update` never raises and a nonsense update is a logged 200.
* **`callback_data` is capped at 64 bytes** and Telegram rejects a longer
  one silently — a button that does nothing when pressed, which is the bug
  class A85/A90/A92 kept producing. `callback_data()` raises instead, and a
  test walks every status in the enum.

Both locks were checked by breaking them: disabling the allowlist fails
three tests, skipping the secret comparison fails two.

Not included, on purpose: confirming a payment. The production notification
only exists once an order is paid, so no message in the chat belongs to an
order awaiting a transfer, and a button nobody can reach is worse than none.

**A97 — a Telegram account links itself, from the console.** A96 kept the
operator list in `TELEGRAM_CONTROL_USER_IDS`. Adding a second person, or
removing one who left, meant an SSH session, a file edit and a restart — and
the only way to learn a Telegram user id was a CLI command that stops working
the moment a webhook exists. The list lives in the database now, and an
account joins it by redeeming a code.

**The obvious version of this does not work, and the reason is the whole
design.** "Send /subscribe, the bot replies with a code, type it back" proves
nothing: whatever the bot says is visible to everyone in the chat, so the
code would be a secret handed out by the surface we do not trust. It is a
loop — the thing you are proving access to is the thing that showed you the
secret.

So the code is issued in the **console**, which is authenticated, and
redeemed in the **bot**. Holding it means holding `ADMIN_TOKEN`; spending it
means controlling that Telegram account; the link binds the two. This is not
privilege escalation — anyone who can read the code can already cancel
orders in the console. It gives an existing authority a second handle.

What a code is worth, and why each part matters:

* **A day, once.** The length is the least of it: what keeps the window
  safe is that the code is single-use and that issuing a new one invalidates
  any outstanding one, so "press the button again" is the complete recovery
  for every way this goes wrong. A day because the person issuing the code
  and the person redeeming it are often not in the same room.
* **8 characters from a 30-letter alphabet** (~2^39), with I, L, O, U, 0 and
  1 left out because it is read off one screen and typed into a phone.
* **Five redemption attempts per account per minute.** This, not the
  expiry, is what makes guessing hopeless: a whole day at that rate buys
  7,200 tries against a keyspace of 6.6e11.
* **Wrong, expired and already-spent get one identical answer.** Telling
  them apart confirms that a guessed code was once real.
* **Stored as a SHA-256 hash.** It is a live credential while it lasts, and
  one that can be read out of a database backup is one worth not writing
  down.

**The gate moved, deliberately.** A96 made the webhook 404 unless the secret
AND the allowlist were set. The route now exists on the secret alone, because
`/link` has to be reachable before anybody is linked — that is how they
become linked. What replaced the 404 is not weaker: an unlinked account is
refused every action and told how to link. The test that used to assert the
404 now asserts the thing that actually matters, that the order does not
move.

`control_enabled()` is settings-only on purpose. Two callers need the answer
where no database is available — the webhook's own lock, and the outbox
worker deciding whether to draw buttons on a message it is sending from a
thread. So "is the feature on" stays a synchronous settings read, and "who
may act" is a per-press database check. The two questions were conflated in
A96 and separating them is what made this simple.

`TELEGRAM_CONTROL_USER_IDS` survives as a **break-glass path**: an id there
acts without being linked, for when the console is unreachable or the last
linked account was removed by accident. The console lists those ids and says
they cannot be revoked from there, because a Remove button that silently did
nothing would be worse than no button.

Checked by breaking it: dropping the single-use and expiry conditions from
the redemption query fails four tests.

**A98 — a signed image URL has to outlive the sitting, not the request.**
`DISPLAY_URL_EXPIRY_S` was one hour. The editor asks for those URLs exactly
once, when the book loads, and never asks again — there is no refresh, no
retry, no periodic re-fetch. So a customer who spent ninety minutes
arranging their book watched every thumbnail and every canvas image turn
into a broken icon, an hour in, with nothing on screen to explain it and
nothing to do but reload and lose their place.

Nothing errored to make this visible. The server was fine; the page was
holding credentials that aged out in its hand. That is the shape worth
remembering: **a deadline on a thing the client caches is a bug that fires
on the client's clock, not on ours, and it never shows up in a log.**

Now a day, which covers any real session — and someone who comes back
tomorrow reloads the page and is handed fresh URLs anyway. The cost is that
a leaked URL stays good longer; these sign the customer's own photos and our
cover artwork, not the print files, which have their own deliberate week.

The three deadlines now have a stated ordering, and a test holds it:

    upload (one request, 15 min)
      < display (one sitting, 1 day)
        < print file (the printer's week, 7 days)

Each is sized to the thing it must outlive. The tests read the deadline back
out of the signature rather than asserting the constant against itself, so
they measure what a browser is actually handed — and they cover both
signature versions, because the answer must not depend on which one boto
happens to use. Reverting the display constant to an hour fails two of them.

One more thing the test pins: the console and the Telegram message hold the
same seven-day figure in two separate constants, in two separate modules,
and both tell the printer "7-day link". A printer told seven days by one and
given four by the other would find out on day five.

**Not fixed, and worth knowing:** a page left open longer than a day still
ages out. The real repair is for the editor to notice a failed image and
re-fetch, which is a bigger change than this was.

**A99 — a stale image asks for a fresh URL instead of staying broken.** A98
gave signed image URLs a day, which made the editor's broken-thumbnail
failure rare. This makes it recoverable: when an image fails to load, the
page asks for fresh URLs once and redraws itself.

**One listener covers every image on every screen**, including ones drawn
later, because `error` on an `<img>` does not bubble but does CAPTURE. A
regex on `Expires` / `X-Amz-Signature` keeps it to our own signed storage
URLs — a sticker or the background drawing is served from this origin and a
refresh would do nothing for it.

**The guards are the feature, not the trimming.** "An image failed" is not
the same as "the URL expired": an object that is genuinely gone fails every
single time, so a refresh fired per failure would be an endless loop pointed
at our own API — the exact shape this codebase keeps producing (A85, A90,
A92). So: one refresh in flight at a time, one a minute at most, and five
per page at the outside. Past that the images stay broken, which is honest.
The cooldown is measured from when a refresh FINISHED, or a slow one would
let the next fire the moment it landed.

Two deliberate narrownesses:

* **It refreshes URLs, not state.** Only `display_url` / `thumb_url` on
  photos we already hold, and the URL fields of designs already known.
  A photo still uploading must not be dropped because it is missing from
  the response, and nothing the customer has arranged may move because a
  thumbnail expired.
* **The redraw does not force.** `renderCanvas()` declines to redraw while
  the customer is typing, and that rule is worth more than a thumbnail
  which will come back on the next redraw anyway.

Design objects are mutated in place rather than replaced, because `S.designs`
holds the same objects and swapping one would leave the gallery pointing at
the old. The preview grid is drawn straight from a poll response rather than
stored state, so re-polling IS its refresh.

The check proves both halves by breaking them. With the listener
unregistered: no re-fetch, and eight visible images stay broken. With the
guards removed: one broken image becomes five requests and nine dead ones
become nine more — the loop, on camera.

**Scope worth knowing:** the check asserts over VISIBLE images. The start
screen's design gallery sits in the DOM behind the editor and is not redrawn
by the refresh — it does not need to be, since it clears itself and
re-fetches the catalogue every time it is shown. Asserting over hidden DOM
would be asserting something nobody can observe.

**A100 — the customer attaches proof of their transfer.** In the
card-transfer pilot nobody tells us a payment arrived: the operator matches
transfers against the bank by hand. A screenshot of the transfer is the one
piece of evidence only the customer has, so they can now attach it to their
own order, and it appears beside the Confirm button where the operator
decides whether the money came.

**It is on the ORDER screen, not the checkout form**, and that is the one
place this was asked for differently. At checkout the customer has not seen
the card or the amount yet — there is nothing for them to have a receipt of.
The upload belongs under the bank card, at the moment they have just been
asked to send money, and it opens and closes with that card: `PAY_CARD_STATUSES`
was lifted out of `public_status` so the box and the card cannot drift into
disagreeing about when payment is still outstanding.

**The declared content type is ignored entirely.** A browser will send
`image/png` for a file of HTML, and these objects are served from our own
storage hostname — so a stored HTML file would be a script running on that
origin. The type is read from the first bytes, the file is stored under the
name WE decide, and anything not recognisably PNG, JPEG or PDF is refused
whatever it claims. Checked by breaking it: a `sniff` that falls back to
"probably a PNG" fails four tests, one of which uploads `<script>`.

Smaller decisions, each with a reason:

* **2 MB, checked twice.** The browser checks so a customer hears about a
  3 MB screenshot before spending their data on it; the server checks
  because it is the authority. The server reads one byte past the limit and
  no further — this endpoint is open to anyone holding a reference, so an
  unbounded read is an invitation. A test uploads exactly 2 MB, because an
  off-by-one on a published limit is the difference between "2 MB" being
  true and being nearly true.
* **The same door as the status page**: reference plus the phone on the
  order, sharing that endpoint's rate limit, with a wrong phone
  indistinguishable from an unknown reference (A77). A second, weaker way to
  reach an order is how a boundary stops being one. The phone rides in the
  form body rather than the query string, because a POST has no reason to
  write a customer's phone number into access logs.
* **The customer is told it arrived, never handed it back.** That page is
  guarded by a phone number, which is a weaker thing than a login, and a
  receipt can carry a bank balance across it. `receipt_uploaded_at` is a
  fact; the file is the operator's.
* **One receipt, replacing.** A second upload is nearly always a correction
  of the first. The previous object is deleted when the format differs, or
  an orphan nobody can reach is still a receipt sitting in a bucket.

This also added the i18n completeness test that did not exist. Nine strings
in five languages at once is exactly the change that leaves one locale
showing a customer a raw key like `receipt.title` — nothing errors, nothing
logs, and it only looks wrong to someone reading that language.

**A101 — the flake was a real bug, and it was ours.** `freeform` failed
intermittently for three sessions. It was reported honestly as "not caused
by this change" each time, which was true and was also not an answer.

The colour-swatch popup attached its dismiss listeners in a
`setTimeout(..., 0)`. For one tick after opening there was a popup on screen
and **nothing listening** for the click or the key that closes it. Anything
trying to close it in that window did nothing — and tore down listeners that
were then attached a tick later, with no popup to match. `freeform` picks a
colour on one tool and then reaches for the next; a popup still open turns
that second click into a toggle-shut, so the second colour is never picked
and the check waits for a popup that will not come.

Two things made this hard to see. It reproduced about once in eighty cycles,
so every "run it again" said it was fine. And **instrumenting it changed the
rate** — adding a MutationObserver and wrapping `addEventListener` took it
from 1-in-80 to 8-in-30, which is itself the tell: a timing race, not a
logic error. The trace that settled it was four entries long:
`["--cycle--", "POPUP+"]` — popup created, listeners never attached.

The timer was guarding against the opening interaction immediately closing
the popup it had just opened, and it never needed to. The handler runs on
`click`, whose `pointerdown` and `keydown` have already been and gone, and
`outsideSwatchClose` ignores `.color-tool` anyway. Attached synchronously,
the window does not exist.

`closeSwatchPop` also now removes EVERY `.swatch-pop` rather than the first.
Nothing should be able to put two on the page, but if anything did, the
second was left open with the listeners already torn down — a popup nothing
could dismiss. Closing all of them makes the function's name true whatever
led there.

**The guard does not hammer.** Hammering catches this once in eighty, which
is how it survived three sessions. `checks/swatchpop.js` opens the popup and
dismisses it IN THE SAME TASK: a deferred attach cannot have run by then, so
with the timer restored it fails 3 runs out of 3 rather than 1 in 80. That
is the lesson worth keeping — **when a race is only reachable inside one
tick, the test should occupy that tick rather than roll dice against it.**

**A102 — the second flake: a check that failed for the thing the product
recovers from.** `adminwiring` was the other intermittent failure, and it
was a different bug from A101 wearing the same clothes. Its failure named
nothing: every assertion printed `ok`, and the run still said FAILED.

Every check watched its page the same way — any `pageerror`, plus **any**
console message of type `error` — and then `if (errors.length) fails.push('page errors')`.
Chromium writes a console error for any resource that fails to load, so one
transient blip on one signed image URL failed a check in which nothing the
check actually asserts had gone wrong. Measured with a probe: zero console
errors in a clean run, exactly one — `Failed to load resource:
net::ERR_FAILED` — after a single aborted image. That is the whole
mechanism, and it explains the two things that made it look like a ghost:
the failure named nothing because nothing named had failed, and re-running
always passed because the blip is a blip.

It was also asserting something the product does not promise. **Since A99 a
failed signed image is a condition the editor recovers from** — it asks for
fresh URLs and redraws. A check that fails because a resource blipped is
failing for the thing we built the recovery to handle.

So the policy lives in one place, `checks/_watch.js`, and it is: resource-load
noise is **counted and printed, never fatal**; everything else stays fatal.
The two that matter are untouched — a `pageerror` is an uncaught exception
and always a real defect, and a console error our own code wrote is us
saying something is wrong. Fourteen checks now share it, including
`freeform`, which had both flakes at once.

**Not-fatal must not mean invisible**, so `watchPage` returns the ignored
lines and the checks print `ignored N resource-load line(s)`. And the policy
itself is held by a check rather than by this paragraph:
`checks/urlrefresh.js` breaks images on purpose, so it asserts that the
deliberate failures were recorded as noise and that none of them counted as
an error. With the old policy pasted back in, that check fails — which is
the only way to know the rule is still doing anything.

Two smaller things the hunt turned up. `run.js` was reducing a failed
check's entire output to the first line matching `/error|failed/i`, which is
enough to see THAT something failed and never enough to see why — and a
check that only fails inside a full run cannot be re-run alone to find out.
It now writes the whole output to `shots/<name>.fail.log`. And `run.js`
treated every `.js` in `checks/` as a check, so the shared `_watch.js` would
have been "run" and counted; files starting with `_` are now skipped.

**A102 — the receipt now tells someone it arrived.** A100 stored the
customer's proof of transfer, showed it in the admin console, and stopped
there. That left the evidence somewhere nobody was looking: an operator
learns a receipt exists by happening to open that order, so a customer can
pay, upload the screenshot, and wait while their proof sits in a bucket.
Storing it and announcing it are two different features, and only one of
them was built.

The upload now enqueues `order.receipt`, which reaches the operator chat as
a message with a **link to open the file**. Four things about it:

* **Enqueued in the receipt's own transaction.** One commit records the
  columns and the message, so there is no window where the file exists and
  nothing is going to say so — the whole reason the outbox exists.
* **The payload carries the KEY, not a URL.** Presigning at enqueue time
  puts a deadline on a message that has not been sent yet, so a delivery
  that waited out a Telegram outage and three backoffs would arrive with a
  link that no longer opens. It is signed at delivery, on every attempt,
  exactly as the print files are.
* **No buttons, deliberately.** The one action this message calls for is
  "the money arrived", and that is not a Telegram action: confirming a
  payment stamps `paid_at` and starts the render, which is why `paid` is
  absent from `OPERATOR_TARGETS`. The keyboard a `pending_payment` order
  would get here is a single *Cancel order* — sitting directly under a
  receipt, one fat thumb from killing the order the receipt is evidence
  for. A message with no buttons and a sentence saying where to go is the
  better object.
* **Reference, amount, link — no name, no phone.** A76's rule for this chat
  holds. What the operator needs in order to go to the bank is the amount
  and the picture.

Worth naming the tension rather than pretending it away: A76 calls this chat
unauthenticated, and this puts a seven-day link to a customer's bank
screenshot in it. The judgement is the same one already made for the print
files, which carry every photo in the book — whoever can read that chat can
already read a great deal, and narrowing that is `TELEGRAM_CHAT_ID`'s job,
not this message's. The customer is still never handed the file back: the
status page says only that it arrived.

Every upload sends, including a replacement, because a corrected receipt is
exactly the thing worth a second message. A refused upload sends nothing —
the enqueue is past the sniffing, so a file that is not a PNG, JPEG or PDF
never becomes a notification.

**A103 — a RAW photo, and a refusal that says why.** Somebody tried to
upload a `.dng`. Two separate things were wrong, and both of them were
silent.

**The editor refused it before it ever left the browser.** The file picker
did not offer `.dng`, and a file that got in anyway produced a red card
reading "Failed" and nothing else. There was no way to learn that the format
was the problem, let alone what to do about it — which is why the question
reached me as "problem with .dng images" rather than as a bug report.

**And had one reached the server, it would have been ACCEPTED.** This is the
part worth remembering. A DNG is a TIFF container, so Pillow opens one
without complaining — and hands back IFD0, which in a DNG is a **thumbnail**.
Measured on a file with a phone's layout: `Image.open` reported 320x240,
`process_image` returned that as the photo's dimensions, and the 4032x3024
picture sat in the file the whole time in a SubIFD nothing had looked at.
Nothing raised. Nothing logged. A twelve-megapixel photograph would have
gone into a printed book as a postage stamp, and the only warning anyone
would have got is the low-resolution badge — telling the customer their
photo was too small while the sharp version was inside the file they gave
us.

**Where the picture actually is.** IFD0 carries `SubIFDs` (tag 330): a list
of further IFDs holding the sensor data (a Bayer mosaic under lossless JPEG,
which nothing here decodes without a raw processor) and the previews the
camera rendered itself, which are ordinary JPEGs. `services/dng.py` walks
that structure and returns the **largest** picture present — "the first one"
being precisely the bug, since in a DNG the first one is the thumbnail.

Four judgements inside it:

* **The camera's rendering, not ours.** Even with LibRaw on hand, the
  embedded preview is the better source for a photo book: it is what the
  customer saw on their phone. Our own demosaic would be flatter and
  differently coloured — more faithful to the sensor, less faithful to the
  person.
* **Sniffed from the bytes.** The declared content type is whatever the
  browser said, and a DNG renamed `.jpg` is still a DNG. Detection reads the
  container, which also closes the hole where a mislabelled upload got the
  thumbnail treatment.
* **Sensor data is never mistaken for a picture.** The raw SubIFD is
  JPEG-compressed too; what disqualifies it is its photometric
  interpretation. A Bayer mosaic decoded as a photograph is a green grid.
* **The tags say JPEG; the bytes have the last word.** A strip that does not
  begin with SOI is skipped. Handing a decoder whatever a container points
  at is how a file format becomes an attack surface.

**It classifies, it does not refuse.** A DNG carrying only a thumbnail comes
through at that size and gets the ordinary low-resolution treatment, because
`domain/resolution.py` says that call is not this layer's to make (A79). The
tray does say something different about a RAW file, though: the sharp
version IS in the file, so the hint names the fix ("export a JPEG") instead
of blaming the photo.

**The other half: failures now name themselves.** `IngestError` carries a
stable `code` as well as its English prose, and the code is what is stored
on the photo — the column used to hold the prose, which nothing displayed.
The editor translates the code into one of five languages and prints it on
the card, and an unknown code prints nothing rather than showing a customer
a raw identifier like `photoerr.something`. Client-side refusals (wrong
type, too big) got the same treatment; before this they were indistinguish-
able from each other and from a server failure.

**The browser is not allowed to shrink a RAW file**, even where it offers
to. A DNG holds several images and nothing in `createImageBitmap` says which
one comes back — a downscaled thumbnail would look like a successful upload
and print like a postage stamp, which is the bug again with the evidence
moved somewhere we cannot see it. The server picks the image.

The cost of that decision is upload size: a ProRAW file is 25-80MB and goes
up whole, so a big one is refused for size and a `MAX_UPLOAD_BYTES` raise
would only make a Tashkent mobile upload slower. **Extracting the preview in
the browser** — the same SubIFD walk, in JavaScript, uploading a few MB
instead of tens — is the obvious next step and is deliberately not in this
change: it is a second parser against a format I cannot test on real files
here, and the server is the one that has to be right.

`checks/rawphoto.js` holds the whole thing, and it earns its place: with the
old `_pixel_source` pasted back, it fails reporting `320×240 px`.

**A104 — text on the cover that could not be removed.** Reported as
"default text on editor is impossible to turn off or delete". It was half
true, in the worse half.

Deleting the prefilled title DID work. The layout saved an empty title,
and both renderers already treat a blank title AND a blank subtitle as no
title block at all — `cover.py` and `preview.py` each return early. What
did not work was the editor: it kept two inputs sitting on the cover
reading "Add a title" and "Add a subtitle", in title-sized type, inside a
dashed box, with drag and rotate handles. A customer who deleted their
title still had text on their cover and nothing that would remove it.

**A hint you cannot dismiss is indistinguishable from text you are stuck
with.** And it broke the promise this editor is built on: what you see is
what gets printed. Here it was showing something the book would not have —
the same contract violation as printing something the customer never saw,
just pointing the other way.

The rule is now stated once, in `coverHasTitle`, and it is deliberately the
renderers' rule rather than a new one: a cover with no title text and no
subtitle text has no title block. There is no `title_hidden` flag, because
a flag would be a fourth opinion to keep in step with three existing ones,
and the first time they disagreed a customer would get a cover that printed
differently from the screen. Deleting the text IS removing the title. The
block stays while it is SELECTED regardless, or it would vanish from under
the caret as the last character went; clicking away empty is what removes
it. An empty subtitle line follows the same rule one level down.

**The settings panel** exists because that made removal possible but not
reachable — and because the only way to change the title's font was to know
that you select the block first. It holds the cover's text (with the switch
that turns it off), font, size, title colour and cover colour, on the cover
screen only: a panel of cover settings offered while looking at page 7
would be a button that does nothing, which is the rule the rest of that
toolbar already follows (A85). Turning the switch off keeps what was typed
in memory for the session, so a mis-tap is recoverable, and does not
persist it, so a reload does not resurrect something the customer removed.

**Two more of the same family, found on the way.**

`Remove` on the title block's toolbar cleared `cover.photo_id`. So on a
cover with no photo it was a button you could press that did nothing, and
on a cover with one it deleted the photo when the thing selected was the
text. There are now two buttons that each say which they mean, and the
photo one appears only when there is a photo. `Title colour` had the same
shape — offered on a cover with no title — and is now shown only when there
is text to colour.

And the layout popover still attached its dismiss listeners in a
`setTimeout(..., 0)`: the second copy of A101's race, which survived that
fix because only the swatch popover was looked at. Both now go through
`positionPop`, which attaches synchronously, and `closeLayoutPop` removes
every popover rather than the first. `checks/bookcfg.js` opens the settings
panel and dismisses it IN THE SAME TASK, which a deferred attach cannot
survive.

Restoring a removed title used `S.bookType`, which is only set while a book
is being made — so after a reload a love story got "Our memories" put back
on it. It reads `S.book.book_type` now, which is the server's answer and
survives. The sticker tray opened on the wrong pack for the same reason and
is fixed with it.

`checks/bookcfg.js` earns its place: with the old rendering restored it
fails reporting exactly what was complained about — `["Add a title", "Add a
subtitle"]` left on a cover the customer had cleared.

**A104, continued — the first cut broke six checks, and they were right.**
Hiding the empty block removed the only way to ADD a title by hand: you
could reach it through the settings panel and nowhere else. `+ Title` is
the answer — the cover's version of `+ Text`, offered for exactly as long
as there is no title. It opens an EMPTY field rather than a prefilled one,
since putting words there that nobody asked for is the complaint this
whole change came from, and an empty block that is clicked away without
typing removes itself, so pressing it by accident costs nothing.

Two things fell out of fixing those checks.

`covertitle.js` is **A89 attempting this same repair already**: it made the
placeholder look like a field — an instruction rather than a noun, in a
dashed outline — on the reasoning that "an instruction plus a field outline
cannot be mistaken for content". A customer reported the same problem again
in plainer words. Worth keeping: when a hint has to be *styled* out of
being mistaken for content, that is evidence the hint should not be there,
and the second attempt should not be a better style.

And typing a title did not make `Title colour` appear, nor did deleting one
make `+ Title` come back, until something else happened to redraw the
canvas — editing in place deliberately does not. Both toolbar buttons now
follow the text as it is typed.

**A104, finally — no text at all until somebody types it.** The prefill
itself is gone. Picking an occasion used to put "Our love story" or "Our
travels" on the cover, and the customer's own words for what was wrong with
that were the clearest statement of it: make it by default no text unless
the user types it in the editor.

What an occasion brings now is COLOUR and nothing else — the background and
the title colour, so that a title added later reads against that background
from its first character. "memory" still applies nothing at all, which is
what continues to separate it from the themed occasions now that none of
them carry words.

The switch in the settings panel follows the same rule. Turning it on
restores what the customer typed earlier in the session if there is
anything to restore, and otherwise opens an EMPTY block with the caret in
it — inventing words there would be the original complaint coming back
through a different control.

The four `type.title.*` strings went with it, in all five languages. A
string nothing reads is a trap: the next person to find `type.title.love`
will assume something uses it.

**The whole arc is worth reading as one thing.** A89 saw text on the cover
that looked like content and made it look more like a field. A104's first
cut stopped drawing it. A104's second cut added `+ Title`, because not
drawing it had removed the only way to put one there by hand. And this,
the third, removed the reason any of it was on screen in the first place.
The fix that held was the one that deleted the feature rather than the one
that improved it — and the signal was there from the start, in a customer
saying twice that they could not get rid of something we had decided they
wanted.

**A105 — the front page now says you already have a book.** Asked plainly:
if we know the customer has an unfinished album, why not say so when they
arrive?

The editor had a resume card from early on, but on its own start screen —
you only saw it after deciding to open the editor. Somebody who left a book
half-finished and came back to the site was met by "Create your book" and
nothing else, the same page a first-time visitor sees. Their book was safe
in this browser's localStorage and the site gave them no reason to believe
it.

The banner sits above the header, before anything written for a first-time
visitor, and it is careful about three things:

* **It asks the server before promising anything.** Books expire and the
  credentials outlive them, so a banner offering to continue something that
  is gone would be worse than no banner. A clean 404 also clears the dead
  credentials, exactly as the editor's own resume card does — and ONLY a
  404 does, because being offline is not evidence that a book is gone.
* **It only offers to continue what can still be edited.** Past `draft` the
  book is locked behind an order, and "continue where you left off" would
  lead to a screen that no longer takes changes.
* **It says where the book is.** Nothing here is an account: the book lives
  in this browser, and the same person on their phone will find nothing.
  Better to say so in the banner than to let them discover it.

It is progressive enhancement — `hidden` in the markup, shown by a script —
so a browser with no book, and a browser with no JavaScript, see the page
exactly as before.

**This only works because the site and the editor are one origin**, which
they are in production: Caddy serves the site at `/`, the editor at
`/editor` and the API under the same hostname. Dev did not match — the dev
server never set `SITE_DIR`, so `/` was a 404 and the site had to be served
separately on another port, which made them two origins. That was a
difference that could hide this feature working or not working, so the dev
server now serves the site at `/` as production does.

**Found on the way:** the editor's Russian resume card read "Книга на
{pages} страниц" for every book. Russian numerals govern the noun's case,
and the page counts are 32, 64, 96 and 192 — so that wording is right for
96 and wrong for the other three. Both it and the new banner use "стр.",
which does not decline and is what a Russian book's own front matter uses.

**A105, continued — and the order you already placed.** The same question
applied to the other thing we know: a customer with an order in flight was
also met by "Create your book".

The banner is two rows now, each shown only when it has something true to
say, and both can be true at once — an order on its way and a new book
already started.

**The order row does not repeat the status in words.** The order screen
already says that, in five languages, and a second copy of that vocabulary
in five static HTML files is two places that have to agree about what
`sent_to_production` is called. The status is fetched to decide whether
there is anything left to track; the screen built for it says the rest.

**It is asked for once per session, not once per page load.** The status
endpoint takes the customer's phone in the query string — the same reason
A100 put the receipt's phone in a form body instead — and a phone number
written into the access log on every visit to the front page is a real cost
for an answer that changes a few times a week. One request per session,
cached in `mb-order`, and the banner renders from that on later page loads.

**A finished order gets no banner.** `delivered`, `cancelled` and
`refunded` end it. A banner that goes on asking after the book has arrived
is a nag, not a service — and without the fetch there would be no way to
know the difference.

**A 404 here deletes nothing**, unlike the book row above it. The status
endpoint answers 404 for a wrong phone exactly as it does for an unknown
reference (A77), so a 404 is not proof the order is gone — and the
reference is the customer's only handle on money they have already paid. A
book that expired is genuinely gone; an order is a record.

`#order` now opens the order screen directly, because without it the
front-page offer to track an order landed on the start screen, where the
customer had to find "View order" and press it again — two clicks for one
intention, the second of them a search.

**What the stub cannot prove, `e2e` does.** `resumebanner.js` fakes the
status to test which ones are worth a banner; that a REAL checkout leaves
`mb-order` in the shape the site's script reads is a seam a stub cannot
reach, so the assertion lives in `e2e`, which buys a whole order anyway.

**And the check caught itself twice.** `bannerText` read the banner's text
whether or not it was on screen, which would have let every assertion about
the wording pass against a banner nobody could see. Fixed once — and then
the second row reintroduced it in a subtler form, because reading the
CONTAINER dragged the hidden row's words in with the visible one. It now
reads row by row, skipping the hidden ones.

**A106 — the contact details are real.** The five site footers carried
`+998XXXXXXXXX`, `hello@example.com` and two `t.me/XXXXXXXXX` links since
the site was written. They are now the founder's own: the phone, a Gmail
address, `@Eurohand1` on Telegram and `@rs_pixeluz` on Instagram. The
launch checklist's contacts item turns green, and it is the first blocking
item on that list to do so.

The handles are shown rather than the bare words "Telegram" and
"Instagram". Somebody who wants to message on Telegram usually searches the
username rather than following a link, and "Telegram" on its own gives them
nothing to search for.

**The check changed shape with the values.** While the details were
placeholders the only question worth asking was whether they were still
placeholders. Now that they are real, the failure that actually happens is
drift: a number changed on the English page and nowhere else leaves four
languages handing out a dead one — and unlike a placeholder, a stale real
number looks entirely convincing. `check_site_contacts` now also requires
all five pages to agree on their `tel:`, `mailto:`, `t.me/` and Instagram
targets, and only on those: the pages are different languages with
different copy and different relative links, and a check that demanded more
would fire on every ordinary edit. Both directions are tested, per A81.

**Two things worth the founder's attention, neither of them ours to
decide.** `merelyriki@gmail.com` is a personal address on a free provider
while the business owns `rspixel.uz`; a forwarding alias like
`hello@rspixel.uz` costs nothing and reads as a company rather than a
person. And `@Eurohand1` carries no relation to the RS Pixel name, so a
customer who finds it has no way to tell they have reached the right place.
Both were used exactly as given.

**P0-2 — "Track an order" did not track an order.** The site's Support
column linked to `editor/`, so a customer chasing an order they had already
paid for arrived at "What kind of book are you making?", with the way to
their order a scroll below the fold on a screen that reads as the wrong
page entirely. After payment, that is the moment a calm customer stops
being one.

**The lookup was not missing.** It existed, it worked, it asked for a
reference and a phone and it showed the order — and nothing linked to it.
That is the part worth keeping: a feature nobody can reach is
indistinguishable from a feature nobody built, and it is the more expensive
of the two, because from the inside it looks finished. The report offered
"build a real lookup page, or remove the link" and the answer was neither:
the page was there, the routing was not.

`#track` opens it directly and every language's Support column points at
it. `#order` — the front-page banner's target (A105) — now falls back to
the same lookup when there is nothing stored, which is not an edge case but
the ordinary one: the customer who ordered on their phone and is looking on
a laptop has no `mb-order` there, and the lookup is exactly what they need.
Sending them to the book picker would have been this same bug in a second
place.

Both are routed through one `applyHashRoute`, and `hashchange` is listened
to as well as read at boot, so the back button works.

**What the check asserts is the landing, not the link.** `trackorder.js`
follows the Support link from all five pages and requires a reference-and-
phone form on screen — landing in the editor at all is what the bug did.
It also submits an unknown reference, so the form is proved to ask the
server rather than merely to exist. And `e2e`, which buys a real order
anyway, clears `mb-order` and finds that order again from the reference and
the phone alone: the other-device path, end to end.

**P0-3 — the site sold a feature that does not exist.** The FAQ answered
"Some of my photos are blurry. Can you fix them?" with "Yes — we use AI
enhancement to improve blurry or muddy photos before printing", in all five
languages. Nothing in this system so much as sharpens a pixel. A customer
reads that, uploads their blurry photos, receives a blurry book and asks
for a free reprint — and is right to.

The replacement describes what the product really does: the editor
classifies every placement's resolution at the size it is used and at its
zoom (A68), the tray badges it on upload, and the preview names the pages
that will print soft before the customer confirms (A79). That is a better
answer as well as a true one — it prevents the disappointment rather than
promising a rescue from it.

**Two words were dropped from the founder's draft.** It offered "too small
or too low-quality to print sharply", and we do not measure quality. A
large, out-of-focus photograph passes every check we have, so a customer
reading "you'll see a warning" about blurry photos would be owed one we
would never give. The copy says resolution, and adds the sentence that
closes the expectation the old question opened: we do not sharpen or
retouch, and what is in the preview is what gets printed. That is the same
promise the whole product is built on.

**The check that guards it caught itself first.** `check_unshipped_claims`
went red immediately — on the honest replacement, because its first draft
matched the word "retouch" and the new copy says we do NOT retouch. A
pattern match cannot read a negation. So the rule is that every term in
that pattern must be wrong in ANY sentence: `AI`, `нейросет`, `sunʼiy
intellekt` and their siblings qualify, and `retouch` does not. A checklist
that goes red at a true sentence is one people learn to skip, and that is
worse than not having it.

The terms are listed per language because the claim was translated. A check
that only knew the English one would have found a fifth of the problem —
which is the same lesson A104's i18n work taught from the other direction.

**Delete the check on the day the feature ships**, and not before.

**P1-1 — two promises the business could not keep as written.**

**"What you see in the editor is what we print."** True of the layout and
impossible for the colour. A screen emits light and paper reflects it, so
deep blues, bright greens and neon tones shift no matter what anyone does,
and no two phone screens agree with each other, let alone with a press.
Every photo-print business receives "the colours are different"; that
sentence made it our fault by contract. The rewrite promises the half we
control — same pages, same order, same text — and names the reason the
other half moves.

**We had just made it worse.** P0-3, an hour earlier, ended its honest
replacement with "what you see in the preview is what we print". In context
that meant "we do not alter your photos", and read on its own it was
exactly this claim. It now says the photos are printed as they were
uploaded, which is what it was always for. Worth remembering: a sentence
that is true about one thing is not safe to reuse as a slogan about
everything.

**"Printing defect? We reprint it free."** The right promise with no
boundary. A customer whose own 600px photo printed soft calls that a
printing defect, and until now there was nothing to point at. The policy
names what is covered — binding, banding, misregistration, trim, transit
damage — and what is not: low-resolution photos the editor warned about
before the order, design choices the customer made, and screen-versus-print
colour. Fourteen days from delivery, with photographs of the whole book and
of the fault.

**It lives under the promise, not on a page of its own.** A boundary a
customer finds only after the argument has started is not a boundary. Every
place that offers a free reprint links to it — the perk, the FAQ answer and
the footer on all five pages, and the editor's start screen, which makes
the same promise and now carries the same link.

At current margins one avoidable reprint erases roughly twenty sales, so
this is a financial control rather than legalese, and `checks/promises.js`
treats it as one: it fails if the policy loses either half of its list, if
any language drops below three links to it, or if the old unqualified
sentence returns in any of the five languages it was translated into.

**P1-3 — the reviews section, built but still empty.** The copy standing
there — "Verified reviews from our first customers will appear here — the
pilot books are being printed right now. We never publish invented quotes"
— is kept exactly as it was. It turns an empty section into a statement,
and it is true.

What was missing was the component behind it. There is now one slot that
takes a name, a photograph and what the book was about, and it lives in a
single list in `assets/reviews.js` that fills all five language pages at
once. Adding a review is one entry plus one file in `assets/reviews/`.

**The words are not translated.** A review appears in the language it was
written in, on every page, with `lang` set so a screen reader says it
correctly. Rewriting a customer's sentence into four other languages is
putting words in their mouth — a smaller version of inventing the quote,
and the person who left it cannot check what we made them say.

**Three or none.** One card in a row built for three does not read as "our
first customer"; it reads as "one person has ever bought this". Below three
the honest note stays. `MIN_TO_PUBLISH` is one line and says so.

**A half-built entry is dropped, loudly.** A card with a name and no book is
indistinguishable from one somebody invented in a hurry, so an entry
missing any required field is skipped and the console says how many were.

**And the cheapest way to fake this now fails.** `check_review_honesty`
blocks the release if a stock-avatar service appears anywhere on the site —
pravatar, ui-avatars, dicebear, gravatar, randomuser, placeholder,
unsplash-random — or if a review photograph is hosted somewhere we do not
control, since a remote picture can change or vanish after it has been
vouched for. It cannot check whether a QUOTE is real; nothing can. What it
can do is make the easy lie expensive.

**There is no fixture review in the repository.** `checks/reviewslot.js`
serves its own through a route intercept, because a fabricated review
committed as test data is a fabricated review, and it would be the first
thing a reader of this repository found.

**P1-4 — the link preview is the advertisement.** The site had no Open
Graph tags at all, so every link pasted into Telegram or Instagram rendered
as a bare grey rectangle. The money behind the link is spent either way.

All five pages now carry title, description, image, url, locale, the image
dimensions, and `twitter:card: summary_large_image`. Three details are
where this usually goes wrong:

* **The image is absolute.** A preview is fetched by somebody else's
  server, from a link with no page to resolve a relative path against. A
  relative `og:image` looks right in a browser and fails everywhere it
  matters, so both the release check and the browser check test for it by
  name.
* **`og:url` and `og:locale` are per page.** Copying the block between
  languages and forgetting these makes every share point at the English
  page. `checks/ogtags.js` requires five distinct values of each rather
  than merely requiring them to exist.
* **The image is fetched, not just declared.** The tag can be perfect and
  the file absent; a preview server gives up quietly. The check pulls the
  bytes, confirms the PNG header and reads 1200x630 out of it.

**The image is an illustration and says so.** The brief asked for a
photograph of a real book, and no book has been printed — that is still an
open item on this very checklist. A rendered mock-up passed off as a
product photograph would be the reviews problem in picture form, so
`assets/og-card.svg` draws the product as a drawing: our own artwork, our
own wordmark, nothing pretending to be a thing we have not made. It is
re-rendered with `node browser-tests/tools/render-og.js` and must be
replaced with a real photograph the day there is one.

**One card, not five.** The only text on it is the brand name and the
domain, so there is nothing to translate and nothing to keep in step; the
language lives in `og:title` and `og:description`, which are copied from
the page's own `<title>` and description rather than written again.

**This check warns rather than blocks.** A grey preview card is lost reach,
not a broken product, and it must not sit on the STOP list beside selling
something that does not exist.

**What cannot be checked from here:** how Telegram actually renders it.
Telegram caches previews aggressively per URL, so the render has to be
tried against the live site — and if it is wrong, the cache has to be
cleared through @WebpageBot before the next attempt shows anything
different.

**P1-5 — the best thing the editor does was not in the copy.** The
auto-layout card said "one click fills your pages automatically", which is
what a grid does. What the software actually does is sort by EXIF
`taken_at` and rebuild the trip in the order it happened — business rule
R2, `app/domain/ordering.py`, the rule that docstring calls the most
important in the product. Five languages advertised the grid.

The card is now named for the ordering and says it in the first clause, in
all five languages, and the claim is repeated in the two other places the
page describes the feature: the how-it-works step and the "do I need
design skills?" answer.

**The claim was verified against the shipped path before it was made,**
not against the domain function. A true rule that nothing calls is still a
false advertisement, so the whole chain was read end to end: the browser
reads the EXIF date off the file header *before* downscaling
(`editor/js/upload.js`, because the downscaled upload carries no EXIF),
sends it on complete (`api.js` → `taken_at_exif`), the server also
extracts it during ingest and keeps whichever it has, `placement.py` feeds
`auto_place_order`, and the editor's button posts to that endpoint. Each
link is covered by a test, and `tests/api/test_placement.py::
test_chronological_order_full_bleed` covers the whole of it by seeding
photos in reverse chronological order and asserting `taken_at` wins.

**`check_order_claim` guards the copy, not the behaviour.** The behaviour
already has tests; what had nothing was the five-way copy. This task
demonstrated the failure mode while fixing it — the first pass edited the
English page in three places and each translation in two, and the
how-it-works step drifted out of step in four languages without a symptom.
The check anchors to the `<h3>` and the paragraph under it, matches the
card under either its old or new name, and asks only that the ordering be
mentioned. Rephrase freely; keep the claim.

**The check warns rather than blocks,** for the same reason P1-4 does:
under-selling a real feature costs sales, not customers.

**What is still worth doing:** the ordering is invisible in the editor
itself. A customer who never reads the marketing page presses the button
and sees photos appear; nothing tells them the order was chosen rather
than arbitrary. A line in the editor at the moment auto-layout runs would
put the claim where it is actually experienced.

**P1-5b — the editor says what auto-fill did.** The marketing page now
sells the chronological ordering, but the editor — the only place the
feature is actually experienced — reported two numbers: "3 placed. 0 did
not fit." A customer who never read the marketing page pressed the button,
saw photos appear, and had no way to learn the order was chosen rather
than arbitrary.

**The toast could not simply repeat the marketing line, because it is not
always true.** Auto-place orders by EXIF `taken_at`; photos without one
are placed in upload order (R2). Telegram and WhatsApp strip EXIF, and
screenshots never had any, so *a book assembled from forwarded photos is
in upload order* — and that is not a rare case here, it may well be the
common one. "In the order you took them" would then be a lie told at the
one moment the customer could still fix the order by hand.

So the endpoint now also returns `dated_count` — how many of the PLACED
photos carried a date — and the editor picks one of three sentences:

* all dated — "in the order you took them";
* none dated — "in the order you added them — these photos carry no date",
  which also tells the customer *why*, and so what to do about it;
* some — "{placed} placed — {dated} by the date they were taken, the
  undated ones after".

A fourth case, nothing placed at all, used to read "0 placed. 0 did not
fit."; it now says there is nothing to place yet.

**`dated_count` counts the placed photos, not the uploaded ones,** so a
16-page book made from 20 dated photos reports 16 of 16 rather than 20 of
16. It is counted from the placed ids rather than inferred from the sort
order, so it stays correct if R2's tie-breaking is ever revisited.

**An absent `dated_count` is not read as "no dates".** A browser holding
cached JS against an older server would otherwise tell every customer
their photos had no dates; the editor falls back to the bare count
instead. This is the A61 trap from the other side, and the cache stamps
for `app.js` and `i18n.js` were bumped together for the same reason — new
code calling `t('autofill.dated')` against a cached `i18n.js` that has
never heard of the key renders the raw key.

**`checks/ordertoast.js` strips the EXIF out of the jpg fixtures itself,**
which is exactly what a messenger does to a photo in transit, and asserts
the undated book does NOT claim the taken order. The expected sentences
are written out in the check rather than read back from `i18n.js`: a check
that derives its expectation from the thing it is checking passes just as
happily when the copy is wrong. The Russian case is a book made in Russian
from the start, and asserts the absence of «снимали» as well as the
presence of «добавили» — a fallback to the English string would otherwise
pass a "is it translated?" test that only looked for Cyrillic.

**Found while testing, not fixed:** the language selector lives only in
`#screen-start`. Once the editor is open there is no way to change
language, so a customer who picks the wrong one has to clear the book and
start again. That is a pre-existing gap, not something this change
introduced.

**A84 caught this change, and the catch was correct.** The first Russian
wording used «съёмки». The editor's display face is a subset built from
the strings we actually ship, and no string had ever contained a hard
sign, so `Ъ/ъ` is not in it — the word would have rendered with one
letter in a fallback typeface. The copy now says «снимка», which means
the same thing in letters the subset has.

The repo's intended fix for a genuinely new character is to re-run
`scripts/subset_web_font.py`, but that takes the upstream TTFs and only
the subset `.woff2` files are in the tree, so rewording was the fix
available here. **Any future Russian string containing `ъ` will fail this
test for the same reason** — and it is a common enough letter
(«объектив», «подъезд») that the subset should be rebuilt from upstream
EB Garamond the next time the fonts are touched, rather than each string
being worded around it.

**A107 — the language can be changed from inside the editor.** It lived
only on the start screen, which put the choice before the customer had
seen anything, and once the editor was open there was no way back to it:
picking the wrong language and noticing two uploads later meant
abandoning the book. The cost of a mis-tap was the whole session.

The editor bar now carries a second selector. `buildLangSelects` builds
every `.lang-select` on the page and mirrors the choice across them,
because two selects disagreeing about the current language is its own
small bug — and the one on the start screen is what the customer sees
again the moment they press Back.

**The start-screen select keeps its id.** `homecheck` and `pricegate`
both drive `#lang-select` by id; the new one is `#ed-lang-select` and
shares only the class, so those checks still address the control they
meant. In the editor bar the `.spacer` does the pushing, so the
`margin-left: auto` that positions the start-screen one is turned off
there rather than fighting it for the right edge.

**Switching closes the settings panel,** which is built with `t()` at open
time and would otherwise sit there in the previous language.

**What `checks/editorlang.js` actually asserts** is not that a select
exists. It switches language *three uploads into a book* and checks the
photos are still there and the editor is still the active screen — a
language switch that cleared the book would be worse than no switch at
all. It also checks the bar still fits a phone now that it carries one
more control, and that the start screen agrees afterwards.

That last one is checked twice on purpose. A fresh visit agreeing proves
only that `setLang` wrote to localStorage; the same-session Back is what
covers the mirroring. Removing the one line that mirrors them was
confirmed to turn that assertion red, and only that one.

**P1-6 — delivery coverage is stated.** We deliver anywhere in Uzbekistan
and the site never said so. "Do you even reach me?" is the first question
a buyer in Namangan or Nukus asks, and at 11pm there is nobody to ask it
to; an unanswered one is a closed tab, and nobody ever hears that they
tried. It is the cheapest sentence on the page to have missing.

It is now in two places on all five pages, because they serve different
people: the **FAQ**, where somebody looking for it goes to look, and the
**footer**, where somebody who never thought to ask still passes it. The
FAQ entry sits immediately before "how long until it arrives" — coverage
is the question that comes first, and an arrival time is meaningless to
someone who does not yet believe we ship to them at all.

**The Karakalpak page names Qaraqalpaqstan explicitly,** and so does the
English one. Its readers are furthest from the print shop and likeliest
to assume the answer is no, which is why the brief singled it out; a
general "anywhere in Uzbekistan" is weaker there than being named.

**The claim was checked against the order form before it was made.**
Checkout takes a free-text address — a 500-character textarea, no region
dropdown, no Tashkent-only restriction — so there is nothing in the
system that would stop a Nukus order. Had the form constrained the
region, the honest fix would have been the form, not the copy.

**`check_delivery_claim` asserts the two places separately**, not that
the words appear on the page. The footer is the half likelier to be
forgotten: it is the same line in five files and nobody reads it on
purpose.

**`checks/delivery.js` expands the entry before reading the answer.** A
`<details>` that opens onto an empty paragraph reads as an answer in the
source and as silence on the page, and no source-level check can tell the
difference — confirmed by emptying it in flight and watching only that
assertion go red. It runs at 390px, because that is what this is read on.

**And now the checkout screen too,** which is the moment the doubt
actually bites: the customer is typing an address in Nukus and wondering
whether anyone comes that far. `co.deliveryHint` sits inside the address
label rather than beside it, so it hugs the field it answers for — as a
sibling the `.co-form` 16px gap would orphan it from the box.

**That assertion rides along in `checks/receipt.js`** rather than getting
its own check. Reaching the checkout screen costs a 32-photo upload and a
preview render, `receipt` is the only default-run check already standing
there, and a second one paying that cost again to read one line would add
minutes and find nothing new. It asserts the line is visible, is not the
raw key, and sits *below* the address field — position is the point.

Translation is covered without driving the flow five times:
`test_i18n_complete` requires the key in every language, and
`checks/editorlang.js` already proves `applyStatic` retranslates the
chrome when the language changes.

**P2-1 — the positioning was travel-locked.** "Your trip. Your photos.
Your book." frames the whole page as a travel book, and the next campaign
is New Year gifting: family, year-in-review, children. A visitor who
clicks a New Year ad and lands on "Your trip" has been told in the first
second that they are in the wrong place.

**Option 1, as recommended: the travel page is untouched.** It is good
*because* it is specific, and broadening it would have traded a page that
converts for a page that offends nobody. `/new-year` and `/family` now
exist in all five languages with matched headline, matched samples and
the same CTA, and a test asserts the main page still leads with "Your
trip." — the option not taken, said out loud.

**Ten pages are generated, not written.** `scripts/build_landings.py`
holds the copy and one template; `tests/test_landing_pages.py` fails if
the committed HTML and the script have drifted. Written by hand these
would be ten more files for every future copy fix to reach — P1-1, P1-5
and P1-6 each had to touch five, and this would have made it fifteen.
Nothing about the shipped site changes: it is still static HTML with no
build step in front of it. Regenerate with
`cd backend && .venv/bin/python scripts/build_landings.py`.

**The campaign has to survive a language change.** Sending a Russian
speaker from the New Year page to the Russian *home* page is the P2-1
mismatch again, one level down. Both language menus link to the same slug,
and `assets/lang.js` takes a `data-page` so the automatic
device-language redirect carries the campaign too. Deleting that one
addition was confirmed to drop a Russian-speaking visitor on `/ru/`, and
to turn exactly one assertion red.

**`/new-year` resolves without its trailing slash** — 307 to `/new-year/`
— because that is the form that goes in an ad, and a 404 there wastes the
whole spend. Checked in the browser rather than assumed from the mount
configuration.

**All ten pages joined `SITE_PAGES`,** so the contacts, unshipped-claim,
review-honesty and link-preview guards cover them. These are the pages a
stranger sees *first*, so a link preview matters more here than anywhere
else on the site. `check_delivery_claim` now asks every page for the
footer line and asks for the FAQ line only where there is an FAQ, so a
landing page is not failed for a section it deliberately does not have.

**The samples are drawings, badged "Sample", and there are no `<img>`
tags on these pages at all** — the same rule as P1-3 and P1-4. No book
has been printed, so there is no photograph of one to show.

**The one promise on these pages that is not a fact** is the New Year
cutoff. It is derived from the site's own "about 30 days from payment to
delivery" with roughly a week of slack, lives in a single
`NEW_YEAR_ORDER_BY` table, and **must be checked against the printer's
December load before any money is spent pointing ads at these pages** — a
December queue is not a November queue. The page also states what happens
if you order later, because a deadline with no consequence attached reads
as a suggestion; a test asserts both, and asserts the family page carries
no seasonal date at all, since it runs all year and a December date on it
would go stale in January with nobody noticing.

**P2-3 — page weight, and a premise that did not hold.** The brief asked
for WebP with fallbacks, lazy-loading below the fold and hard-compressed
hero imagery, on the grounds that a photography site is image-heavy.
Measured first, and it is not: **this site ships no raster images at
all.** Every illustration on every page is inline SVG, the type is a
system stack with no web font, and there is not one `<img>` element in the
markup. There was nothing to convert to WebP and nothing below the fold to
defer.

What the site actually costs, gzipped as production serves it: the
heaviest page (Russian home) is 8.6 KB of HTML, 4.7 KB of CSS and 5.5 KB
of JavaScript — **about 19 KB fully loaded**. The campaign landing pages
are roughly 9 KB. First contentful paint on a throttled slow-4G cell,
measured against the dev server which does *not* compress, is far inside
the three-second target.

**`assets/og.png` is 230 KB and is deliberately left alone.** It is
fetched by Telegram's and Instagram's preview crawlers and never by the
page, and several preview fetchers do not render WebP — "optimising" it
would cost the link previews P1-4 exists to produce, to save bytes no
visitor ever downloads. This is the one place where doing what the brief
literally asked for would have made the product worse.

**So the work was a budget rather than a clean-up.** `check_page_weight`
holds every page, with every local asset it pulls in, under 120 KB
uncompressed (the heaviest is currently 63 KB) and any single raster file
under 200 KB. It counts raw bytes rather than gzipped on purpose: Caddy
compresses in production, so the number is the pessimistic one, and a
budget that cannot be met by reaching for a better compressor is the one
worth having. Written now, while nothing is slow, because the first real
photograph — a printed book for the OG card, a customer's review portrait
— is exactly what turns a 19 KB page into a 2 MB one, and a budget
written after that is a post-mortem.

**`check_image_discipline` found a real defect on its first run.**
`assets/reviews.js` — the one place an `<img>` actually arrives — set
`loading="lazy"` but no dimensions, so every published review portrait
would have shifted the quote under the reader's thumb as it landed. It now
sets `decoding="async"` and an explicit 44x44, the size the stylesheet
draws it, as attributes rather than CSS alone: the browser needs the ratio
*before* it has the file. That bug would only have appeared the day real
reviews were published, long after the code was written.

**A measurement that lies is worse than none.** The first version of the
timing harness read `first-contentful-paint` immediately and counted
response bodies in an async handler; it reported `null` paints and gave
the same page two different byte counts. `checks/pageweight.js` waits for
the paint entry through a `PerformanceObserver` and takes bytes from CDP
`loadingFinished`, and it treats a missing FCP as a failure rather than a
pass — a performance check that goes green on a blank page is worse than
not measuring.

**P2-4 — the privacy policy, the terms, and the EXIF question.**

**The engineering half first, because it is the one with live harm in it.**
A phone writes the coordinates of where a photo was taken into the file,
so a family photograph taken at home carries the home address.
`image_processing` already said in a comment that derivatives carry no
metadata. A comment is not a test, and this session has repeatedly found
code that says untrue things about itself, so it was checked against a
GPS-tagged fixture instead: the display JPEG, the thumbnail, the composed
print page and the preview page all come out with no EXIF tags, no GPS
IFD and no APP1 segment at all. **The claim was true.**

`tests/test_exif_privacy.py` now holds it true. The way it would break is
somebody adding `exif=` to a `save()` call to fix a rotation bug — a
reasonable-looking one-liner that silently reattaches the coordinates to
every page of every book. That exact change was made temporarily and
turned three assertions red, including a search of the raw bytes for the
packed rationals a GPS IFD would contain, which catches metadata surviving
somewhere a tag parser does not look.

The original upload keeps its EXIF deliberately: it is the customer's own
file, `taken_at` is read off it for R2, and it is never sent anywhere. The
print files that go to the printer — a third party, over Telegram — are
composed canvases, and they are clean.

**Every fact in the policy was read out of the code, not drafted from a
template.** 30 days is `books.DRAFT_RETENTION`, and because `books.py`
resets `expires_at` on every mutation the document says "30 days after you
last opened it" rather than "after you create it" — a difference that
matters to somebody who has been working on a book for a month. Expiry
really deletes the files, because `lifecycle.expire_drafts` collects the
original, display, thumbnail and preview keys and removes them.
`test_policy_pages.py` ties the number in the document to the constant:
change `DRAFT_RETENTION` and the policy becomes false, in five languages
at once, and the test says so.

**Where the honest answer is not the tidy one:** a book that reached
`locked` or `ordered` is never expired, so order files are kept
indefinitely and removed only when somebody asks. The document says
exactly that rather than naming a retention period nothing implements.
**This is a real gap worth closing** — an acquirer or a regulator will
generally want a stated period, and "until you ask" is a weaker answer
than "12 months, then deleted". Implementing that is outstanding work, not
something the wording papers over.

**A script-mixing bug, found and then guarded.** The Karakalpak terms
contained `máselениń` — Cyrillic е, н and и pasted into a Latin word. It
renders as a word nobody can search for and no spell-check would see. The
translation-hygiene tests now scan the document body of every Latin-script
page for Cyrillic, and the Cyrillic pages for the opposite. They scan the
document rather than the whole page on purpose: the language menu carries
«Русский» and «Ўзбекча» on every page by design, and a scan over the whole
page flags all five of them.

**`check_delivery_claim` grew a third case.** It asks for the footer line
only where the footer has a marketing column, because a policy page
carries a plain document footer — pushing delivery copy into the privacy
policy would be noise in the one document a customer reads when they have
stopped trusting you.

**`checks/policies.js` follows the links rather than building them.** It
reads the privacy and terms hrefs out of the footer of all fifteen selling
pages and fetches them, because a relative href that resolves correctly
from `/index.html` and wrongly from `/ru/new-year/` is exactly the bug a
hand-written URL in the check would hide. A privacy link that 404s is the
P0-2 failure on the page where it costs the most.

**Change 3 — funnel instrumentation.** An append-only `funnel_events`
table, a closed event vocabulary, server-side emission everywhere the
server can see the step for itself, and a JSON report behind the admin
token. The purpose is cost of acquisition per channel, so the design is
driven by three ways instrumentation is worse than useless.

**1. It must never break the thing it measures.** The obvious
implementation — insert into the caller's session — is wrong, and wrong in
the normal case rather than an exotic one: a once-only event emitted twice
raises a unique violation, which aborts the enclosing transaction, and the
customer's checkout fails because we tried to count it. The other obvious
implementation, a separate session outside the caller's transaction, is
wrong the other way: the row would survive a rollback, so a book whose
creation failed would still report `book_started`.

So every write runs in a **SAVEPOINT** nested in the caller's transaction.
A failure unwinds the savepoint alone; a caller rollback takes the event
with it, which is correct — the step never happened. A test commits after
a deliberately duplicated event specifically to prove the transaction is
still usable.

**2. It must not inflate.** A customer who refreshes has not started a
second book, and a funnel that says otherwise makes every rate below it
wrong in the flattering direction. The guard is a **partial unique index**
on `(book_id, event_type)` excluding the four genuinely repeatable events
— not a check-then-insert in Python, which two simultaneous requests both
pass. The report then counts **distinct books** (and distinct sessions for
the two steps that happen before a book exists), never rows, so even a
duplicate that somehow landed could not move a number.

**3. Attribution has to reach the money.** `utm_*` is captured on first
landing into a first-party cookie and **first landing wins** — overwriting
it would record a customer who saw a New Year advert, left, and came back
a week later by typing the address as direct traffic, and the campaign
that actually paid for them would show a cost per acquisition with the
acquisition missing. Payments arrive on a webhook and abandonment is found
by a nightly job, neither of which carries a cookie, so both take their
session and campaign off the **book's own earliest event**. Without that
one join, every sale reads as direct traffic and the entire point of the
change is lost.

**Where the specification and the product disagreed, and what I did.**
The brief says only `site_visit` and `editor_opened` come from the client.
`checkout_opened` cannot: moving to the checkout screen is a screen swap
in the editor with no server call behind it, so the server never learns of
it. Rather than drop the step — it is the one where the drop-off is most
worth knowing — the client may report it through one narrow door, and the
door is what makes that safe: a fixed allowlist that cannot name a money
event, the book's edit token required, and the once-per-book index, so a
replay or a forgery cannot move the number. `reminder_clicked` arrives the
same way, off a `?r=3` marker on the reminder link. **The report says in
its own payload which steps are client-reported**, so nobody reads the top
of the funnel as gospel.

**Two bugs my own tests found.** `log.debug(..., event=...)` collides with
structlog's own key for the message and raises `TypeError` — inside the
exception handler whose entire job is to swallow errors, which is the
worst possible place for a throw. And the migration's index predicate is
spelled out while the model builds its own from the enum; a test asserts
the two agree, because a partial index whose predicate drifts stops
guarding the events it was written for and nothing else notices.

**The privacy policy was updated in the same change, not after it.** P2-4
published a document listing what we store, and adding two cookies without
saying so would have made that document false — the specific failure the
policy tests exist to prevent. It now has a section naming both cookies,
what they are for, that neither holds a name, phone or email, that neither
is readable by the page, and that there are no third-party analytics or
advertising trackers at all.

**What is not done:** there is no admin UI, by agreement — a JSON endpoint
is enough for now. `half_designed` and `design_completed` are computed on
every layout save, which is cheap but means a book completed by an
operator action rather than a customer save would not record them.

**Change 2 — Telegram as a recovery channel.** A customer taps "Remind me
in Telegram" in the editor, presses Start in the bot, and their reminders
arrive somewhere they actually read.

**The finding that changes how important this is: email never worked.**
`queue_reminders` required `Book.email`, and **nothing has ever set it** —
the editor has no email capture and never calls `PATCH /books/{id}/email`,
and checkout does not write it back to the book either. The email branch
of the reminder job could not fire for a real customer. Telegram is not a
second recovery channel here; it is the first one.

**The deep-link token is NOT the edit token, and that is the security
design of the whole feature.** A deep link travels through Telegram's
servers, sits in a chat list and gets forwarded. The edit token is the
only thing between a stranger and somebody's family photographs. So a book
gets a second, single-purpose, expiring secret whose only power is to
attach a chat id, and which is spent on use. Leaking it costs the customer
unwanted reminders, not their book. A test asserts the two differ.

**404, not the 401 the brief asked for.** A96 already decided this and the
reasoning holds: a wrong secret must learn nothing a right one would, so
the webhook is never an oracle for whether an RS Pixel bot lives at this
host, and a deployment that never configured it has no extra surface at
all. The requirement — reject anything without the secret — is met, and
more strictly. Flagged rather than silently changed.

**`/start` had to be routed in front of the operator gate.** As it stood,
`/start` required the sender to be a linked operator, so every customer
arriving from a deep link would have been told "you are not linked" —
the flow would have been dead on arrival. Operators redeem codes with
`/link`, customers arrive with `/start <token>`, so the two do not collide.

**A requirement I broke and then fixed.** The first cut sent the
confirmation inline with `telegram.send_to` from the webhook handler,
which the brief explicitly forbids — and the dev run showed exactly why:
the link succeeded, the inline call to a fake bot token threw, and the
whole update came back `{"ignored": "error"}` with the confirmation lost
and no retry. Every customer-facing message now goes through
`OutboxMessage` on the `telegram.reply` topic, with the same
at-least-once delivery and backoff as every other notification, and a
test asserts nothing is sent synchronously.

**De-duplication is a table, not a guess.** Telegram retries until it gets
a 200, and the visible half of that bug is a customer receiving the same
confirmation twice. `telegram_updates` has one column that matters and the
primary key does the work — inside a SAVEPOINT, because the first version
called `session.add` *outside* it and a duplicate poisoned the caller's
transaction, which is the very failure the savepoint pattern exists to
prevent.

**One chat, several books,** modelled as a nullable indexed column rather
than a unique constraint: somebody who makes one book for their mother and
another for a wedding is one chat and two books, and a unique chat id
would make the second link silently fail. `/stop` therefore clears *every*
book for that chat — a partial stop is what gets a bot reported.

**The editor re-asks when the tab regains focus.** The customer taps the
button, leaves for Telegram, presses Start and comes back; without this
they return to a button still offering what they have just done.

**Also fixed on the way:** reminder links were relative (`/editor/abc`),
which is not clickable in an email and is not a link at all in a chat
message. `PUBLIC_BASE_URL` makes them absolute for both channels, and the
Telegram message is sent without a link rather than with a broken one when
it is unset.

**Change 4 — three reminders, and who gets credit for the rescue.**
Day 3 ("your book is waiting — N days left"), day 14 ("still saved"), and
a new day 25 that names the deadline. Day 25 is the last one that can be
acted on: a draft expires 30 days after its last edit, so a reminder any
later arrives after the photographs are gone.

**The number is read off the book, not off the reminder day.** Every edit
pushes `expires_at` out again, so a book edited since its day-3 reminder
genuinely has more than 27 days left. `_days_left` subtracts from
`expires_at`; the spec's "27 days" is what that produces for a book last
touched three days ago, rather than a constant that would quietly become
a small lie a customer can check.

**Empty drafts get nothing,** and the query that decides it is the same
one that fetches the thumbnail — there is no book to come back to, and a
reminder about one is the definition of spam and the fastest way to have
the bot reported.

**The thumbnail is one of their own photographs, presigned at delivery.**
Minting the link when the reminder was queued would hand Telegram an
expired URL after an outage and three backoffs, which is the same mistake
the print-file links already avoid.

**Where Change 4 and Change 3 genuinely conflict, and how it was
resolved.** Change 4 asks that reminder links attribute recovered orders;
Change 3 established that first landing wins. If a reminder click
overwrote the session's campaign, a customer won by a New Year advert and
merely *rescued* by a reminder would be recorded as having come from the
reminder — stripping the campaign that actually paid for them of the
sale, and making its cost per acquisition look worse than it is. That is
precisely the distortion Change 3 exists to prevent.

So: the acquisition stays with first touch, and the rescue is recorded on
its own event. Every reminder link carries
`utm_source=reminder&utm_campaign=draft_recovery`, so it reads honestly in
any analytics; and REMINDER_CLICKED is stamped with that campaign **by
the server**, because a click on our own reminder is a draft recovery by
definition and there is nothing to trust the client about. Recovered
orders are then books with a `reminder_clicked` that later paid — a
question the funnel table already answers. Both requirements are met
without either one corrupting the other.

**The tagging lives in one function** (`reminder_query`), because the
relative fallback used when `PUBLIC_BASE_URL` is unset has to carry the
same tags — a test caught that it did not, and an untagged link is a
recovered order that cannot be told from new traffic, which is the one
thing these tags exist for.

**The seasonal note is appended, never woven in,** so that switching it
off at the end of a campaign cannot leave half a sentence behind. It is
config plus a restart, no code: `REMINDER_SEASONAL_NOTE`, empty outside a
campaign. **Confirm the date against the printer's December load before
switching it on** — the same caveat as P2-1's cutoff, and the same reason.

**Both channels say the same thing.** The body is composed once in
`lifecycle`, including the day's wording, the days actually left and the
seasonal line, so email and Telegram cannot drift into telling the same
customer two different stories. `build_reminder` keeps a fallback for
messages queued by an older build and still sitting in the outbox across
a deploy — delivered rather than dropped.

**CR-003 groundwork — the upload path had no back wall.**

Before building the anonymous contributor upload the CR asks for, a second
opinion on that endpoint's controls turned up something more important:
the door it would be a second copy of was already open. Three findings,
each verified in the code rather than taken on trust:

* **A presigned PUT does not sign the length.** `storage.presign_put`
  signs bucket, key and content type only, so the `size_bytes` a client
  declares when it asks for a URL is decorative — declare 1 MB, upload
  5 GB. The server validated the declaration and nothing validated the
  upload.
* **`ingest_photo` read the whole object into memory before any check.**
  `get_bytes` first, `process_image` second. A 5 GB body against a 1 MB
  declaration did not fail the upload, it killed the worker.
* **No per-book photo cap at all,** so "100 photos per contributor link"
  would have been a fence with nothing behind it.

Fixed on the shared path, which is what both doors use: ingest now asks
storage how big the object actually is (`head_size`) BEFORE reading it,
refuses anything over the limit, records the real size rather than the
declared one, and deletes the original when ingest refuses it — otherwise
a rejected file sits in the bucket for the book's whole 30-day life, which
is a month of free storage for whatever was pushed at us. A book now has a
ceiling of 600 photographs: generous for a 96-page book, and the wall
behind every other limit.

**The structural fix is now done.** Uploads are a presigned POST with a
`content-length-range` condition in the signed policy, so the cap belongs
to the storage service and applies before a byte lands. `presign_put` is
removed rather than deprecated: left in place it is a loaded gun for the
next person who needs an upload URL in a hurry, and a test asserts it is
gone. Both clients — the editor and the contributor page — send the fields
unmodified with the file last, which the S3 POST contract requires and
which a comment at each site says out loud.

The contributor path signs the tighter policy: the book's REMAINING
allowance rather than the global ceiling, so a contributor cannot spend
more of it than they were granted even by ignoring the size they declared.

Three things learned doing it, each of which changed the work:

* **`moto` does not enforce `content-length-range`.** Measured, in both
  in-process and server mode: a 5 KB body sailed through a 100-byte policy
  with a 204. It validates nothing else on a POST either — no policy, a
  tampered policy and a substituted key are all accepted. So the tests
  assert what the signed policy CONTAINS, which is the part we are
  responsible for and the part that realistically regresses, and they say
  in writing that they are not proof an oversized upload is refused. The
  `head_size` check in `ingest_photo` is therefore still load-bearing and
  must not be removed.
* **boto signed the POST policy as SigV2 by default** (`AWSAccessKeyId` +
  `signature`) — the deprecated form, removed in newer AWS regions. The
  upload cap rides on that signature, so it was the one credential that
  should not have been signed the old way. The presigner now sets
  `s3v4` explicitly. The test double was building its own client without
  that config, so the suite had been exercising a credential format the
  deployment never issues.
* **SigV4 caps a presigned URL at seven days and rejects anything longer.**
  The flip video asked for thirty, which would have been a 400 from
  storage at the moment a customer tapped the link. Its thirty days now
  live in the token — `/v/{token}` signs a fresh URL per visit and
  `find()` enforces the age — and `presign_get` clamps to the protocol
  ceiling so an invalid URL cannot be minted. A test asserts no expiry
  constant anywhere exceeds it, so the clamp should never fire.

**CR-003 Phase 1 — share links, production updates, gift mode.**

**CR-003-1, the share link, is a THIRD secret and that is the design.**
`edit_token` is everything, `telegram_token` attaches a chat, and
`share_token` shows pages. A share link is forwarded, screenshotted and
pasted into group chats, so it has to be incapable of doing anything else
and losing it must cost nothing but the showing. Revoking it deletes the
rendered images too, because clearing a column while the pictures sit in
storage is not what the owner thinks "revoke" means.

Share pages render at **144 DPI (~1190px)** — above the 72 DPI preview
because this image *is* the advertisement and gets looked at on a phone,
and below the CR's 1200px ceiling so a forwarded link can never yield
print-quality copies of a family's photographs. The renderers are the
preview's own, with the scale as a parameter, so the book being shown off
cannot drift from the book that was approved; the preview's 115 render
tests confirm its own output is byte-identical.

**The share page is server-rendered, unlike every other page on this
site,** for one reason: the Open Graph card has to carry *this book's*
cover. The link is going into Telegram and that card is the whole
advertisement. `X-Robots-Tag: noindex` and `Referrer-Policy: no-referrer`
on everything a token reaches — customers' photographs must never appear
in a search result.

**CR-003-2 adds three stages to the order state machine** — printing,
binding, quality_check — and **allows forward skips**. An operator who has
to click through every stage to record reality will stop recording it, and
a status nobody updates is worse than one with gaps. Only three stages
reach the customer; a bot that narrates every internal step gets muted,
and then the message that mattered is muted too.

Idempotency per `(order, status)` is decided from the order's own audit
trail rather than a new table — the fact is already recorded there, and
the operator is one person on a phone who will press the same button
twice.

**CR-003-3's one rule is structural, not a check.** Production messages go
to the buyer because the only channels that exist are the buyer's: the
book's Telegram chat, which the buyer linked, and the order's email, which
is the buyer's. The recipient's details live in a separate table that only
the operator's notification reads. A present someone was told about in
advance is not a present, and the way to keep that true is to have no path
that could send them anything.

The operator's Telegram notification puts the gift block **above the print
files**, because every line of it changes what the person packing the box
does: a different address, a card to write by hand, a date not to ship
before, and no price in the box.

**CR-003-4 is a printing job and a spreadsheet,** written up in
`docs/referral-card.md` rather than built. At 40 books a month a referral
system is a table nobody reads. The one thing the write-up insists on is
the column people forget: the promise is *two* discounts, and a programme
that quietly honours only the friend's cheats the customer who liked you
enough to recommend you.

**CR-003-8 is deliberately NOT built.** Its own condition is "only if
capacity is genuinely constrained", and 40+ books a month against current
volume is not a constraint. A scarcity counter that counts nothing real is
exactly the practice this project rated a competitor down for.
