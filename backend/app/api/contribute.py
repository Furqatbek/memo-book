"""The contributor link's endpoints — CR-003-6.

Two audiences again, and the split is sharper here than anywhere else in
this codebase:

  * the OWNER, holding the edit token, mints and revokes;
  * a CONTRIBUTOR, holding only the contributor token, may add photographs
    and read one count. Nothing else. Not the book, not the pages, not the
    owner, not the price.

This is an UNAUTHENTICATED endpoint that accepts files. Everything below
assumes the token has been pasted into a group chat, because it has.

Unknown, revoked, expired and no-longer-a-draft all answer 404. A
contributor page must not be an oracle for which books exist.
"""
import html
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app import queue
from app.api.tracking import record, session_id_of
from app.config import get_settings
from app.db.session import get_session
from app.domain.events import EventType
from app.rate_limit import rate_limit
from app.services import contribute as svc
from app.services import photos as photos_svc

router = APIRouter(tags=["contribute"])

Session = Annotated[AsyncSession, Depends(get_session)]
EditToken = Annotated[str, Header(alias="X-Edit-Token")]

NOINDEX = {"X-Robots-Tag": "noindex, nofollow",
           "Referrer-Policy": "no-referrer"}

_GONE = HTTPException(status_code=404, detail="Not Found")

Throttle = rate_limit("contribute", lambda s: s.rate_limit_contribute_per_min)


# ---------------------------------------------------------------- owner ---

@router.post("/api/v1/books/{book_id}/contributor-link")
async def create_link(book_id: uuid.UUID, request: Request, session: Session,
                      x_edit_token: EditToken) -> dict:
    book, token = await svc.create(session, book_id, x_edit_token)
    await record(request, session, EventType.CONTRIBUTOR_LINK_CREATED,
                 book_id=book.id)
    await session.commit()
    # The only moment this token exists in readable form. It is not stored
    # anywhere in this shape and cannot be shown again.
    return {"contributor_token": token, "url": svc.contribute_url(token),
            **await svc.usage(session, book_id)}


@router.delete("/api/v1/books/{book_id}/contributor-link", status_code=204)
async def revoke_link(book_id: uuid.UUID, session: Session,
                      x_edit_token: EditToken) -> Response:
    await svc.revoke(session, book_id, x_edit_token)
    await session.commit()
    return Response(status_code=204)


# ---------------------------------------------------------- contributor ---

@router.get("/api/v1/contribute/{token}", dependencies=[Throttle])
async def contributor_view(token: str, session: Session,
                           response: Response) -> dict:
    """Everything a contributor may know. Read it twice — what is missing
    is missing on purpose."""
    book = await svc.find(session, token)
    if book is None:
        raise _GONE
    response.headers.update(NOINDEX)
    return await svc.public_view(session, book)


class ContributorUploadIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(max_length=255)
    mime: str = Field(max_length=64)
    bytes: int
    # Self-declared, never trusted, only a label for the owner.
    contributor_name: str | None = Field(default=None, max_length=60)


@router.post("/api/v1/contribute/{token}/upload-url", dependencies=[Throttle])
async def contributor_upload_url(token: str, body: ContributorUploadIn,
                                 request: Request, session: Session) -> dict:
    book = await svc.find(session, token)
    if book is None:
        raise _GONE
    who = svc.contributor_id(session_id_of(request))
    photo, upload = await photos_svc.issue_contributor_upload_url(
        session, book, who, svc.clean_name(body.contributor_name),
        body.mime, body.bytes)
    # No storage key in the answer, unlike the owner's version of this
    # endpoint: a contributor has no use for one and it is the sort of
    # detail that turns into a way to guess at other keys. The key IS inside
    # `upload.fields`, because the POST policy signs it — but there it is
    # part of a credential for one object rather than a fact about our
    # naming scheme.
    return {"upload": upload, "photo_id": photo.id}


class ContributorCompleteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    photo_id: uuid.UUID
    taken_at_exif: str | None = Field(default=None, max_length=32)


@router.post("/api/v1/contribute/{token}/complete", dependencies=[Throttle])
async def contributor_complete(token: str, body: ContributorCompleteIn,
                               request: Request, session: Session) -> dict:
    book = await svc.find(session, token)
    if book is None:
        raise _GONE
    who = svc.contributor_id(session_id_of(request))
    photo = await photos_svc.complete_contributor_upload(
        session, book, who, body.photo_id, taken_at_exif=body.taken_at_exif)
    if photo.status == "processing":
        if queue.eager():
            await photos_svc.ingest_photo(session, photo.id)
        else:
            queue.enqueue_ingest(photo.id)
    await record(request, session, EventType.CONTRIBUTOR_UPLOAD,
                 book_id=book.id, properties={"contributor": who[:12]})
    await session.commit()
    return {"status": "processing"}


# ----------------------------------------------------------- the page ---

def _page(view: dict, token: str) -> str:
    settings = get_settings()
    base = (settings.public_base_url or "").rstrip("/")
    title = html.escape(view["book_title"] or "a photo book")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Add your photos — RS Pixel</title>
<link rel="stylesheet" href="{base}/assets/style.css?v=20260926a">
<!-- No og:image and no book detail in the card. A contributor link is a
     working link sent to one person, not something meant to look good
     when it is forwarded onwards. -->
<meta property="og:title" content="Add your photos">
<meta property="og:description" content="Someone is making a photo book and
 would like your pictures in it.">
</head>
<body class="share-body">
<main class="share-wrap">
  <header class="share-head"><a class="brand" href="{base}/">RS Pixel</a></header>
  <h1 class="share-title">Add your photos to “{title}”</h1>
  <p class="share-sub" id="c-sub"></p>
  <label class="od-note">
    <span class="muted small">Your name (optional) — so they know whose
      pictures are whose</span>
    <input id="c-name" maxlength="60" autocomplete="name">
  </label>
  <p><input id="c-files" type="file" accept="image/*" multiple></p>
  <div id="c-status" class="share-note" aria-live="polite"></div>
  <p class="muted small">
    You are adding photos only. You will not be able to see or change the
    book, and nothing here costs anything.
  </p>
  <div class="share-cta">
    <p>Making one yourself is the same thing from the other side.</p>
    <a class="btn btn-primary" id="c-cta"
       href="{base}/editor/?utm_source=contribute&utm_medium=share&utm_campaign=contribute">
      Make a book of your own
    </a>
  </div>
</main>
<script src="{base}/assets/contribute.js?v=20260926a" data-token="{html.escape(token)}"></script>
</body>
</html>
"""


@router.get("/c/{token}", response_class=HTMLResponse, dependencies=[Throttle])
async def contributor_page(token: str, session: Session) -> HTMLResponse:
    book = await svc.find(session, token)
    if book is None:
        raise _GONE
    view = await svc.public_view(session, book)
    return HTMLResponse(_page(view, token), headers=NOINDEX)
