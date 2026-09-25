import uuid
from datetime import datetime
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PhotoStatus(StrEnum):
    PENDING = "pending"        # upload URL issued, bytes not confirmed
    PROCESSING = "processing"  # complete called, ingest running
    READY = "ready"
    DUPLICATE = "duplicate"    # same sha256 as another photo in this book
    FAILED = "failed"


class Photo(Base):
    __tablename__ = "photos"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    book_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("books.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(sa.String(16), default=PhotoStatus.PENDING.value)
    error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    original_key: Mapped[str] = mapped_column(sa.String(255))  # immutable, never overwritten
    display_key: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    thumb_key: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)

    orig_width: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)   # post-rotation
    orig_height: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)  # post-rotation
    mime_original: Mapped[str] = mapped_column(sa.String(64))
    bytes_original: Mapped[int] = mapped_column(sa.BigInteger)
    taken_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    exif_orientation: Mapped[int] = mapped_column(sa.Integer, default=1)
    uploaded_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    sha256: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)
    duplicate_of: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid, nullable=True)

    # Who added this, when it was not the owner (CR-003-6). NOT the
    # contributor's token: that is a secret, and a copy of it on every photo
    # row would undo the point of storing only its hash. This is an opaque
    # per-contributor id derived from their anonymous session, and it exists
    # for two jobs — counting distinct contributors against the cap, and
    # showing the owner which pictures are not theirs.
    contributed_by: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True, index=True)
    # Self-declared and optional. Never trusted for anything; it is a label
    # so the owner can tell Aziza's photographs from Bek's.
    contributor_name: Mapped[str | None] = mapped_column(
        sa.String(60), nullable=True)
