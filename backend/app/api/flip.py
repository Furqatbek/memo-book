"""The flip video's one public door — CR-003-5.

`GET /v/{token}` redirects to a presigned URL for the MP4. Three reasons it
is not simply a presigned link pasted into the message:

  * a presigned URL cannot be counted, and FLIP_VIDEO_DOWNLOADED is the
    only way to know whether any of this was worth doing;
  * a presigned URL expires while the message is still sitting unread in a
    chat, and then the customer taps a dead link at the exact moment they
    were most pleased with us;
  * a presigned URL cannot be revoked.

What it reaches is a 1080x1920 video and nothing else. There is no print
file, no original and no contact detail behind this token.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.tracking import record
from app.db.session import get_session
from app.domain.events import EventType
from app.rate_limit import rate_limit
from app.services import flip_video as svc

router = APIRouter(tags=["flip"])

Session = Annotated[AsyncSession, Depends(get_session)]

_GONE = HTTPException(status_code=404, detail="Not Found")


@router.get("/v/{token}",
            dependencies=[rate_limit("share",
                                     lambda s: s.rate_limit_share_per_min)])
async def download(token: str, request: Request,
                   session: Session) -> RedirectResponse:
    from app import storage
    from sqlalchemy import select

    from app.models.order import Order

    video = await svc.find(session, token)
    if video is None:
        raise _GONE

    order = (await session.execute(
        select(Order).where(Order.id == video.order_id))).scalar_one()
    await svc.count_download(session, video)
    await record(request, session, EventType.FLIP_VIDEO_DOWNLOADED,
                 book_id=order.book_id)
    await session.commit()

    url = storage.presign_get(video.storage_key, expires_in=svc.URL_EXPIRY_S)
    # 302, not 301: the presigned URL is different every time, and a
    # permanently cached redirect would hand somebody a link that has
    # since expired.
    return RedirectResponse(url, status_code=302, headers={
        "X-Robots-Tag": "noindex, nofollow",
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store",
    })
