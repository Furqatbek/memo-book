"""Executing the side effects the domain declares (A76).

`states.py` says what entering a status *means* — enqueue a render, alert the
operator, notify production — and deliberately does not know how any of that
is done. That split is right. It has exactly one failure mode: an effect can
be declared and then executed by nobody, and nothing anywhere notices.

That is not hypothetical. `Effect.ALERT_OPERATOR` was declared on entering
`render_failed` from the first day of the state machine and was never
executed by anything: the one place that saw it wrote a log line and a
comment saying the wiring would come later. A customer's paid order could
fail to render and the only trace was a log nobody reads.

So the executors live in a registry, and a test asserts that every effect the
domain can declare has one. Declaring a new effect without wiring it now
fails the suite instead of failing a customer.

TIMING IS PART OF THE CONTRACT. Two effects in this file must happen at
opposite sides of the same commit:

* An outbox row must be written in the SAME transaction as the status change
  it announces (spec Part 8). Commit them separately and a crash in between
  either announces something that did not happen or loses something that
  did.
* A queue job must NOT be dispatched until that transaction is durable.
  Enqueue first and the worker can pick the job up, read the row the
  enqueuing transaction has not committed yet, and find an order in the old
  state — a race that shows up as "the render silently did nothing", rarely,
  under load, on the money path.

`When` makes that explicit per effect rather than leaving it to whoever
writes the next caller.
"""
from collections.abc import Awaitable, Callable
from enum import StrEnum

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.states import EFFECTS_ON_ENTER, Effect
from app.models.order import Order

log = structlog.get_logger()


class When(StrEnum):
    IN_TRANSACTION = "in_transaction"
    AFTER_COMMIT = "after_commit"


Executor = Callable[[AsyncSession, Order, dict], Awaitable[None]]


async def _enqueue_render(session: AsyncSession, order: Order,
                          context: dict) -> None:
    """R8: payment is the only render trigger, and it fires exactly once per
    paid transition — the transition itself is what makes that true, since
    the state machine refuses a second one."""
    from app import queue
    from app.services.fulfillment import run_order_render

    if queue.eager():
        await run_order_render(session, order.id)
    else:
        queue.enqueue_order_render(order.id)


async def _notify_production(session: AsyncSession, order: Order,
                             context: dict) -> None:
    """Hand the printer the finished files. Enqueued in the render's own
    transaction: a Telegram outage can neither roll back a completed render
    nor lose the message announcing it."""
    from app.services import outbox

    outbox.enqueue(session, outbox.TOPIC_ORDER_RENDERED,
                   outbox.rendered_payload(order, context["book"],
                                           context["interior_key"],
                                           context["cover_key"],
                                           context.get("soft_pages")))


async def _alert_operator(session: AsyncSession, order: Order,
                          context: dict) -> None:
    """Something needs a person. Through the outbox rather than a direct
    send, so the alert inherits the same at-least-once delivery and backoff
    as everything else — an alert that is itself lost to a network blip is
    worse than none, because the log line looked like it was handled."""
    from app.services import outbox

    outbox.enqueue(session, outbox.TOPIC_ORDER_ATTENTION,
                   outbox.attention_payload(
                       order,
                       reason=context.get("reason", "needs attention"),
                       detail=context.get("detail")))


EXECUTORS: dict[Effect, tuple[When, Executor]] = {
    Effect.ENQUEUE_RENDER: (When.AFTER_COMMIT, _enqueue_render),
    Effect.NOTIFY_PRODUCTION: (When.IN_TRANSACTION, _notify_production),
    Effect.ALERT_OPERATOR: (When.IN_TRANSACTION, _alert_operator),
}


def declared_effects() -> set[Effect]:
    """Every effect the state machine can hand a caller."""
    return {e for effects in EFFECTS_ON_ENTER.values() for e in effects}


async def run_effects(session: AsyncSession, order: Order,
                      effects: tuple[Effect, ...], when: When,
                      **context) -> None:
    """Run the effects that belong at this side of the commit.

    Callers pass the full effect tuple both times and this picks; splitting
    the tuple at the call site is how one gets forgotten.
    """
    for effect in effects:
        registered = EXECUTORS.get(effect)
        if registered is None:
            # Unreachable while the registry test passes. If it ever is
            # reached, losing the effect quietly is the one thing that must
            # not happen — this is the money path.
            raise RuntimeError(
                f"{effect} is declared by the state machine but no executor "
                "is registered for it")
        effect_when, run = registered
        if effect_when is not when:
            continue
        await run(session, order, context)
        log.info("effect.ran", effect=effect.value, when=when.value,
                 order=order.human_ref)
