"""The funnel report — Change 3.

One JSON endpoint behind the admin token. No UI in scope: the point of
this change is to be able to compute cost of acquisition per channel, and
that needs numbers a spreadsheet can read, not a dashboard.

Counting rule, and it matters: every step is counted as DISTINCT BOOKS,
except the two that happen before a book exists, which are counted as
distinct sessions. Counting rows would let one person who refreshed the
editor six times outweigh six people who each opened it once, and every
rate below them would be wrong in a direction that flatters us.
"""
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import require_admin
from app.db.session import get_session
from app.domain.events import FUNNEL_ORDER, EventType
from app.models.funnel_event import FunnelEvent
from app.rate_limit import rate_limit

router = APIRouter(prefix="/api/v1/internal", tags=["internal"],
                   dependencies=[rate_limit("admin",
                                            lambda s: s.rate_limit_admin_per_min)])

Session = Annotated[AsyncSession, Depends(get_session)]
Admin = Depends(require_admin)

# Before a book exists there is nothing to count but the visitor.
BY_SESSION = {EventType.SITE_VISIT, EventType.EDITOR_OPENED}


def _subject(event: EventType):
    return (FunnelEvent.session_id if event in BY_SESSION else FunnelEvent.book_id)


async def _counts(session: AsyncSession, start: datetime | None,
                  end: datetime | None, campaign: str | None,
                  group_by_campaign: bool = False) -> dict:
    out: dict = {}
    for event in FUNNEL_ORDER:
        stmt = select(func.count(func.distinct(_subject(event)))).where(
            FunnelEvent.event_type == event.value)
        if start:
            stmt = stmt.where(FunnelEvent.occurred_at >= start)
        if end:
            stmt = stmt.where(FunnelEvent.occurred_at <= end)
        if campaign:
            stmt = stmt.where(FunnelEvent.campaign == campaign)
        out[event.value] = int((await session.execute(stmt)).scalar() or 0)
    return out


def _rates(counts: dict) -> dict:
    """Each step against the one before it, and against the top.

    Zero denominators answer `None` rather than 0.0: "no data" and "nobody
    converted" are different facts, and a report that renders them the same
    invites the wrong decision about where the money went.
    """
    rates: dict = {}
    top = counts.get(EventType.SITE_VISIT.value, 0)
    previous = None
    for event in FUNNEL_ORDER:
        n = counts.get(event.value, 0)
        if previous is not None:
            prev_name, prev_n = previous
            rates[f"{prev_name}_to_{event.value}"] = (
                round(n / prev_n, 4) if prev_n else None)
        rates[f"{event.value}_of_site_visit"] = round(n / top, 4) if top else None
        previous = (event.value, n)
    return rates


@router.get("/funnel", dependencies=[Admin])
async def funnel_report(
    session: Session,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: Annotated[datetime | None, Query()] = None,
    campaign: Annotated[str | None, Query(max_length=128)] = None,
) -> dict:
    """Counts, conversion rates, and the same broken down by campaign."""
    # A naive datetime from the query string would compare as UTC against
    # tz-aware rows on Postgres and raise; make the assumption explicit.
    if from_ and from_.tzinfo is None:
        from_ = from_.replace(tzinfo=UTC)
    if to and to.tzinfo is None:
        to = to.replace(tzinfo=UTC)

    counts = await _counts(session, from_, to, campaign)

    campaigns_stmt = select(FunnelEvent.campaign).where(
        FunnelEvent.campaign.is_not(None)).distinct()
    if from_:
        campaigns_stmt = campaigns_stmt.where(FunnelEvent.occurred_at >= from_)
    if to:
        campaigns_stmt = campaigns_stmt.where(FunnelEvent.occurred_at <= to)
    names = [c for (c,) in (await session.execute(campaigns_stmt)).all() if c]

    by_campaign = {}
    for name in sorted(names):
        if campaign and name != campaign:
            continue
        c = await _counts(session, from_, to, name)
        by_campaign[name] = {"counts": c, "conversion_rates": _rates(c)}

    return {
        **counts,
        "conversion_rates": _rates(counts),
        "by_campaign": by_campaign,
        "window": {"from": from_.isoformat() if from_ else None,
                   "to": to.isoformat() if to else None,
                   "campaign": campaign},
        # Said out loud in the payload so nobody reads the top of the funnel
        # as gospel: these two come from the browser and an ad-blocker eats
        # some of them. Everything below book_started is server-observed.
        "counting": {
            "site_visit": "distinct sessions, client-reported",
            "editor_opened": "distinct sessions, client-reported",
            "checkout_opened": "distinct books, client-reported",
            "everything_else": "distinct books, server-observed",
        },
    }
