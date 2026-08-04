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
