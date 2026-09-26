"""What needs a person right now (A76).

The operator gets Telegram alerts. That covers most of it and has one hole
you cannot patch from inside Telegram: **a Telegram alert cannot tell you
that Telegram is broken.** If the bot token is wrong, the chat id is stale,
or the network to api.telegram.org is down, every alert this system raises
retries eight times and is then abandoned — including the message carrying
the print files to the printer. The order sits in `rendered`, which looks
completely healthy, and the customer waits for a book nobody was told to
print.

So the console — which is authenticated, on our own domain, and reached by a
person rather than a push — carries its own view of everything stuck. It
answers one question: is there anything I need to do that I do not already
know about?

Three sources, deliberately including the last one:

* orders in `render_failed` — the render broke, retryable from the console;
* orders in `rendering` past the stall threshold — the watchdog has not got
  to them yet, and showing them a few minutes early costs nothing;
* outbox messages that gave up — the alert itself failing is exactly the
  case Telegram cannot report;
* SETTINGS THAT HAVE SWITCHED A CUSTOMER-FACING FEATURE OFF. Several
  features fail closed on purpose rather than half-work: with no
  PUBLIC_BASE_URL the editor hides the share and contributor buttons,
  because the alternative is copying the text "/s/abc" into somebody's
  group chat. That is the right behaviour and it is invisible — the button
  is simply not there, and the only trace is one line in a startup log
  nobody reads. This is how the operator finds out, in the place they
  already look.
"""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domain.states import OrderStatus
from app.models.order import Order, OrderEvent
from app.models.outbox import OutboxMessage, OutboxStatus

# Topic -> what a person should understand from it having failed. The topic
# string alone ("order.rendered") reads like good news.
UNDELIVERED_MEANING = {
    "order.rendered": "the printer was never sent this order's files",
    "order.attention": "an alert about this order never reached you",
    "book.reminder": "a reminder email to the customer was never sent",
}


def _aware(value: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes, Postgres aware ones."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


async def _stalled_since(session: AsyncSession,
                         order: Order) -> datetime | None:
    return _aware((await session.execute(
        select(OrderEvent.created_at)
        .where(OrderEvent.order_id == order.id,
               OrderEvent.to_status == OrderStatus.RENDERING.value)
        .order_by(OrderEvent.created_at.desc()).limit(1)
    )).scalar_one_or_none())


async def needs_attention(session: AsyncSession,
                          now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    stall_after = get_settings().render_stall_after_s
    cutoff = now - timedelta(seconds=stall_after)

    items: list[dict] = []

    failed = (await session.execute(
        select(Order).where(Order.status == OrderStatus.RENDER_FAILED.value)
        .order_by(Order.created_at)
    )).scalars().all()
    for order in failed:
        why = (await session.execute(
            select(OrderEvent.note)
            .where(OrderEvent.order_id == order.id,
                   OrderEvent.to_status == OrderStatus.RENDER_FAILED.value)
            .order_by(OrderEvent.created_at.desc()).limit(1)
        )).scalar_one_or_none()
        items.append({
            "kind": "render_failed",
            "human_ref": order.human_ref,
            "status": order.status,
            "customer_name": order.customer_name,
            "summary": "the print files could not be rendered",
            "detail": why,
            "action": "Retry it, or cancel and refund.",
        })

    rendering = (await session.execute(
        select(Order).where(Order.status == OrderStatus.RENDERING.value)
    )).scalars().all()
    for order in rendering:
        started = await _stalled_since(session, order)
        if started is None or started > cutoff:
            continue
        items.append({
            "kind": "render_stalled",
            "human_ref": order.human_ref,
            "status": order.status,
            "customer_name": order.customer_name,
            "summary": f"rendering for over {stall_after // 60} minutes",
            "detail": f"started {started.isoformat()}",
            "action": "The watchdog will move this to render_failed shortly.",
        })

    undelivered = (await session.execute(
        select(OutboxMessage)
        .where(OutboxMessage.status == OutboxStatus.FAILED.value)
        .order_by(OutboxMessage.created_at)
    )).scalars().all()
    for message in undelivered:
        ref = (message.payload or {}).get("human_ref")
        items.append({
            "kind": "undelivered",
            "human_ref": ref,
            "status": None,
            "customer_name": None,
            "summary": UNDELIVERED_MEANING.get(
                message.topic, f"a {message.topic} message was never delivered"),
            "detail": message.last_error,
            "action": ("Fix the cause, then use “Send to the printer again” "
                       "on the order."),
        })

    items.extend(_configuration_gaps())
    return {"count": len(items), "items": items}


# Setting -> what is switched off, and what the operator sees instead.
#
# Every entry here is a feature that FAILS CLOSED by design. The value of
# saying so out loud is that "the button is missing" and "the button is
# broken" look identical from the outside, and the second one sends somebody
# hunting through JavaScript for an hour.
def _configuration_gaps() -> list[dict]:
    settings = get_settings()
    gaps: list[dict] = []

    if not (settings.public_base_url or "").strip():
        gaps.append({
            "kind": "config",
            "human_ref": None,
            "status": None,
            "customer_name": None,
            "summary": "PUBLIC_BASE_URL is not set, so every link that has "
                       "to work outside this server is switched off",
            "detail": "The editor hides “Share preview” and “Ask friends for "
                      "photos” entirely, rather than handing somebody a link "
                      "like “/s/abc” that opens nowhere. Draft reminders, "
                      "review requests and flip-video links are affected the "
                      "same way.",
            "action": "Set PUBLIC_BASE_URL to this deployment's origin "
                      "(e.g. https://rspixel.uz, no trailing slash) in "
                      "deploy/.env and restart. Nothing else needs changing.",
        })

    if not (settings.telegram_bot_username or "").strip():
        gaps.append({
            "kind": "config",
            "human_ref": None,
            "status": None,
            "customer_name": None,
            "summary": "TELEGRAM_BOT_USERNAME is not set, so customers are "
                       "never offered the Telegram bot",
            "detail": "The editor hides the offer rather than showing a "
                      "button that lands nowhere. A customer who never links "
                      "Telegram gets their production updates by email if "
                      "they gave an address, and nothing if they did not.",
            "action": "Set TELEGRAM_BOT_USERNAME to the bot's @name without "
                      "the @, in deploy/.env, and restart.",
        })

    if not settings.prices_confirmed:
        gaps.append({
            "kind": "config",
            "human_ref": None,
            "status": None,
            "customer_name": None,
            "summary": "PRICES_CONFIRMED is false — the shop is not taking "
                       "orders",
            "detail": "Checkout answers 503 for everybody. This is the guard "
                      "that stops a placeholder price becoming somebody's "
                      "bill.",
            "action": "Confirm the real prices, then set PRICES_CONFIRMED=true.",
        })

    return gaps
