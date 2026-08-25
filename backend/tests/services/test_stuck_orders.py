"""A76: a paid order must never stop moving without somebody being told.

Three ways it used to happen quietly, all on the money path:

* the render raised, the order went to `render_failed`, and the alert the
  domain declared was a log line nobody reads;
* the render worker was killed mid-job, leaving the order in `rendering`
  with nothing to finish it, nothing to retry it and nothing to notice;
* the printer's message exhausted its retries and the order sat in
  `rendered` looking perfectly healthy.

These test the first two end to end — what the operator actually receives —
rather than that a function was called.
"""
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.config import get_settings
from app.domain.states import Effect, OrderStatus
from app.models.order import Order, OrderEvent
from app.models.outbox import OutboxMessage, OutboxStatus
from app.services import outbox
from app.services.effects import When
from app.services.fulfillment import reap_stalled_renders, run_order_render
from tests.api.test_checkout import do_checkout, ready_book


async def paid_order(client, db) -> Order:
    """A real order taken all the way through checkout and payment.

    Paying runs the render eagerly in tests, so callers that want to control
    what the render does must patch it BEFORE calling this — which is also
    the honest shape, since a render fails on the attempt payment triggers,
    not on some later one.
    """
    book_id, headers = await ready_book(client, db)
    resp = await do_checkout(client, book_id, headers)
    assert resp.status_code == 201, resp.text
    ref = resp.json()["human_ref"]

    from app.services.payments import mark_paid
    order = (await db.execute(
        select(Order).where(Order.human_ref == ref))).scalar_one()
    await mark_paid(db, order, note="test", provider="dev", txn_id="t1")
    return order


def break_the_render(monkeypatch, message: str) -> None:
    async def boom(session, book_id):
        raise RuntimeError(message)

    monkeypatch.setattr("app.services.fulfillment.render_interior", boom)


async def paid_but_unrendered(client, db, monkeypatch) -> Order:
    """Paid, with the render never started — what the row looks like the
    instant before a worker picks the job up."""
    async def nothing(session, order_id):
        return None

    monkeypatch.setattr("app.services.effects.run_order_render", nothing,
                        raising=False)
    monkeypatch.setattr("app.services.fulfillment.run_order_render", nothing,
                        raising=False)
    import app.services.effects as effects_mod

    async def enqueue_nothing(session, order, context):
        return None

    original = effects_mod.EXECUTORS[Effect.ENQUEUE_RENDER]
    effects_mod.EXECUTORS[Effect.ENQUEUE_RENDER] = (When.AFTER_COMMIT,
                                                    enqueue_nothing)
    try:
        return await paid_order(client, db)
    finally:
        effects_mod.EXECUTORS[Effect.ENQUEUE_RENDER] = original


def alerts(messages: list[OutboxMessage]) -> list[OutboxMessage]:
    return [m for m in messages if m.topic == outbox.TOPIC_ORDER_ATTENTION]


async def all_messages(db) -> list[OutboxMessage]:
    return list((await db.execute(select(OutboxMessage))).scalars().all())


class TestAFailedRenderReachesTheOperator:
    async def test_an_alert_is_queued(self, client, db, monkeypatch):
        # Break the render before paying: payment is what triggers it.
        break_the_render(monkeypatch, "the printer PDF exploded")
        order = await paid_order(client, db)

        await db.refresh(order)
        assert order.status == OrderStatus.RENDER_FAILED.value

        queued = alerts(await all_messages(db))
        assert len(queued) == 1, "a failed render told nobody"
        assert queued[0].payload["human_ref"] == order.human_ref
        assert "render" in queued[0].payload["reason"]

    async def test_the_alert_says_what_broke(self, client, db, monkeypatch):
        break_the_render(monkeypatch, "cover artwork is 3 pixels wide")
        await paid_order(client, db)

        payload = alerts(await all_messages(db))[0].payload
        assert "3 pixels wide" in payload["detail"]

    async def test_the_alert_carries_no_customer_pii(self, client, db,
                                                     monkeypatch):
        """A Telegram chat is not an authenticated surface. The reference is
        enough for the operator to open the console, which is."""
        break_the_render(monkeypatch, "nope")
        await paid_order(client, db)

        payload = alerts(await all_messages(db))[0].payload
        blob = str(payload).lower()
        for leaked in ("aziza", "+998", "chilonzor", "example.com"):
            assert leaked not in blob, f"{leaked!r} leaked into an alert"

    async def test_the_alert_and_the_failure_commit_together(
            self, client, db, monkeypatch):
        """The whole point of routing it through the outbox: an order cannot
        be marked failed in one transaction and the alert lost in another."""
        break_the_render(monkeypatch, "nope")
        order = await paid_order(client, db)

        # Both are durable, from a fresh read of the session's own state.
        await db.refresh(order)
        assert order.status == OrderStatus.RENDER_FAILED.value
        assert alerts(await all_messages(db))[0].status == (
            OutboxStatus.PENDING.value)


class TestAStalledRenderIsNoticed:
    async def _stall(self, db, order, age_s: int) -> None:
        """Put the order in `rendering` with its entry event backdated, which
        is exactly what a worker killed mid-job leaves behind."""
        order.status = OrderStatus.RENDERING.value
        db.add(OrderEvent(
            id=uuid.uuid4(), order_id=order.id,
            from_status=OrderStatus.PAID.value,
            to_status=OrderStatus.RENDERING.value,
            note="render started",
            created_at=datetime.now(UTC) - timedelta(seconds=age_s)))
        await db.commit()

    async def test_a_fresh_render_is_left_alone(self, client, db, monkeypatch):
        """The reaper must not shoot a render that is merely working."""
        order = await paid_but_unrendered(client, db, monkeypatch)
        await self._stall(db, order, age_s=5)

        assert await reap_stalled_renders(db) == 0
        await db.refresh(order)
        assert order.status == OrderStatus.RENDERING.value

    async def test_an_old_one_is_moved_somewhere_retryable(self, client, db, monkeypatch):
        order = await paid_but_unrendered(client, db, monkeypatch)
        await self._stall(db, order,
                          age_s=get_settings().render_stall_after_s + 60)

        assert await reap_stalled_renders(db) == 1
        await db.refresh(order)
        assert order.status == OrderStatus.RENDER_FAILED.value

    async def test_and_the_operator_is_told(self, client, db, monkeypatch):
        order = await paid_but_unrendered(client, db, monkeypatch)
        await self._stall(db, order,
                          age_s=get_settings().render_stall_after_s + 60)
        await reap_stalled_renders(db)

        queued = alerts(await all_messages(db))
        assert len(queued) == 1
        assert "stopped" in queued[0].payload["reason"]

    async def test_the_audit_trail_records_why(self, client, db, monkeypatch):
        """`render_failed` with no explanation is a mystery six weeks later."""
        order = await paid_but_unrendered(client, db, monkeypatch)
        await self._stall(db, order,
                          age_s=get_settings().render_stall_after_s + 60)
        await reap_stalled_renders(db)

        events = (await db.execute(
            select(OrderEvent).where(
                OrderEvent.order_id == order.id,
                OrderEvent.to_status == OrderStatus.RENDER_FAILED.value)
        )).scalars().all()
        assert len(events) == 1
        assert "no progress" in (events[0].note or "")

    async def test_reaping_twice_alerts_once(self, client, db, monkeypatch):
        """The watchdog runs every few minutes. An order it already reaped is
        no longer in `rendering`, so it cannot be reaped again — otherwise
        the operator gets the same alert every five minutes forever."""
        order = await paid_but_unrendered(client, db, monkeypatch)
        await self._stall(db, order,
                          age_s=get_settings().render_stall_after_s + 60)

        assert await reap_stalled_renders(db) == 1
        assert await reap_stalled_renders(db) == 0
        assert len(alerts(await all_messages(db))) == 1


class TestASlowRenderThatFinishesAnyway:
    async def test_it_walks_itself_back_through_a_legal_route(
            self, client, db, monkeypatch):
        """The watchdog's threshold is a guess, so it will sometimes be wrong
        about a render that is slow rather than dead. When that job finishes,
        the files are real and the order must end up `rendered` — by the
        legal path, so the audit trail shows what happened rather than a
        status quietly overwriting the watchdog's."""
        order = await paid_but_unrendered(client, db, monkeypatch)

        # The watchdog gives up while the render is still working — the
        # render is between its opening transition and its closing one, which
        # is the only window where this can happen. Patching the cover render
        # puts us inside that window with the real interior already done.
        from app.render.cover import build_cover_pdf as real_build

        async def watchdog_fires_mid_render(session, book_id):
            from sqlalchemy import update
            await session.execute(
                update(Order).where(Order.id == order.id)
                .values(status=OrderStatus.RENDER_FAILED.value))
            session.add(OrderEvent(
                id=uuid.uuid4(), order_id=order.id,
                from_status=OrderStatus.RENDERING.value,
                to_status=OrderStatus.RENDER_FAILED.value,
                note="no progress for 1800s — the render worker probably died",
                created_at=datetime.now(UTC)))
            await session.commit()
            return {"storage_key": f"books/{book_id}/render/cover.pdf",
                    "kind": "cover", "page_count": 1, "bytes": 1,
                    "sha256": "x" * 64, "render_ms": 1}

        monkeypatch.setattr("app.services.fulfillment.render_cover",
                            watchdog_fires_mid_render)
        assert real_build is not None  # the real one is untouched

        await run_order_render(db, order.id)

        await db.refresh(order)
        assert order.status == OrderStatus.RENDERED.value

        notes = [e.note for e in (await db.execute(
            select(OrderEvent).where(OrderEvent.order_id == order.id)
            .order_by(OrderEvent.created_at)
        )).scalars().all()]
        assert any("stalled but then finished" in (n or "") for n in notes), (
            f"the recovery is not in the audit trail: {notes}")
