"""funnel events (Change 3)

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-25

One new append-only table and nothing touched. The partial unique index is
the point of the migration: it is what stops a refresh counting as a second
book_started, and it has to be enforced by the database rather than by a
check-then-insert in Python, which two simultaneous requests both pass.

The predicate lists the repeatable events. It is written out here rather
than generated so that the schema is readable in isolation; the model
carries the same list built from the enum, and
`tests/test_funnel_model.py` asserts the two agree.
"""
import sqlalchemy as sa

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

REPEATABLE = ("editor_opened", "reminder_clicked", "reminder_sent", "site_visit")
_PREDICATE = "event_type NOT IN ({})".format(
    ", ".join(f"'{e}'" for e in REPEATABLE))


def upgrade() -> None:
    op.create_table(
        "funnel_events",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("book_id", sa.Uuid, sa.ForeignKey("books.id"), nullable=True),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("properties", sa.JSON, nullable=False),
        sa.Column("source", sa.String(128), nullable=True),
        sa.Column("campaign", sa.String(128), nullable=True),
        sa.Column("medium", sa.String(128), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_funnel_events_book_id", "funnel_events", ["book_id"])
    op.create_index("ix_funnel_events_session_id", "funnel_events", ["session_id"])
    op.create_index("ix_funnel_events_event_type", "funnel_events", ["event_type"])
    op.create_index("ix_funnel_events_occurred_at", "funnel_events", ["occurred_at"])
    op.create_index("ix_funnel_events_type_time", "funnel_events",
                    ["event_type", "occurred_at"])
    op.create_index("ix_funnel_events_book_time", "funnel_events",
                    ["book_id", "occurred_at"])
    op.create_index("uq_funnel_events_once_per_book", "funnel_events",
                    ["book_id", "event_type"], unique=True,
                    sqlite_where=sa.text(_PREDICATE),
                    postgresql_where=sa.text(_PREDICATE))


def downgrade() -> None:
    op.drop_index("uq_funnel_events_once_per_book", table_name="funnel_events")
    op.drop_index("ix_funnel_events_book_time", table_name="funnel_events")
    op.drop_index("ix_funnel_events_type_time", table_name="funnel_events")
    op.drop_index("ix_funnel_events_occurred_at", table_name="funnel_events")
    op.drop_index("ix_funnel_events_event_type", table_name="funnel_events")
    op.drop_index("ix_funnel_events_session_id", table_name="funnel_events")
    op.drop_index("ix_funnel_events_book_id", table_name="funnel_events")
    op.drop_table("funnel_events")
