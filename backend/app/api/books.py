"""Books endpoints (spec Part 5). Auth: X-Edit-Token header; a wrong token is
indistinguishable from a missing book (404). Layout mutations require
If-Match: <layout_version> (409 on conflict, 428 when absent)."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
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

router = APIRouter(prefix="/api/v1/books", tags=["books"])

Session = Annotated[AsyncSession, Depends(get_session)]
EditToken = Annotated[str, Header(alias="X-Edit-Token")]
IfMatch = Annotated[int | None, Header(alias="If-Match")]


def _book_response(book: Book) -> dict:
    return {
        "book_id": book.id,
        "page_count": book.page_count,
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
async def create_book(body: CreateBookRequest, session: Session):
    book = await svc.create_book(session, body.page_count)
    return {**_book_response(book), "edit_token": book.edit_token}


@router.get("/{book_id}", response_model=BookResponse)
async def get_book(book_id: uuid.UUID, session: Session, x_edit_token: EditToken):
    book = await svc.get_book_authed(session, book_id, x_edit_token)
    photos = await photo_svc.list_photos(session, book_id, x_edit_token)
    return {**_book_response(book),
            "photos": [photo_svc.serialize_photo(p) for p in photos]}


@router.patch("/{book_id}/layout", response_model=LayoutPatchResponse)
async def patch_layout(book_id: uuid.UUID, body: LayoutBody, session: Session,
                       x_edit_token: EditToken, if_match: IfMatch = None):
    book = await svc.patch_layout(session, book_id, x_edit_token, if_match, body)
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
async def set_email(book_id: uuid.UUID, body: SetEmailRequest, session: Session,
                    x_edit_token: EditToken):
    book = await svc.set_email(session, book_id, x_edit_token, body.email)
    return _book_response(book)


@router.post("/{book_id}/auto-place")
async def auto_place(book_id: uuid.UUID, session: Session, x_edit_token: EditToken,
                     if_match: IfMatch = None):
    book, placed_count, unplaced = await placement_svc.auto_place(
        session, book_id, x_edit_token, if_match
    )
    return {
        "layout": book.layout,
        "layout_version": book.layout_version,
        "placed_count": placed_count,
        "unplaced_photo_ids": unplaced,  # R3: surplus is surfaced, never dropped
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
