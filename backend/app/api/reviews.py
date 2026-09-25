"""The review form — CR-003-9.

One link, sent once, seven days after the book arrived. Behind it is a
form and nothing else: no account, no order detail, no price, no way to
reach the book. A review link that leaked would let a stranger write a
review nobody publishes without reading it.

THE PERMISSION BOX IS NOT A FORMALITY. It is unticked, it is the only
thing that grants publication, and submitting without it stores a private
message rather than a review. Nothing here publishes anything in any case
— the site's list is hand-curated, and a person copies an approved review
into it.
"""
import html
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_session
from app.rate_limit import rate_limit
from app.services import reviews as svc

router = APIRouter(tags=["reviews"])

Session = Annotated[AsyncSession, Depends(get_session)]

NOINDEX = {"X-Robots-Tag": "noindex, nofollow",
           "Referrer-Policy": "no-referrer"}

_GONE = HTTPException(status_code=404, detail="Not Found")

Throttle = rate_limit("share", lambda s: s.rate_limit_share_per_min)


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=svc.TEXT_MAX)
    display_name: str | None = Field(default=None, max_length=svc.NAME_MAX)
    city: str | None = Field(default=None, max_length=svc.NAME_MAX)
    lang: str | None = Field(default=None, max_length=8)
    # Defaults to FALSE. A field that defaulted to true would turn every
    # slip of a client into permission nobody gave.
    may_publish: bool = False


@router.post("/api/v1/reviews/{token}", dependencies=[Throttle])
async def submit(token: str, body: ReviewIn, session: Session) -> dict:
    review = await svc.find(session, token)
    if review is None:
        raise _GONE
    await svc.submit(session, review, text=body.text,
                     display_name=body.display_name, city=body.city,
                     lang=body.lang, may_publish=body.may_publish)
    return {"status": "thank you", "may_publish": review.may_publish}


@router.post("/api/v1/reviews/{token}/photo", dependencies=[Throttle],
             status_code=201)
async def attach_photo(token: str, session: Session,
                       photo: UploadFile = File(...)) -> dict:
    """Their photograph of the book. Optional, and resized and stripped of
    its EXIF on the way in — the same treatment the operator's press photos
    get, for the same reason: this one was taken at home."""
    from app.services.progress_photos import ProgressPhotoError, store

    review = await svc.find(session, token)
    if review is None:
        raise _GONE
    raw = await photo.read()
    try:
        key = await store(f"review-{str(review.order_id)[:8]}", raw)
    except ProgressPhotoError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    review.photo_key = key
    await session.commit()
    return {"stored": True}


def _page(token: str, already: bool) -> str:
    settings = get_settings()
    base = (settings.public_base_url or "").rstrip("/")
    done = ("<p class=\"share-note\">You have already sent this — thank you. "
            "Sending it again replaces what you wrote.</p>" if already else "")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>How is your book? — RS Pixel</title>
<link rel="stylesheet" href="{base}/assets/style.css">
</head>
<body class="share-body">
<main class="share-wrap">
  <header class="share-head"><a class="brand" href="{base}/">RS Pixel</a></header>
  <h1 class="share-title">How is your book?</h1>
  <p class="share-sub">An honest one is worth more to us than a kind one.
     Say what you actually thought.</p>
  {done}
  <label class="od-note">
    <span class="muted small">Your review</span>
    <textarea id="r-text" rows="6" maxlength="{svc.TEXT_MAX}"></textarea>
  </label>
  <label class="od-note">
    <span class="muted small">Your name, as you would like it shown
      (optional)</span>
    <input id="r-name" maxlength="{svc.NAME_MAX}">
  </label>
  <label class="od-note">
    <span class="muted small">City (optional)</span>
    <input id="r-city" maxlength="{svc.NAME_MAX}">
  </label>
  <label class="od-note">
    <span class="muted small">A photo of the book (optional)</span>
    <input id="r-photo" type="file" accept="image/*">
  </label>
  <!-- Unticked, and it stays unticked. This box is the only thing that
       grants publication; without it what is written above is a private
       message to us and is never shown to anybody. -->
  <p><label><input type="checkbox" id="r-publish">
    You may publish this review, with my name as written above, on your
    website.</label></p>
  <p><button class="btn btn-primary" id="r-send" type="button">Send</button></p>
  <div id="r-status" class="share-note" aria-live="polite"></div>
</main>
<script src="{base}/assets/review.js" data-token="{html.escape(token)}"></script>
</body>
</html>
"""


@router.get("/r/{token}", response_class=HTMLResponse, dependencies=[Throttle])
async def form(token: str, request: Request, session: Session) -> HTMLResponse:
    review = await svc.find(session, token)
    if review is None:
        raise _GONE
    return HTMLResponse(_page(token, review.submitted_at is not None),
                        headers=NOINDEX)
