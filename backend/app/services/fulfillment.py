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

from app.domain.states import OrderStatus
from app.models.order import Order
from app.models.payment import PdfArtifact
from app.services.orders import apply_transition
from app.services.render import render_interior

log = structlog.get_logger()


async def run_order_render(session: AsyncSession, order_id: uuid.UUID) -> None:
    order = (await session.execute(
        select(Order).where(Order.id == order_id)
    )).scalar_one()

    existing = (await session.execute(
        select(PdfArtifact).where(PdfArtifact.order_id == order_id,
                                  PdfArtifact.kind == "interior")
    )).scalar_one_or_none()
    if order.status == OrderStatus.RENDERED.value and existing is not None:
        return  # idempotent: already rendered

    if order.status in (OrderStatus.PAID.value, OrderStatus.RENDER_FAILED.value):
        apply_transition(session, order, OrderStatus.RENDERING, "render started")
        await session.commit()
    elif order.status != OrderStatus.RENDERING.value:
        log.warning("render.skipped_wrong_state", order=order.human_ref,
                    status=order.status)
        return

    try:
        meta = await render_interior(session, order.book_id)
    except Exception as exc:  # noqa: BLE001 — job boundary
        apply_transition(session, order, OrderStatus.RENDER_FAILED, str(exc)[:500])
        await session.commit()
        # Effect.ALERT_OPERATOR — surfaced via structured log until M11 wiring.
        log.error("render.failed_alert_operator", order=order.human_ref,
                  error=str(exc))
        return

    if existing is None:
        session.add(PdfArtifact(
            order_id=order_id, kind="interior", storage_key=meta["storage_key"],
            sha256=meta["sha256"], page_count=meta["page_count"],
            size_bytes=meta["bytes"], render_ms=meta["render_ms"],
            created_at=datetime.now(UTC),
        ))
    apply_transition(session, order, OrderStatus.RENDERED, "interior rendered")
    await session.commit()
    log.info("render.rendered", order=order.human_ref, sha256=meta["sha256"])
