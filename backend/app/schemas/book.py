"""API request/response models for the books endpoints."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.layout import LayoutDoc


class CreateBookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_count: int


class ChangePageCountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_count: int


class SetEmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr


class BookResponse(BaseModel):
    book_id: uuid.UUID
    page_count: int
    status: str
    layout: dict
    layout_version: int
    email: str | None
    photos: list = Field(default_factory=list)  # populated from Milestone 4
    created_at: datetime
    updated_at: datetime
    expires_at: datetime


class CreateBookResponse(BookResponse):
    edit_token: str


class LayoutPatchResponse(BaseModel):
    layout: dict
    layout_version: int


class PageCountResponse(BaseModel):
    page_count: int
    layout: dict
    layout_version: int
    warnings: list[str]


# Re-exported so the router can annotate the PATCH body precisely.
LayoutBody = LayoutDoc
