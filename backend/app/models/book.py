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
    status: Mapped[str] = mapped_column(sa.String(16), default=BookStatus.DRAFT.value)
    layout: Mapped[dict] = mapped_column(JSONDoc)
    layout_version: Mapped[int] = mapped_column(sa.Integer, default=1)
    email: Mapped[str | None] = mapped_column(sa.String(320), nullable=True)
    reminder_3d_sent: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    reminder_14d_sent: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
