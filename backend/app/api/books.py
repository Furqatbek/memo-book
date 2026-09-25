"""Books endpoints (spec Part 5). Auth: X-Edit-Token header; a wrong token is
indistinguishable from a missing book (404). Layout mutations require
If-Match: <layout_version> (409 on conflict, 428 when absent)."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.tracking import record
from app.db.session import get_session
from app.domain.events import EventType
from app.models.book import Book
from app.rate_limit import rate_limit
from app.schemas.book import (
    BookResponse,
    ChangePageCountRequest,
    CreateBookRequest,
    CreateBookResponse,
    LayoutBody,
    LayoutPatchResponse,
    PageCountResponse,
    SetEmailRequest,
)
from app.services import books as svc
from app.services import photos as photo_svc
from app.services import placement as placement_svc
from app.services import telegram_recovery

router = APIRouter(prefix="/api/v1/books", tags=["books"])

Session = Annotated[AsyncSession, Depends(get_session)]
EditToken = Annotated[str, Header(alias="X-Edit-Token")]
IfMatch = Annotated[int | None, Header(alias="If-Match")]


def _book_response(book: Book) -> dict:
    return {
        "book_id": book.id,
        "page_count": book.page_count,
        # Needed to reopen a resumed book with the right cover gallery (A71).
        "book_type": book.book_type,
        "status": book.status,
        "layout": book.layout,
        "layout_version": book.layout_version,
        "email": book.email,
        "photos": [],
        "created_at": book.created_at,
        "updated_at": book.updated_at,
        "expires_at": book.expires_at,
    }


@router.post("", response_model=CreateBookResponse, status_code=201,
             dependencies=[rate_limit("book-create",
                                      lambda s: s.rate_limit_book_create_per_min)])
async def create_book(body: CreateBookRequest, request: Request, session: Session):
    book = await svc.create_book(session, body.page_count, body.book_type)
    # The first step the server can see for itself: a tier was chosen and a
    # row exists. Everything above this in the funnel is client-reported.
    await record(request, session, EventType.BOOK_STARTED, book_id=book.id,
                 properties={"page_count": book.page_count,
                             "book_type": book.book_type})
    await session.commit()
    return {**_book_response(book), "edit_token": book.edit_token}


@router.get("/{book_id}", response_model=BookResponse)
async def get_book(book_id: uuid.UUID, session: Session, x_edit_token: EditToken):
    book = await svc.get_book_authed(session, book_id, x_edit_token)
    photos = await photo_svc.list_photos(session, book_id, x_edit_token)
    return {**_book_response(book),
            "photos": [photo_svc.serialize_photo(p) for p in photos]}


@router.patch("/{book_id}/layout", response_model=LayoutPatchResponse)
async def patch_layout(book_id: uuid.UUID, body: LayoutBody, request: Request,
                       session: Session,
                       x_edit_token: EditToken, if_match: IfMatch = None):
    book = await svc.patch_layout(session, book_id, x_edit_token, if_match, body)
    for milestone in placement_svc.design_milestones(book.layout):
        await record(request, session, milestone, book_id=book.id)
    await session.commit()
    return {"layout": book.layout, "layout_version": book.layout_version}


@router.patch("/{book_id}/page-count", response_model=PageCountResponse)
async def change_page_count(book_id: uuid.UUID, body: ChangePageCountRequest,
                            session: Session, x_edit_token: EditToken,
                            if_match: IfMatch = None):
    book, warnings = await svc.change_page_count(
        session, book_id, x_edit_token, if_match, body.page_count
    )
    return {"page_count": book.page_count, "layout": book.layout,
            "layout_version": book.layout_version, "warnings": warnings}


@router.patch("/{book_id}/email", response_model=BookResponse)
async def set_email(book_id: uuid.UUID, body: SetEmailRequest, request: Request,
                    session: Session, x_edit_token: EditToken):
    book = await svc.set_email(session, book_id, x_edit_token, body.email)
    if book.email:
        await record(request, session, EventType.CONTACT_CAPTURED,
                     book_id=book.id, properties={"channel": "email"})
        await session.commit()
    return _book_response(book)


@router.post("/{book_id}/auto-place")
async def auto_place(book_id: uuid.UUID, request: Request, session: Session,
                     x_edit_token: EditToken, if_match: IfMatch = None):
    book, placed_count, unplaced, dated_count = await placement_svc.auto_place(
        session, book_id, x_edit_token, if_match
    )
    # One click here can cross both design lines at once.
    for milestone in placement_svc.design_milestones(book.layout):
        await record(request, session, milestone, book_id=book.id)
    await session.commit()
    return {
        "layout": book.layout,
        "layout_version": book.layout_version,
        "placed_count": placed_count,
        "unplaced_photo_ids": unplaced,  # R3: surplus is surfaced, never dropped
        # How many of those carried a date, so the editor can say it put the
        # photos in the order they were taken only when that is true (P1-5).
        "dated_count": dated_count,
    }


@router.get("/{book_id}/telegram-link")
async def telegram_link(book_id: uuid.UUID, session: Session,
                        x_edit_token: EditToken) -> dict:
    """The deep link that turns this book into a Telegram conversation.

    Behind the edit token, because minting a recovery secret for somebody
    else's book is exactly what an attacker would want to do with an open
    endpoint. `available: false` when no bot username is configured — the
    editor then hides the offer rather than showing a link that lands
    nowhere, which is the P0-2 lesson in a different place.
    """
    book = await svc.get_book_authed(session, book_id, x_edit_token)
    if not telegram_recovery.configured():
        return {"available": False, "deep_link": None, "linked": False}
    token = await telegram_recovery.issue_token(session, book)
    await session.commit()
    return {
        "available": True,
        "deep_link": telegram_recovery.deep_link(token),
        "linked": book.telegram_chat_id is not None,
    }


@router.get("/{book_id}/checkout-eligibility")
async def checkout_eligibility(book_id: uuid.UUID, session: Session,
                               x_edit_token: EditToken):
    result = await placement_svc.eligibility(session, book_id, x_edit_token)
    return {
        "eligible": result.eligible,
        "photo_count": result.photo_count,
        "page_count": result.page_count,
        "issues": [
            {"code": i.code.value, "message": i.message, "details": i.details}
            for i in result.issues
        ],
        "suggested_tier": result.suggested_tier,
    }
