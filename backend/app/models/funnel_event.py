"""Append-only funnel events — Change 3.

Nothing ever updates or deletes a row here. That is what makes the table
safe to write from anywhere: the worst a bug can do is add a row nobody
counts, never corrupt a book or an order.

The unique index is the load-bearing part. Checking "has this event already
been recorded?" in Python and then inserting is a race: two requests that
arrive together both read "no" and both insert, and the metric is inflated
by exactly the kind of double-submit that instrumentation exists to
measure. The database refuses the second one instead, and the service
swallows the refusal.
"""
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.events import REPEATABLE

JSONDoc = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

# Spelled out rather than interpolated so the migration and the model can
# be compared by eye — a partial index whose predicate drifts from the enum
# stops guarding the events it was written for, silently.
_REPEATABLE_SQL = ", ".join(f"'{e.value}'" for e in sorted(REPEATABLE, key=lambda e: e.value))


class FunnelEvent(Base):
    __tablename__ = "funnel_events"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    book_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("books.id"), nullable=True, index=True)
    # Anonymous, from a first-party cookie. Never a customer identifier.
    session_id: Mapped[str] = mapped_column(sa.String(64), index=True)
    event_type: Mapped[str] = mapped_column(sa.String(32), index=True)
    properties: Mapped[dict] = mapped_column(JSONDoc, default=dict)
    source: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    campaign: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    medium: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), index=True,
        default=lambda: datetime.now(UTC))

    __table_args__ = (
        sa.Index("ix_funnel_events_type_time", "event_type", "occurred_at"),
        sa.Index("ix_funnel_events_book_time", "book_id", "occurred_at"),
        # One per book per type, for every type that is a milestone rather
        # than something repeatable. A NULL book_id never collides in either
        # Postgres or SQLite, which is exactly right: site_visit has no book.
        sa.Index("uq_funnel_events_once_per_book", "book_id", "event_type",
                 unique=True,
                 sqlite_where=sa.text(f"event_type NOT IN ({_REPEATABLE_SQL})"),
                 postgresql_where=sa.text(f"event_type NOT IN ({_REPEATABLE_SQL})")),
    )
