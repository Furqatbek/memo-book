"""API request/response models for the books endpoints."""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.schemas.layout import LayoutDoc

BookType = Literal["love", "travel", "birthday", "memory"]


class CreateBookRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_count: int
    book_type: BookType | None = None


class ChangePageCountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_count: int


class SetEmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr


class BookResponse(BaseModel):
    book_id: uuid.UUID
    page_count: int
    book_type: str | None = None
    status: str
    layout: dict
    layout_version: int
    email: str | None
    photos: list = Field(default_factory=list)  # populated from Milestone 4
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    # Which links are currently live (CR-003-1, CR-003-6). BOOLEANS, never
    # the tokens: the share token is a credential and the contributor token
    # is only ever stored as a hash, so neither can or should come back
    # here. The editor needs exactly this much to decide whether to offer
    # "turn it off" — without it the owner could create a link and had no
    # way to revoke one.
    shared: bool = False
    has_contributor_link: bool = False
    # Real views of the share link, for the owner. Never invented: it is
    # incremented by the view endpoint and by nothing else.
    share_view_count: int = 0


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
