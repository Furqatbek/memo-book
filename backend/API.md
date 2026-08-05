# Photo Book Platform — API Reference

Interactive docs: `GET /docs` (Swagger UI, generated from code).
This file is the example-driven reference for frontend work.

- **Base path:** `/api/v1` (health probes live at the root)
- **Auth:** anonymous ownership via the `X-Edit-Token` header — returned once
  by `POST /books`, required by every book-scoped endpoint. A wrong token is
  indistinguishable from a missing book (`404`), so tokens can't be probed.
- **Concurrency:** every layout mutation requires `If-Match: <layout_version>`.
  Stale version → `409` carrying the current layout; missing header → `428`.
- **Money:** integers in **tiyin** (1 UZS = 100 tiyin). Never floats.
- **Coordinates:** millimetres, origin at the top-left of the **trim** box
  (148×210mm). Full-bleed = `(-3, -3, 154, 216)`. Text is clamped server-side
  into the safe area (5mm inside trim) — the response shows the clamped values.

## Error envelope

Every error, including validation errors, uses one shape. Switch on `code`,
never on `message`:

```json
{ "error": { "code": "PHOTOS_INSUFFICIENT",
             "message": "you have 10 photos but the 16-page book needs 16",
             "details": { "have": 10, "need": 16 } } }
```

| Code | HTTP | Meaning |
|---|---|---|
| `VALIDATION_ERROR` | 422 | Request shape/content invalid (`details.errors` lists fields) |
| `INVALID_PAGE_TIER` | 422 | `page_count` not one of 16/32/48/96 |
| `INVALID_PLACEMENT` | 422 | Placement outside the bleed canvas |
| `VERSION_REQUIRED` | 428 | `If-Match` header missing |
| `VERSION_CONFLICT` | 409 | Stale layout version; `details.layout` is the current document |
| `BOOK_LOCKED` | 423 | Book checked out; layout is immutable |
| `BOOK_EXPIRED` | 410 | Draft expired (30-day retention) |
| `PHOTOS_INSUFFICIENT` | 409 | Fewer usable photos than pages (R1) |
| `PAGES_INCOMPLETE` | 409 | A page has no placement / references an unusable photo |
| `PREVIEW_NOT_CONFIRMED` | 422 | `confirmed_preview` was not `true` |
| `PREVIEW_STALE` | 409 | No preview, or layout changed since it rendered |
| `ORDER_NOT_FOUND` | 404 | Unknown reference or wrong phone |
| `SIGNATURE_INVALID` | 403 | Webhook signature failed (nothing recorded) |
| `AMOUNT_MISMATCH` | 400 | Callback amount ≠ stored order amount |
| `ILLEGAL_TRANSITION` | 409 | e.g. cancel after payment |
| `RATE_LIMITED` | 429 | Per-IP limit hit (`details.scope`, per minute) |
| `NOT_FOUND` | 404 | Book/photo/provider not found (or bad token) |

## Status vocabularies

- **Book:** `draft → locked → ordered`; `draft → expired`
- **Photo:** `pending → processing → ready | duplicate | failed`
- **Order:** `draft_order → pending_payment → paid → rendering → rendered →
  sent_to_production → shipped → delivered`; `pending_payment → cancelled`
  (re-checkout allowed); `rendering → render_failed → rendering`;
  `shipped|delivered → refunded`

---

## Health

```bash
curl $API/health          # → {"status":"ok"}          (no dependency checks)
curl $API/ready           # → 200 {"status":"ok","checks":{...}} or 503
```

---

## Books

### Create a book — `POST /api/v1/books`

```bash
curl -X POST $API/api/v1/books -H 'Content-Type: application/json' \
     -d '{"page_count": 16}'
```

`201`:

```json
{
  "book_id": "7b0f6c19-0e9c-43ed-9e71-bfecd3ad3d66",
  "edit_token": "Qw3…43-char-url-safe-secret…xZ",
  "page_count": 16,
  "status": "draft",
  "layout": {
    "version": 1,
    "cover": { "photo_id": null, "title": "", "subtitle": "",
               "title_font": "Inter", "title_size_pt": 28.0 },
    "pages": [ { "index": 0, "placements": [], "texts": [] }, "… 15 more …" ]
  },
  "layout_version": 1,
  "email": null,
  "photos": [],
  "created_at": "2026-08-05T10:00:00Z",
  "updated_at": "2026-08-05T10:00:00Z",
  "expires_at": "2026-09-04T10:00:00Z"
}
```

**Store `edit_token` — it is shown only here.** Errors: `INVALID_PAGE_TIER`,
`RATE_LIMITED`.

### Get a book — `GET /api/v1/books/{book_id}`

```bash
curl $API/api/v1/books/$BOOK -H "X-Edit-Token: $TOKEN"
```

Same shape as above without `edit_token`; `photos` is the serialized list
(see *List photos*).

### Update the layout — `PATCH /api/v1/books/{book_id}/layout`

The layout is always written **as a whole document**. Autosave = send the
full document on every user action.

```bash
curl -X PATCH $API/api/v1/books/$BOOK/layout \
     -H "X-Edit-Token: $TOKEN" -H "If-Match: 1" \
     -H 'Content-Type: application/json' -d '{
  "version": 1,
  "cover": { "photo_id": "PHOTO_UUID", "title": "Italy 2026", "subtitle": "June",
             "title_font": "Inter", "title_size_pt": 28 },
  "pages": [
    { "index": 0,
      "placements": [ { "photo_id": "PHOTO_UUID",
                        "x_mm": -3, "y_mm": -3, "w_mm": 154, "h_mm": 216,
                        "rotation": 0, "fit": "cover" } ],
      "texts": [ { "id": "t1", "x_mm": 12, "y_mm": 180, "w_mm": 124, "h_mm": 18,
                   "content": "Amalfi coast", "font": "Inter", "size_pt": 11,
                   "align": "left", "color": "#1a1a1a" } ] },
    { "index": 1, "placements": [], "texts": [] }
  ]
}'
```

`200` → `{ "layout": { …clamped, saved document… }, "layout_version": 2 }`
— a text box sent at `x_mm: 1` comes back at `x_mm: 5` (safe-area clamp).

Rules: exactly `page_count` pages with contiguous `index`; ≤1 placement per
page (MVP); placements must lie inside the bleed canvas. Errors:
`VERSION_REQUIRED` (428), `VERSION_CONFLICT` (409, current layout in
`details`), `BOOK_LOCKED` (423), `INVALID_PLACEMENT`, `VALIDATION_ERROR`.

### Change the tier — `PATCH /api/v1/books/{book_id}/page-count`

```bash
curl -X PATCH $API/api/v1/books/$BOOK/page-count \
     -H "X-Edit-Token: $TOKEN" -H "If-Match: 2" \
     -H 'Content-Type: application/json' -d '{"page_count": 32}'
```

`200` → `{ "page_count": 32, "layout": {…}, "layout_version": 3,
"warnings": [] }`. Shrinking never drops silently — warnings report what was
truncated: `["truncated 16 pages containing 3 placed photos and 1 text boxes"]`.

### Set a recovery email — `PATCH /api/v1/books/{book_id}/email`

```bash
curl -X PATCH $API/api/v1/books/$BOOK/email \
     -H "X-Edit-Token: $TOKEN" -H 'Content-Type: application/json' \
     -d '{"email": "traveller@example.com"}'
```

Enables the day-3 / day-14 draft reminders. `200` → book document.

### Auto-place — `POST /api/v1/books/{book_id}/auto-place`

Fills pages chronologically (EXIF `taken_at` ascending; undated photos last
in upload order — deterministic, never random), one full-bleed photo per
page. Cover and existing texts are preserved.

```bash
curl -X POST $API/api/v1/books/$BOOK/auto-place \
     -H "X-Edit-Token: $TOKEN" -H "If-Match: 3"
```

`200`:

```json
{ "layout": { "…placements rewritten…" },
  "layout_version": 4,
  "placed_count": 16,
  "unplaced_photo_ids": ["…surplus photo ids, never dropped silently…"] }
```

### Checkout eligibility — `GET /api/v1/books/{book_id}/checkout-eligibility`

```bash
curl $API/api/v1/books/$BOOK/checkout-eligibility -H "X-Edit-Token: $TOKEN"
```

```json
{ "eligible": false, "photo_count": 10, "page_count": 16,
  "issues": [ { "code": "PHOTOS_INSUFFICIENT",
                "message": "You have 10 photos but the 16-page book needs 16.",
                "details": { "have": 10, "need": 16, "shortfall": 6 } } ],
  "suggested_tier": null }
```

On surplus (20 photos / 16 pages): `eligible: true, suggested_tier: 32`
(the upsell).

---

## Photos

Bytes go **directly to object storage** via a presigned URL — never through
the API.

### 1. Request an upload URL — `POST /api/v1/books/{book_id}/photos/upload-url`

```bash
curl -X POST $API/api/v1/books/$BOOK/photos/upload-url \
     -H "X-Edit-Token: $TOKEN" -H 'Content-Type: application/json' \
     -d '{"filename": "IMG_1204.HEIC", "mime": "image/heic", "bytes": 2048000}'
```

`200` → `{ "upload_url": "https://…signed, 15-min expiry…",
"photo_id": "…", "storage_key": "books/…/orig/…" }`.
Allowed mimes: `image/jpeg`, `image/png`, `image/heic`, `image/heif`;
max 25MB. Errors: `VALIDATION_ERROR`, `RATE_LIMITED`.

### 2. Upload the bytes (client → storage)

```bash
curl -X PUT "$UPLOAD_URL" -H 'Content-Type: image/heic' \
     --data-binary @IMG_1204.HEIC
```

### 3. Confirm — `POST /api/v1/books/{book_id}/photos/{photo_id}/complete`

```bash
curl -X POST $API/api/v1/books/$BOOK/photos/$PHOTO/complete \
     -H "X-Edit-Token: $TOKEN"
```

`200` → `{"status": "processing"}` (idempotent; `422` if nothing was
uploaded). Ingest then converts HEIC→JPEG, extracts `taken_at` **before**
conversion, applies EXIF rotation physically, builds display/thumb
derivatives with all metadata stripped, and flags duplicates by hash.
Poll the list until `ready`.

### List photos — `GET /api/v1/books/{book_id}/photos`

```bash
curl $API/api/v1/books/$BOOK/photos -H "X-Edit-Token: $TOKEN"
```

```json
{ "photos": [ {
    "photo_id": "…", "status": "ready", "error": null,
    "width": 4032, "height": 3024,
    "mime_original": "image/heic", "bytes_original": 2048000,
    "taken_at": "2026-06-13T10:00:00Z",
    "uploaded_at": "2026-08-05T10:05:00Z",
    "resolution_status": "ok",
    "duplicate_of": null,
    "display_url": "https://…signed, 1h…",
    "thumb_url": "https://…signed, 1h…" } ] }
```

`resolution_status` (`ok`/`warn`/`block`) is computed for a full-bleed
placement; recompute per placed size in the editor with the same thresholds
(≥200 DPI ok, 100–199 warn, <100 block; sources <800px never fill a page).
A `duplicate` photo is placeable; `duplicate_of` points at its twin.

### Delete — `DELETE /api/v1/books/{book_id}/photos/{photo_id}`

```bash
curl -X DELETE $API/api/v1/books/$BOOK/photos/$PHOTO -H "X-Edit-Token: $TOKEN"
```

`204`; removes the row and all storage objects.

---

## Preview

### Request — `POST /api/v1/books/{book_id}/preview`

```bash
curl -X POST $API/api/v1/books/$BOOK/preview -H "X-Edit-Token: $TOKEN"
```

`202` → `{"status": "processing"}`. Renders every page (empty ones as
watermarked blanks) at 72dpi with a `PREVIEW` watermark.

### Poll — `GET /api/v1/books/{book_id}/preview`

```json
{ "status": "ready",
  "page_urls": ["https://…page-0.jpg…", "… one per page …"],
  "stale": false, "page_count": 16, "layout_version": 4 }
```

`stale: true` the moment the layout changes after rendering — checkout will
refuse a stale preview, so re-render before confirming.

---

## Checkout & orders

### Checkout — `POST /api/v1/books/{book_id}/checkout`

Requires, in order: an editable draft; `confirmed_preview: true` (timestamp
recorded); a fresh preview; photos ≥ pages (R1); every page holding a usable
placement.

```bash
curl -X POST $API/api/v1/books/$BOOK/checkout \
     -H "X-Edit-Token: $TOKEN" -H 'Content-Type: application/json' -d '{
  "name": "Aziza Karimova",
  "phone": "+998 90 123-45-67",
  "address": "Tashkent, Chilonzor 5, dom 12, kv 34",
  "email": "aziza@example.com",
  "confirmed_preview": true
}'
```

`201`:

```json
{ "human_ref": "UB-7K3M2",
  "order_status": "pending_payment",
  "amount_minor": 29900000,
  "currency": "UZS",
  "payment": {
    "providers_available": ["dev"],
    "init": [ { "provider": "dev", "human_ref": "UB-7K3M2",
                "amount_minor": 29900000, "currency": "UZS",
                "webhook": "/api/v1/payments/dev/webhook",
                "note": "dev mode: POST the webhook with the shared signature header to mark this order paid" } ] } }
```

The book locks (`423` on all mutations). Errors: `PREVIEW_NOT_CONFIRMED`,
`PREVIEW_STALE`, `PHOTOS_INSUFFICIENT`, `PAGES_INCOMPLETE`, `BOOK_LOCKED`.

### Public status — `GET /api/v1/orders/{human_ref}?phone=…`

No token; reference + phone (any formatting). Returns no PII.

```bash
curl "$API/api/v1/orders/UB-7K3M2?phone=998901234567"
```

```json
{ "human_ref": "UB-7K3M2", "status": "rendered", "page_count": 16,
  "amount_minor": 29900000, "currency": "UZS",
  "created_at": "2026-08-05T10:30:00Z", "paid_at": "2026-08-05T10:31:00Z" }
```

Wrong phone ≡ unknown reference (`404 ORDER_NOT_FOUND`).

---

## Payments (dev provider)

Real acquirers implement the same webhook contract later. In dev mode a
correctly-signed webhook **is** the payment.

### Webhook — `POST /api/v1/payments/dev/webhook`

```bash
curl -X POST $API/api/v1/payments/dev/webhook \
     -H "X-Dev-Signature: $DEV_PAYMENT_SECRET" \
     -H 'Content-Type: application/json' -d '{
  "event_id": "evt-001",
  "action": "pay",
  "human_ref": "UB-7K3M2",
  "amount_minor": 29900000
}'
```

`200` → `{ "status": "ok", "order_status": "rendered", "duplicate": false }`
(with `TASK_EAGER=true` the render runs inline; otherwise poll the public
status through `paid → rendering → rendered`).

Semantics: signature verified **before** parsing (`403`, nothing recorded);
amount must equal the order (`400 AMOUNT_MISMATCH`); the same
`(provider, event_id, action)` replayed returns the same response with
`duplicate: true` and zero side effects; a `pay` for an already-paid order is
acknowledged, not re-executed. `{"action": "cancel", …}` cancels a
pending order and unlocks the book; cancel after payment → `409`.

---

## Happy path, end to end

```bash
API=http://localhost:8000
BOOK=$(curl -s -X POST $API/api/v1/books -H 'Content-Type: application/json' \
        -d '{"page_count":16}')
ID=$(echo $BOOK | jq -r .book_id); TOKEN=$(echo $BOOK | jq -r .edit_token)

# repeat ×16: presign → PUT → complete
U=$(curl -s -X POST $API/api/v1/books/$ID/photos/upload-url \
     -H "X-Edit-Token: $TOKEN" -H 'Content-Type: application/json' \
     -d '{"filename":"a.jpg","mime":"image/jpeg","bytes":123456}')
curl -s -X PUT "$(echo $U | jq -r .upload_url)" \
     -H 'Content-Type: image/jpeg' --data-binary @a.jpg
curl -s -X POST $API/api/v1/books/$ID/photos/$(echo $U | jq -r .photo_id)/complete \
     -H "X-Edit-Token: $TOKEN"

curl -s -X POST $API/api/v1/books/$ID/auto-place \
     -H "X-Edit-Token: $TOKEN" -H "If-Match: 1"
curl -s -X POST $API/api/v1/books/$ID/preview -H "X-Edit-Token: $TOKEN"
REF=$(curl -s -X POST $API/api/v1/books/$ID/checkout \
     -H "X-Edit-Token: $TOKEN" -H 'Content-Type: application/json' \
     -d '{"name":"A","phone":"+998900000000","address":"Tashkent","confirmed_preview":true}' \
     | jq -r .human_ref)
curl -s -X POST $API/api/v1/payments/dev/webhook \
     -H "X-Dev-Signature: dev-secret-change-me" -H 'Content-Type: application/json' \
     -d "{\"event_id\":\"e1\",\"action\":\"pay\",\"human_ref\":\"$REF\",\"amount_minor\":29900000}"
curl -s "$API/api/v1/orders/$REF?phone=998900000000"
```
