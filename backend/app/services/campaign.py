"""The campaign window and what may honestly be said about it — CR-003-7,
CR-003-8.

Two numbers reach a customer from here, and both are computed rather than
written down:

  DAYS LEFT TO ORDER.  The deadline is the date the book must ARRIVE, so
  the date to order by is that minus the days production actually takes.
  Counted on the server, because a browser's clock belongs to the browser
  and "order within 6 days" is a promise.

  PLACES REMAINING.  Real paid orders against a configured ceiling, or
  nothing at all.

    A fabricated scarcity counter is the practice this product exists in
    contrast to. The rule is the founder's and it is absolute: every
    scarcity or availability figure shown to a customer is computed from
    real data, or it does not ship.

  So the ceiling is UNSET by default. With no ceiling there is no number,
  no banner and no closure — not a made-up ceiling, not "limited places",
  nothing. Setting MONTHLY_CAPACITY is a statement by somebody who has
  spoken to the printer, and the number then shown is orders actually paid
  for, counted.

When places run out the campaign checkout closes and says so, because a
counter that reaches zero and keeps selling is a lie told slowly.
"""
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domain.states import OrderStatus
from app.models.order import Order

log = structlog.get_logger()

# A place is taken by a book the printer still OWES: paid for, and not yet
# out of the door. That is the honest reading of "capacity", because what
# the printer quoted is throughput — how many they can make in a month —
# and a book already shipped is off the press and consuming nothing.
#
# Two exclusions worth stating out loud, because each is a temptation in
# the flattering direction:
#
#   pending_payment is NOT a place. Plenty of those are never paid, and
#   counting them would make "places remaining" smaller than the truth —
#   which is the direction that sells books, and therefore the one to be
#   most careful about.
#
#   shipped and delivered are NOT places. They are finished work. Leaving
#   them in would make the counter ratchet downwards for ever until
#   somebody reset it by hand, which is a scarcity figure that stops
#   describing anything.
TAKEN_STATUSES = (
    OrderStatus.PAID.value,
    OrderStatus.RENDERING.value,
    OrderStatus.RENDER_FAILED.value,
    OrderStatus.RENDERED.value,
    OrderStatus.SENT_TO_PRODUCTION.value,
    OrderStatus.PRINTING.value,
    OrderStatus.BINDING.value,
    OrderStatus.QUALITY_CHECK.value,
)


@dataclass(frozen=True)
class Window:
    """What is true about the campaign right now. Every field is either a
    computed fact or None; nothing here is decorative."""

    label: str
    deadline: date              # the date the book must ARRIVE
    order_by: date              # deadline minus production
    days_left: int              # whole days from today to order_by
    capacity: int | None        # the ceiling, if somebody set one
    taken: int | None           # paid orders inside the window
    places_left: int | None     # capacity - taken, never below zero

    @property
    def open(self) -> bool:
        if self.days_left < 0:
            return False
        return self.places_left is None or self.places_left > 0

    @property
    def sold_out(self) -> bool:
        return self.places_left is not None and self.places_left <= 0

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "deadline": self.deadline.isoformat(),
            "order_by": self.order_by.isoformat(),
            "days_left": self.days_left,
            "open": self.open,
            "sold_out": self.sold_out,
            # Absent rather than null when there is no ceiling: a client
            # that renders `places_left: null` as "0 places left" is a bug
            # waiting to happen, and this shape makes it impossible.
            **({"places_left": self.places_left, "capacity": self.capacity}
               if self.places_left is not None else {}),
        }


def _today(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).date()


def configured() -> tuple[date, str, int] | None:
    """(deadline, label, production days), or None when no campaign is set.

    A malformed date switches the campaign OFF rather than guessing. The
    banner says "order within N days"; an N derived from a date somebody
    typed wrongly is a promise made by accident.
    """
    settings = get_settings()
    raw = (settings.campaign_deadline or "").strip()
    if not raw:
        return None
    try:
        deadline = date.fromisoformat(raw)
    except ValueError:
        log.warning("campaign.bad_deadline", value=raw[:32])
        return None
    label = (settings.campaign_label or "").strip() or "the deadline"
    return deadline, label, max(0, settings.production_days)


async def _taken(session: AsyncSession) -> int:
    """How many books the printer currently owes.

    No date filter, deliberately. Filtering by the deadline's own month
    would count nothing at all — a New Year order is placed in November —
    and any other window is a guess at when a campaign began. The queue is
    a fact that needs no window: it is what somebody would count by
    looking at the console.
    """
    return int((await session.execute(
        select(func.count(Order.id)).where(Order.status.in_(TAKEN_STATUSES))
    )).scalar() or 0)


async def current(session: AsyncSession,
                  now: datetime | None = None) -> Window | None:
    """The campaign as it stands, or None if there is no campaign.

    None is also the answer once the order-by date has passed, because a
    banner counting down to a date in the past is worse than no banner:
    it tells a customer the product is unattended.
    """
    config = configured()
    if config is None:
        return None
    deadline, label, production_days = config
    today = _today(now)
    order_by = deadline - timedelta(days=production_days)
    days_left = (order_by - today).days
    if days_left < 0:
        return None

    settings = get_settings()
    capacity = settings.monthly_capacity or None
    taken = places_left = None
    if capacity:
        taken = await _taken(session)
        places_left = max(0, capacity - taken)

    return Window(label=label, deadline=deadline, order_by=order_by,
                  days_left=days_left, capacity=capacity, taken=taken,
                  places_left=places_left)


def banner_line(window: Window) -> str:
    """The sentence shown in the editor, in English. The editor translates
    it from the numbers; this is what the reminder messages carry, and what
    a test can read."""
    if window.days_left == 0:
        return f"Today is the last day to order for {window.label}."
    days = "day" if window.days_left == 1 else "days"
    return (f"Order within {window.days_left} {days} to receive your book "
            f"before {window.label}.")


async def seasonal_note(session: AsyncSession,
                        now: datetime | None = None) -> str:
    """The line appended to reminder messages during the window (CR-003-7).

    Prefers the computed sentence over the hand-written
    REMINDER_SEASONAL_NOTE, because the hand-written one cannot count down
    and will still say "order by 25 November" on the 26th.
    """
    window = await current(session, now)
    if window is None or not window.open:
        return (get_settings().reminder_seasonal_note or "").strip()
    return banner_line(window)
