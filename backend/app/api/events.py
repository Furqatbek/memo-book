"""The one door a browser may push a funnel event through — Change 3.

Everything the server can observe for itself is emitted where it happens.
Three things it genuinely cannot see arrive here instead: somebody reading
the marketing page, opening the editor, and moving to the checkout screen
— that last one is a screen swap in the editor with no server call behind
it at all.

What a caller can do is deliberately small:

  * it may name an event from a fixed set and nothing else. An unknown or
    server-only type is refused, so this cannot become a back door for
    forging `payment_succeeded`;
  * the row is written, timestamped and attributed by the server from the
    session cookie, so the caller cannot claim a different session or a
    campaign it did not come from;
  * `checkout_opened` needs the book's edit token, and is once-per-book, so
    replaying it cannot inflate the step it measures.

An ad-blocker or a dropped request still costs us these events. That is a
known and accepted under-count on exactly two ends of the funnel, and it is
why every step in between is measured server-side instead.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.tracking import tracking_of
from app.db.session import get_session
from app.domain.events import CLIENT_REPORTABLE, EventType
from app.rate_limit import rate_limit
from app.services import funnel
from app.services.books import get_book_authed

router = APIRouter(prefix="/api/v1/events", tags=["events"],
                   dependencies=[rate_limit("events",
                                            lambda s: s.rate_limit_events_per_min)])

Session = Annotated[AsyncSession, Depends(get_session)]

_NEEDS_BOOK = {EventType.CHECKOUT_OPENED}


class EventIn(BaseModel):
    type: str = Field(max_length=32)
    book_id: uuid.UUID | None = None
    # Only ever a reminder day today; kept tiny on purpose so this cannot
    # become a channel for shipping arbitrary blobs into the database.
    day: int | None = Field(default=None, ge=1, le=60)


@router.post("", status_code=202)
async def record(body: EventIn, request: Request, session: Session,
                 x_edit_token: Annotated[str | None, Header()] = None) -> dict:
    """Always 202. The browser is told we heard, never whether we stored it.

    Whether a row was written is not the caller's business — it leaks
    whether an event had already been recorded for that book, and there is
    nothing useful a page could do with the answer anyway.
    """
    try:
        event = EventType(body.type)
    except ValueError:
        raise HTTPException(status_code=422, detail="unknown event") from None
    if event not in CLIENT_REPORTABLE:
        # Emitted server-side where it happens; a browser may not claim it.
        raise HTTPException(status_code=422, detail="unknown event")

    book_id = None
    if event in _NEEDS_BOOK:
        if not body.book_id or not x_edit_token:
            raise HTTPException(status_code=422, detail="unknown event")
        # Proves the caller holds this book, and 404s exactly as every other
        # book route does when it does not.
        book = await get_book_authed(session, body.book_id, x_edit_token)
        book_id = book.id

    sid, attribution = tracking_of(request)
    properties = {"day": body.day} if body.day else {}
    await funnel.emit(session, event, session_id=sid, book_id=book_id,
                      properties=properties, attribution=attribution)
    await session.commit()
    return {"ok": True}
