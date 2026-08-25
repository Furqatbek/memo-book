"""Order fulfillment: paid -> rendering -> rendered with a PdfArtifact.

Failures land in render_failed — never a zombie state — and the operator is
actually told, through the outbox, in the same transaction as the failure
(A76). `render_failed -> rendering` stays open as the retry path. Rendering
twice never creates two artifacts.

A render that stops making progress is not a state this can reach on its
own, so `reap_stalled_renders` at the bottom of this file is what notices a
worker that died mid-job.
"""
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import queue
from app.config import get_settings
from app.domain.states import OrderStatus
from app.models.book import Book
from app.models.order import Order, OrderEvent
from app.models.payment import PdfArtifact
from app.services import outbox
from app.services.effects import When, run_effects
from app.services.orders import apply_transition
from app.services.render import render_cover, render_interior, soft_pages

log = structlog.get_logger()


async def _existing_artifact(session: AsyncSession, order_id: uuid.UUID,
                             kind: str) -> PdfArtifact | None:
    return (await session.execute(
        select(PdfArtifact).where(PdfArtifact.order_id == order_id,
                                  PdfArtifact.kind == kind)
    )).scalar_one_or_none()


def _add_artifact(session: AsyncSession, order_id: uuid.UUID, meta: dict) -> None:
    session.add(PdfArtifact(
        order_id=order_id, kind=meta["kind"], storage_key=meta["storage_key"],
        sha256=meta["sha256"], page_count=meta["page_count"],
        size_bytes=meta["bytes"], render_ms=meta["render_ms"],
        created_at=datetime.now(UTC),
    ))


async def run_order_render(session: AsyncSession, order_id: uuid.UUID) -> None:
    order = (await session.execute(
        select(Order).where(Order.id == order_id)
    )).scalar_one()

    have_interior = await _existing_artifact(session, order_id, "interior")
    have_cover = await _existing_artifact(session, order_id, "cover")
    if (order.status == OrderStatus.RENDERED.value
            and have_interior is not None and have_cover is not None):
        return  # idempotent: already rendered

    if order.status in (OrderStatus.PAID.value, OrderStatus.RENDER_FAILED.value):
        apply_transition(session, order, OrderStatus.RENDERING, "render started")
        await session.commit()
    elif order.status != OrderStatus.RENDERING.value:
        log.warning("render.skipped_wrong_state", order=order.human_ref,
                    status=order.status)
        return

    try:
        interior_meta = await render_interior(session, order.book_id)
        cover_meta = await render_cover(session, order.book_id)
    except Exception as exc:  # noqa: BLE001 — job boundary
        effects = apply_transition(session, order, OrderStatus.RENDER_FAILED,
                                   str(exc)[:500])
        # Effect.ALERT_OPERATOR. The alert is an outbox row in this same
        # transaction, so the customer's order cannot be marked failed
        # without somebody being told (A76).
        await run_effects(session, order, effects, When.IN_TRANSACTION,
                          reason="the print files could not be rendered",
                          detail=str(exc))
        await session.commit()
        await run_effects(session, order, effects, When.AFTER_COMMIT)
        log.error("render.failed", order=order.human_ref, error=str(exc))
        return

    if have_interior is None:
        _add_artifact(session, order_id, interior_meta)
    if have_cover is None:
        _add_artifact(session, order_id, cover_meta)

    # The render can outlive the watchdog's patience: a job that takes longer
    # than RENDER_STALL_AFTER is declared stalled and moved to render_failed
    # while it is still working. It then finishes successfully, and the files
    # are real. Re-read the row rather than trusting the copy loaded before
    # the render started, and walk back through `rendering` — the legal route
    # — so the audit trail says what actually happened instead of a status
    # silently overwriting the watchdog's (A76).
    await session.refresh(order)
    if order.status == OrderStatus.RENDER_FAILED.value:
        apply_transition(session, order, OrderStatus.RENDERING,
                         "the render was declared stalled but then finished")
    effects = apply_transition(session, order, OrderStatus.RENDERED,
                               "interior + cover rendered")
    # NOTIFY_PRODUCTION: the outbox row commits in the SAME transaction as
    # the rendered transition (spec Part 8) — a Telegram outage can neither
    # roll back the render nor lose the notification.
    book = (await session.execute(
        select(Book).where(Book.id == order.book_id)
    )).scalar_one()
    await run_effects(session, order, effects, When.IN_TRANSACTION,
                      book=book,
                      interior_key=interior_meta["storage_key"],
                      cover_key=cover_meta["storage_key"],
                      soft_pages=await soft_pages(session, order.book_id))
    await session.commit()
    await run_effects(session, order, effects, When.AFTER_COMMIT)
    log.info("render.rendered", order=order.human_ref,
             interior_sha256=interior_meta["sha256"],
             cover_sha256=cover_meta["sha256"])

    if queue.eager():
        await outbox.deliver_pending(session)
    # In worker deployments the standalone outbox worker delivers on its
    # own cadence — nothing to enqueue here.


async def reap_stalled_renders(session: AsyncSession,
                               now: datetime | None = None) -> int:
    """Move renders that stopped making progress into render_failed (A76).

    A worker killed mid-job — OOM, a deploy, a reboot — leaves its order in
    `rendering` with nothing left to finish it: no retry, no timeout, no
    alert. The customer has paid, the printer never hears about it, and the
    only sign is a row that looks busy forever. This is the thing that
    notices.

    It does not kill anything; it re-labels. `render_failed` is retryable by
    the operator and, unlike `rendering`, it is loud — entering it declares
    ALERT_OPERATOR. A job that turns out to still be alive and finishes later
    walks itself back (see run_order_render).

    The timeout is therefore a "certainly dead" threshold, not a deadline:
    err generous. Renders of the largest book are measured in a couple of
    minutes; the default here is half an hour.
    """
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(seconds=get_settings().render_stall_after_s)

    orders = (await session.execute(
        select(Order).where(Order.status == OrderStatus.RENDERING.value)
    )).scalars().all()

    reaped = 0
    for order in orders:
        started = (await session.execute(
            select(sa_func.max(OrderEvent.created_at)).where(
                OrderEvent.order_id == order.id,
                OrderEvent.to_status == OrderStatus.RENDERING.value)
        )).scalar_one_or_none()
        # No event at all should be impossible — every transition writes one
        # — but treating "unknown" as "not yet stale" is the safe direction:
        # the alternative fails a render that may be running fine.
        if started is None:
            continue
        # SQLite gives these back naive; Postgres gives them back aware.
        # Normalise BEFORE comparing — mixing the two raises TypeError, and
        # this code path only runs when something has already gone wrong.
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        if started > cutoff:
            continue

        effects = apply_transition(
            session, order, OrderStatus.RENDER_FAILED,
            f"no progress for {get_settings().render_stall_after_s}s — "
            "the render worker probably died")
        await run_effects(session, order, effects, When.IN_TRANSACTION,
                          reason="the render stopped without finishing",
                          detail="The worker was probably killed mid-job. "
                                 "Retry it from the console.")
        await session.commit()
        await run_effects(session, order, effects, When.AFTER_COMMIT)
        reaped += 1
        log.warning("render.stalled", order=order.human_ref,
                    started_at=str(started))
    return reaped
