import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.states import BookStatus

# JSONB on Postgres, plain JSON elsewhere (tests can run on SQLite).
JSONDoc = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


class Book(Base):
    __tablename__ = "books"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    edit_token: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)
    page_count: Mapped[int] = mapped_column(sa.Integer)
    # Occasion picked in the editor (love/travel/birthday/memory); shown to
    # the print operator. Nullable: books predating the picker have none.
    book_type: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    status: Mapped[str] = mapped_column(sa.String(16), default=BookStatus.DRAFT.value)
    layout: Mapped[dict] = mapped_column(JSONDoc)
    layout_version: Mapped[int] = mapped_column(sa.Integer, default=1)
    email: Mapped[str | None] = mapped_column(sa.String(320), nullable=True)

    # Telegram as a recovery channel (Change 2). Deliberately NOT unique:
    # one person may make several books, and a unique chat id would make
    # the second link silently fail.
    telegram_chat_id: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True, index=True)
    telegram_linked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True)
    # The deep-link secret, and NOT `edit_token`: a deep link travels
    # through Telegram, sits in a chat list and gets forwarded, while the
    # edit token is all that stands between a stranger and these
    # photographs. This one can only attach a chat to a book, and expires.
    telegram_token: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True, unique=True, index=True)
    telegram_token_expires_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True)

    reminder_3d_sent: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    reminder_14d_sent: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))

    # Preview (Milestone 7): none/processing/ready/failed + the layout version
    # the preview was rendered from, so staleness is detectable.
    preview_status: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    preview_layout_version: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
