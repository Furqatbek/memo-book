"""Photo endpoints (spec Part 5). Bytes go straight to object storage via
presigned PUT — never through the API server."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app import queue
from app.db.session import get_session
from app.rate_limit import rate_limit
from app.services import photos as svc

router = APIRouter(prefix="/api/v1/books/{book_id}/photos", tags=["photos"])

Session = Annotated[AsyncSession, Depends(get_session)]
EditToken = Annotated[str, Header(alias="X-Edit-Token")]


class UploadUrlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(max_length=255)
    mime: str = Field(max_length=64)
    bytes: int


class UploadUrlResponse(BaseModel):
    upload_url: str
    photo_id: uuid.UUID
    storage_key: str


@router.post("/upload-url", response_model=UploadUrlResponse,
             dependencies=[rate_limit("upload-url",
                                      lambda s: s.rate_limit_upload_url_per_min)])
async def upload_url(book_id: uuid.UUID, body: UploadUrlRequest, session: Session,
                     x_edit_token: EditToken):
    photo, url = await svc.issue_upload_url(
        session, book_id, x_edit_token, body.filename, body.mime, body.bytes
    )
    return {"upload_url": url, "photo_id": photo.id, "storage_key": photo.original_key}


@router.post("/{photo_id}/complete")
async def complete(book_id: uuid.UUID, photo_id: uuid.UUID, session: Session,
                   x_edit_token: EditToken):
    photo = await svc.complete_upload(session, book_id, x_edit_token, photo_id)
    if photo.status == "processing":
        if queue.eager():
            await svc.ingest_photo(session, photo.id)
        else:
            queue.enqueue_ingest(photo.id)
    return {"status": "processing"}


@router.get("")
async def list_photos(book_id: uuid.UUID, session: Session, x_edit_token: EditToken):
    photos = await svc.list_photos(session, book_id, x_edit_token)
    return {"photos": [svc.serialize_photo(p) for p in photos]}


@router.delete("/{photo_id}", status_code=204)
async def delete_photo(book_id: uuid.UUID, photo_id: uuid.UUID, session: Session,
                       x_edit_token: EditToken):
    await svc.delete_photo(session, book_id, x_edit_token, photo_id)
