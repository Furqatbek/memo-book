"""share events are repeatable (CR-003-1)

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-25

The partial unique index on `funnel_events` exists so a refresh cannot
inflate a milestone. CR-003-1 adds two events that are NOT milestones:
a share link is created once, and then viewed by as many people as the
owner sends it to — that count being the entire point of the feature.

Left out of the predicate, the index would refuse every view after the
first and the number would read 1 for ever. The model builds its predicate
from the enum and a test asserts the two agree, which is what caught this.
"""
import sqlalchemy as sa

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

OLD = ("editor_opened", "reminder_clicked", "reminder_sent", "site_visit")
NEW = ("editor_opened", "reminder_clicked", "reminder_sent",
       "share_cta_clicked", "share_link_viewed", "site_visit")


def _predicate(names) -> str:
    return "event_type NOT IN ({})".format(", ".join(f"'{n}'" for n in names))


def _rebuild(names) -> None:
    op.drop_index("uq_funnel_events_once_per_book", table_name="funnel_events")
    op.create_index("uq_funnel_events_once_per_book", "funnel_events",
                    ["book_id", "event_type"], unique=True,
                    sqlite_where=sa.text(_predicate(names)),
                    postgresql_where=sa.text(_predicate(names)))


def upgrade() -> None:
    _rebuild(NEW)


def downgrade() -> None:
    _rebuild(OLD)
