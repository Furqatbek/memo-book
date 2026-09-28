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

Five sources, deliberately including the last two:

* orders in `render_failed` — the render broke, retryable from the console;
* orders in `rendering` past the stall threshold — the watchdog has not got
  to them yet, and showing them a few minutes early costs nothing;
* outbox messages that gave up — the alert itself failing is exactly the
  case Telegram cannot report;
* CUSTOMERS NOTHING CAN REACH. Everybody is contacted through the Telegram
  bot; somebody who typed an email at checkout and never linked the bot is
  reachable only by mail, and there is no mail transport. That used to show
  up as one failed outbox row per message, which reads as a delivery fault
  rather than as the consequence of a decision, and arrives in ones rather
  than as a number. Now nothing is queued for them and this says how many
  they are, counted from real rows;
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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domain.states import BookStatus, OrderStatus
from app.models.book import Book
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

    items.extend(await _silenced_customers(session))
    items.extend(_configuration_gaps())
    return {"count": len(items), "items": items}


async def _silenced_customers(session: AsyncSession) -> list[dict]:
    """How many people an absent mail transport is keeping in the dark.

    Everything reaches customers through the Telegram bot. Someone who typed
    an email at checkout and never linked the bot is reachable only by mail,
    and there is no mail — so they hear nothing about their own order.

    Until now the only trace of that was one failed outbox row per message,
    which read as a delivery fault rather than as a policy, and arrived in
    ones rather than as a number. Nothing queues those messages any more, so
    this is the replacement: ONE row, and every figure in it counted from
    real rows. If it cannot be counted it is not shown — which is why there
    is no estimate here of how many of them would have read the mail anyway.
    """
    from app.services import email

    if email.configured():
        return []

    live = (await session.execute(
        select(func.count()).select_from(Order).join(
            Book, Book.id == Order.book_id
        ).where(
            Order.status.notin_((OrderStatus.DELIVERED.value,
                                 OrderStatus.CANCELLED.value,
                                 OrderStatus.REFUNDED.value)),
            Order.customer_email.is_not(None),
            Order.customer_email != "",
            Book.telegram_chat_id.is_(None),
        ))).scalar() or 0

    # Drafts are a separate population and a separate loss: these are people
    # who would have got a "your book is waiting" reminder and will not.
    drafts = (await session.execute(
        select(func.count()).select_from(Book).where(
            Book.status == BookStatus.DRAFT.value,
            Book.email.is_not(None),
            Book.email != "",
            Book.telegram_chat_id.is_(None),
        ))).scalar() or 0

    if not (live or drafts):
        return []

    parts = []
    if live:
        parts.append(f"{live} live order{'s' if live != 1 else ''}")
    if drafts:
        parts.append(f"{drafts} unfinished book{'s' if drafts != 1 else ''}")
    return [{
        "kind": "config",
        "human_ref": None,
        "status": None,
        "customer_name": None,
        "summary": f"No mail transport: {' and '.join(parts)} belong to "
                   "customers who can only be reached by email, and are "
                   "hearing nothing",
        "detail": "They gave an address at checkout and never linked the "
                  "Telegram bot. Nothing is queued for them — a message that "
                  "cannot be sent used to fail here as an alert, and worse, "
                  "spent the one reminder or review request that customer "
                  "gets. They are contacted properly the day mail works.",
        "action": "Either reach these customers by hand — the order screen "
                  "has their phone number — or get more of them onto the bot: "
                  "the offer appears on the preview and order screens, and "
                  "needs TELEGRAM_BOT_USERNAME set.",
    }]


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
                      "button that lands nowhere — so nobody can link the "
                      "bot at all, and since there is no mail transport, "
                      "that means no customer hears anything about their "
                      "order except from you.",
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
