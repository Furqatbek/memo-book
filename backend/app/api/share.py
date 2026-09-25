"""The share link, and the page a stranger sees — CR-003-1.

Two audiences, two very different surfaces:

  * the OWNER, holding the edit token, mints and revokes the link;
  * a VIEWER, holding only the share token, gets page pictures and a way
    to make a book of their own.

The viewer's side is rendered server-side rather than served as another
static page, for one reason: the Open Graph tags have to carry THIS book's
cover. The link is going to be pasted into Telegram, and that preview card
is the entire advertisement — a generic card would waste the share.

`X-Robots-Tag: noindex` on everything a token reaches. Customers'
photographs of their families must never turn up in a search result.
"""
import html
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.tracking import record
from app.config import get_settings
from app.db.session import get_session
from app.domain.events import EventType
from app.rate_limit import rate_limit
from app.services import share as svc

router = APIRouter(tags=["share"])

Session = Annotated[AsyncSession, Depends(get_session)]
EditToken = Annotated[str, Header(alias="X-Edit-Token")]

NOINDEX = {"X-Robots-Tag": "noindex, nofollow",
           "Referrer-Policy": "no-referrer"}

# Unknown, revoked and expired all answer the same way: a share page must
# not be an oracle for which tokens exist.
_GONE = HTTPException(status_code=404, detail="Not Found")

# Where a book made from a shared link came from. The same three values go
# on the page's own CTA link, so a viewer who arrives with an attribution
# already stored and one who does not are counted the same way.
SHARE_ATTRIBUTION = {"source": "share", "medium": "share",
                     "campaign": "share"}
SHARE_QUERY = "&".join(f"utm_{k}={v}" for k, v in SHARE_ATTRIBUTION.items())


@router.post("/api/v1/books/{book_id}/share")
async def create_share(book_id: uuid.UUID, request: Request, session: Session,
                       x_edit_token: EditToken) -> dict:
    book = await svc.create(session, book_id, x_edit_token)
    await record(request, session, EventType.SHARE_LINK_CREATED, book_id=book.id)
    await session.commit()
    # Rendered inline: the owner pressed a button and is waiting, and a
    # link that opens on "preparing…" is a link they will not send.
    if svc.is_stale(book):
        await svc.render(session, book)
    return {"share_token": book.share_token,
            "share_url": svc.share_url(book.share_token),
            "view_count": book.share_view_count or 0}


@router.delete("/api/v1/books/{book_id}/share", status_code=204)
async def revoke_share(book_id: uuid.UUID, session: Session,
                       x_edit_token: EditToken) -> Response:
    await svc.revoke(session, book_id, x_edit_token)
    await session.commit()
    return Response(status_code=204)


@router.get("/api/v1/shared/{share_token}",
            dependencies=[rate_limit("share",
                                     lambda s: s.rate_limit_share_per_min)])
async def shared_json(share_token: str, request: Request,
                      session: Session, response: Response) -> dict:
    """The pages, for the viewer's page-turn. 404 for anything else."""
    book = await svc.find(session, share_token)
    if book is None:
        raise _GONE
    response.headers.update(NOINDEX)
    if svc.is_stale(book):
        # The owner has edited since this was last drawn. Re-render rather
        # than show a stale book: the link is meant to be live, and "works
        # on an incomplete book" is the main use case.
        await svc.render(session, book)
    await svc.count_view(session, book)
    await record(request, session, EventType.SHARE_LINK_VIEWED, book_id=book.id,
                 properties={"referrer": (request.headers.get("referer") or "")[:200]})
    await session.commit()
    return await svc.view(session, book)


def _page(book, token: str, cover_url: str) -> str:
    """The shell. Everything visible is drawn by the client from the JSON
    above; what matters here is the head."""
    settings = get_settings()
    base = (settings.public_base_url or "").rstrip("/")
    cover = book.layout.get("cover") or {}
    title = html.escape((cover.get("title") or "").strip() or "A photo book")
    desc = html.escape(
        f"{book.page_count} pages, made in RS Pixel. "
        "Have a look — and make one of your own.")
    url = f"{base}/s/{token}"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{title} — RS Pixel</title>
<meta name="description" content="{desc}">
<link rel="stylesheet" href="{base}/assets/style.css">
<!-- This card IS the advertisement: the link is going into Telegram, and
     what renders there is what people see before they see anything else.
     The image is THIS book's cover, not a generic one. -->
<meta property="og:type" content="website">
<meta property="og:site_name" content="RS Pixel">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{html.escape(url)}">
<meta property="og:image" content="{html.escape(cover_url)}">
<meta name="twitter:card" content="summary_large_image">
</head>
<body class="share-body">
<main class="share-wrap">
  <header class="share-head">
    <a class="brand" href="{base}/">RS Pixel</a>
  </header>
  <h1 class="share-title">{title}</h1>
  <p class="share-sub" id="share-sub"></p>
  <div id="share-pages" class="share-pages" aria-live="polite"></div>
  <div class="share-cta">
    <p>Made with RS Pixel — design your own photo book and we print it.</p>
    <a class="btn btn-primary" id="share-cta" href="{base}/editor/?{SHARE_QUERY}">
      Make one of your own
    </a>
  </div>
</main>
<script src="{base}/assets/share.js" data-token="{html.escape(token)}"></script>
</body>
</html>
"""


@router.get("/s/{share_token}", response_class=HTMLResponse,
            dependencies=[rate_limit("share",
                                     lambda s: s.rate_limit_share_per_min)])
async def share_page(share_token: str, request: Request,
                     session: Session) -> HTMLResponse:
    book = await svc.find(session, share_token)
    if book is None:
        raise _GONE
    # This visit IS the landing, and we know exactly what it was — better
    # than the referrer, which arrives as `t.me` or as nothing at all. Only
    # honoured for a visitor with no attribution already stored. The token
    # itself never goes near this: it is a secret, and a report is not a
    # place to keep one.
    request.state.funnel_landing = dict(SHARE_ATTRIBUTION)
    if svc.is_stale(book):
        await svc.render(session, book)
    from app import storage

    cover_url = storage.presign_get(
        f"books/{book.id}/share/cover.jpg", expires_in=svc.VIEW_URL_EXPIRY_S)
    return HTMLResponse(_page(book, share_token, cover_url), headers=NOINDEX)
