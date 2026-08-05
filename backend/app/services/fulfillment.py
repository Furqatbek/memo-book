"""Order fulfillment: paid -> rendering -> rendered with a PdfArtifact.

Failures land in render_failed (never a zombie state) with the operator
alert effect logged; render_failed -> rendering stays open as the retry
path. Rendering twice never creates two artifacts.
"""
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import queue
from app.domain.states import OrderStatus
from app.models.book import Book
from app.models.order import Order
from app.models.payment import PdfArtifact
from app.services import outbox
from app.services.orders import apply_transition
from app.services.render import render_cover, render_interior

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
        apply_transition(session, order, OrderStatus.RENDER_FAILED, str(exc)[:500])
        await session.commit()
        # Effect.ALERT_OPERATOR — surfaced via structured log until M11 wiring.
        log.error("render.failed_alert_operator", order=order.human_ref,
                  error=str(exc))
        return

    if have_interior is None:
        _add_artifact(session, order_id, interior_meta)
    if have_cover is None:
        _add_artifact(session, order_id, cover_meta)
    apply_transition(session, order, OrderStatus.RENDERED,
                     "interior + cover rendered")
    # NOTIFY_PRODUCTION effect: the outbox row commits in the SAME
    # transaction as the rendered transition (spec Part 8) — a Telegram
    # outage can neither roll back the render nor lose the notification.
    book = (await session.execute(
        select(Book).where(Book.id == order.book_id)
    )).scalar_one()
    outbox.enqueue(session, outbox.TOPIC_ORDER_RENDERED,
                   outbox.rendered_payload(order, book,
                                           interior_meta["storage_key"],
                                           cover_meta["storage_key"]))
    await session.commit()
    log.info("render.rendered", order=order.human_ref,
             interior_sha256=interior_meta["sha256"],
             cover_sha256=cover_meta["sha256"])

    if queue.eager():
        await outbox.deliver_pending(session)
    # In worker deployments the standalone outbox worker delivers on its
    # own cadence — nothing to enqueue here.
