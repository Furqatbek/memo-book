# memo-book backend

Backend for the self-serve photo book platform. Spec: [`../backend-build-prompt.md`](../backend-build-prompt.md)
(build milestones in Part 10). Current state: **Milestones 1–4 complete** —
FastAPI skeleton, fully unit-tested pure domain core, the books API
(JSONB layout, optimistic concurrency via `If-Match`, anonymous `X-Edit-Token`
auth, page-count re-flow, 30-day retention extension), and photo ingest
(presigned direct-to-S3 uploads, HEIC→JPEG with EXIF extracted first,
physical orientation fix, metadata-stripped derivatives, sha256 dedupe,
decompression-bomb guards; RQ worker or inline via `TASK_EAGER`).

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
