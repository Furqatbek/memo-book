"""Preview endpoints (spec Part 5)."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app import queue
from app.db.session import get_session
from app.services import preview as svc

router = APIRouter(prefix="/api/v1/books/{book_id}/preview", tags=["preview"])

Session = Annotated[AsyncSession, Depends(get_session)]
EditToken = Annotated[str, Header(alias="X-Edit-Token")]


@router.post("", status_code=202)
async def request_preview(book_id: uuid.UUID, session: Session,
                          x_edit_token: EditToken):
    book = await svc.request_preview(session, book_id, x_edit_token)
    if queue.eager():
        await svc.run_preview(session, book.id)
    else:
        queue.enqueue_preview(book.id)
    return {"status": "processing"}


@router.get("")
async def get_preview(book_id: uuid.UUID, session: Session, x_edit_token: EditToken):
    return await svc.preview_state(session, book_id, x_edit_token)
