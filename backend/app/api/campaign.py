"""What the editor is told about the campaign — CR-003-7, CR-003-8.

Public and identical for everybody, so nothing here is throttled or
guarded: it is the shop window. The only thing worth saying twice is that
every number in the answer is computed on the SERVER. A countdown driven
by the browser's clock is a promise made by a machine whose owner can set
it to any date they like, and "order within 6 days" is a promise about a
printer's schedule.

When there is no campaign the answer is `{"campaign": null}` rather than an
absent key or an error, so the editor has one shape to render and one
branch to take.
"""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.services import campaign as svc

router = APIRouter(prefix="/api/v1", tags=["campaign"])

Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("/campaign")
async def campaign(session: Session) -> dict:
    """The campaign, and whether links may be offered at all.

    `sharing` rides along here rather than in an endpoint of its own for
    one practical reason: the editor asks this once on entry and both
    answers decide what the bar shows, so a second round trip would buy
    nothing. It is one boolean, and it is about the same thing — what this
    deployment is able to promise a customer right now.

    Without PUBLIC_BASE_URL a share link is the text `/s/abc`, which is
    not a link in a chat window. The editor hides the buttons rather than
    handing somebody a broken one, the same way the Telegram offer hides
    itself when no bot is configured (Change 2).
    """
    from app.services.public_links import configured

    window = await svc.current(session)
    return {"campaign": window.as_dict() if window else None,
            "sharing": {"available": configured()}}
