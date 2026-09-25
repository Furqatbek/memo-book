"""Writing funnel events — Change 3.

The rule that shapes this whole module: **recording an event must never
break the thing it is recording.** Analytics that can fail a checkout is
worth less than no analytics at all.

That rules out the obvious implementation. Inserting into the caller's
session directly means a unique-violation — which is the NORMAL outcome
here, every time a once-only event is emitted twice — aborts the enclosing
transaction, and the customer's order fails because we tried to count it.

It also rules out the other obvious one. Opening a separate session and
writing outside the caller's transaction would survive a rollback, so a
book whose creation was rolled back would still report `book_started`, and
the funnel would count books that do not exist.

So: a SAVEPOINT. The insert runs nested inside the caller's transaction.
If it fails, only the savepoint unwinds and the caller's work is untouched;
if the caller later rolls back, the event goes with it, which is right —
the step never happened. Anything unexpected is logged and swallowed.
"""
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.events import EventType
from app.models.funnel_event import FunnelEvent

log = structlog.get_logger()

# Attribution travels with the request; see app/api/deps.py. A missing one
# is normal (direct traffic), not an error.
ATTRIBUTION_KEYS = ("source", "medium", "campaign")


async def emit(session: AsyncSession, event: EventType, *,
               session_id: str | None,
               book_id: uuid.UUID | None = None,
               properties: dict | None = None,
               attribution: dict | None = None,
               occurred_at: datetime | None = None) -> bool:
    """Record one event. Returns whether a row was written.

    `False` is an ordinary answer, not a failure: it is what a second
    `book_started` for the same book looks like, and the caller is expected
    to ignore it.
    """
    if not session_id:
        # Every event belongs to a session. Without one there is nothing to
        # attribute and nothing to de-duplicate a funnel by, so it is
        # dropped rather than written as an orphan that skews the counts.
        log.warning("funnel.no_session", funnel_event=event.value)
        return False

    attribution = attribution or {}
    row = FunnelEvent(
        id=uuid.uuid4(),
        book_id=book_id,
        session_id=session_id[:64],
        event_type=event.value,
        properties=properties or {},
        source=(attribution.get("source") or None),
        medium=(attribution.get("medium") or None),
        campaign=(attribution.get("campaign") or None),
        occurred_at=occurred_at or datetime.now(UTC),
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
        return True
    except SQLAlchemyError:
        # The expected case: the unique index refused a duplicate of a
        # once-per-book event. Debug rather than warning, because a user who
        # refreshes is not a fault and this would otherwise be the noisiest
        # line in the log.
        log.debug("funnel.duplicate_or_failed", funnel_event=event.value,
                  book_id=str(book_id) if book_id else None)
        return False
    except Exception:  # noqa: BLE001 — nothing here may reach the caller
        log.exception("funnel.emit_failed", funnel_event=event.value)
        return False


async def book_tracking(session: AsyncSession,
                        book_id: uuid.UUID) -> tuple[str | None, dict]:
    """The session and campaign a book belongs to, from its own first event.

    Payments arrive on a webhook from the provider and abandonment is
    noticed by a nightly job: neither carries the customer's cookie. Taking
    the attribution off the book's earliest event is what keeps the
    campaign attached all the way to the money — which is the entire point
    of the change. Without it, every payment would read as direct traffic
    and cost per acquisition could not be computed at all.
    """
    from sqlalchemy import select

    row = (await session.execute(
        select(FunnelEvent)
        .where(FunnelEvent.book_id == book_id)
        .order_by(FunnelEvent.occurred_at.asc())
        .limit(1)
    )).scalar_one_or_none()
    if row is None:
        return None, {}
    return row.session_id, {"source": row.source, "medium": row.medium,
                            "campaign": row.campaign}


async def emit_for_book(session: AsyncSession, event: EventType,
                        book_id: uuid.UUID, **kw) -> bool:
    """Emit against a book when there is no request to read a cookie from."""
    sid, attribution = await book_tracking(session, book_id)
    return await emit(session, event, session_id=sid, book_id=book_id,
                      attribution=attribution, **kw)


async def emit_many(session: AsyncSession, events: list[EventType], **kw) -> int:
    """Several events for one moment — a layout save can cross both the
    half-designed and design-completed lines at once."""
    written = 0
    for event in events:
        written += bool(await emit(session, event, **kw))
    return written
