# memo-book backend

Backend for the self-serve photo book platform.
**API reference with request/response examples: [`API.md`](API.md)**
(interactive Swagger UI at `/docs` when the server is running).
Spec: [`../backend-build-prompt.md`](../backend-build-prompt.md)
(build milestones in Part 10). Current state: **all 13 milestones complete** —
FastAPI skeleton, fully unit-tested pure domain core, the books API
(JSONB layout, optimistic concurrency via `If-Match`, anonymous `X-Edit-Token`
auth, page-count re-flow, 30-day retention extension), and photo ingest
(presigned direct-to-S3 uploads, HEIC→JPEG with EXIF extracted first,
physical orientation fix, metadata-stripped derivatives, sha256 dedupe,
decompression-bomb guards; RQ worker or inline via `TASK_EAGER`), plus
auto-place (R2 chronological fill, surplus surfaced), the
checkout-eligibility endpoint (R1/R3), and the interior render pipeline
(300dpi from originals, one page at a time under a proven 512MB budget,
byte-deterministic RGB PDF + optional Ghostscript CMYK stage, repo-pinned
DejaVu fonts, golden-raster regression test), the 72dpi watermarked
preview with staleness tracking, and checkout/orders (confirmation gate
with recorded timestamp, R1 + complete-pages enforcement, book locking,
append-only order_events audit, cancellation/re-checkout, public status
lookup by reference + phone), and payments in dev mode (PaymentProvider
protocol, signature-before-parse, amount verification, R10 webhook
idempotency, paid → render → PdfArtifact; real acquirers slot into the
same protocol later), the hardcover wrap render (spine-table-driven
geometry — PLACEHOLDER values until the printer confirms — front-panel
art through the wrap, vector title/subtitle, second PdfArtifact), the
transactional outbox with Telegram delivery (same-transaction enqueue,
exponential backoff, 7-day signed artifact links generated at delivery
time — never the file), lifecycle jobs (R6 expiry + storage GC, R7
reminders through the outbox), and hardening (per-IP rate limiting, the
Part 9.5 end-to-end journey test, smoke + load scripts).

## Definition of Done (spec Part 13) status

1. ✅ Part 9 tests pass in CI (unit, integration, render, E2E)
2. ✅ E2E passes — CI runs it against real Postgres (moto stands in for S3;
   run once against `docker compose` before launch)
3. ✅ 96-page render within budget under 512MB peak RSS (measured 62MB)
4. ✅ Duplicated payment webhook provably causes no duplicate side effects
5. ✅ Expiry never touches ordered books' photos (dedicated test)
6. ◻️ Smoke after deploy with auto-rollback — `scripts/smoke.py` is ready;
   wire it into the deploy pipeline when one exists
7. ✅ HEIC → correctly ordered, correctly oriented page (synthetic fixture;
   add one real iPhone HEIC before launch — A18)
8. ✅ README local setup in under ten commands
9. ✅ Every environment variable documented in `.env.example`

The frontend editor lives in [`../editor`](../editor/README.md) and consumes
this API (`CORS_ORIGINS` / `EDITOR_DIR` in `.env.example` wire it up).

## Operations

```bash
uvicorn app.main:app                    # API
rq worker ingest preview render         # job workers (RQ)
python -m app.workers.outbox            # notification delivery loop
python -m app.workers.lifecycle         # nightly via cron (expiry+reminders)
python scripts/smoke.py <base_url>      # post-deploy smoke (<30s, exit!=0 = roll back)
python scripts/loadtest.py <base_url>   # pre-launch load test (NOT in CI)
python scripts/devserver.py --fresh     # dev: whole stack, no Docker (SQLite +
                                        #   in-process S3 + editor at /editor)
```

## Go-live blockers (config only)

- Real spine widths + wrap margin from the printer (`SPINE_MM_*`, A26/A38)
- Real tier prices (`PRICE_MINOR_*`, A32)
- A real payment provider (`app/payments/`, A35) and
  `DEV_PAYMENTS_ENABLED=false`
- Telegram bot credentials; email transport for reminders (A41)
- One genuine iPhone HEIC in the test fixtures (A18)
- Point the deployed editor at the deployed API: `apiBase` in
  `editor/config.js`, `CORS_ORIGINS` here, and a bucket CORS rule for
  browser uploads (A48)

## Local setup

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
docker compose up -d          # Postgres 16, Redis 7, MinIO (+ bucket)
cp .env.example .env
pytest                        # all tests
uvicorn app.main:app --reload # http://localhost:8000/health, /ready, /docs
```

## Layout

| Path | Contents |
|---|---|
| `app/domain/` | **Milestone 2 — pure business rules, zero I/O.** Geometry & mm→px mapping, text clamping, resolution classification, R2 auto-place ordering, R1/R3 tier gating, order/book state machines with declared effects, money (integer minor units). |
| `app/api/` | HTTP endpoints (`/health`, `/ready` so far) |
| `app/config.py` | pydantic-settings; every variable documented in `.env.example` |
| `alembic/` | Migrations (initialised; first models arrive in Milestone 3) |
| `tests/` | pytest + hypothesis property tests |

## Rules of the codebase

- Geometry constants live in `app/domain/geometry.py` and are imported from
  there — never redefined.
- `order.status` is never assigned directly; all changes go through
  `transition_order()`, which enforces the legal-transition map and returns
  the effects the transition mandates (entering `paid` is the **only** thing
  that enqueues a render — rule R8).
- No floats in any monetary path. Amounts are integers in tiyin.
- Error codes are the closed enum in `app/domain/errors.py`; the frontend
  switches on `code`, never on `message`.

Assumptions made while implementing: see [`ASSUMPTIONS.md`](ASSUMPTIONS.md).
