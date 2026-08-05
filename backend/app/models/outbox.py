import uuid
from datetime import datetime
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.book import JSONDoc


class OutboxStatus(StrEnum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


class OutboxMessage(Base):
    """Transactional outbox (spec Part 8): written in the SAME transaction as
    the state change it announces, delivered by a separate worker with
    exponential backoff. At-least-once; consumers tolerate duplicates."""

    __tablename__ = "outbox_messages"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    topic: Mapped[str] = mapped_column(sa.String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSONDoc)
    status: Mapped[str] = mapped_column(sa.String(16),
                                        default=OutboxStatus.PENDING.value, index=True)
    attempts: Mapped[int] = mapped_column(sa.Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
