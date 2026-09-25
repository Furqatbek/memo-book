"""flip-video and contributor events are repeatable (CR-003 Phase 2)

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-25

The same widening as 0017, for the same reason, and caught by the same
test — which is the argument for having written that test.

Three more events are genuinely not milestones in one book's life:

* `flip_video_downloaded` — the link goes into a chat and is opened by
  everybody the customer forwards it to. That count IS the feature;
* `contributor_upload` — several people adding photographs to one book is
  the whole of CR-003-6. Counted once, the cap would read 1 and the
  owner's "3 added so far" would never move;
* `contributor_cta_clicked` — pressed by strangers on somebody else's page.

`contributor_link_created` deliberately stays once-only: one link per book
is exactly what that table enforces.
"""
import sqlalchemy as sa

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

OLD = ("editor_opened", "reminder_clicked", "reminder_sent",
       "share_cta_clicked", "share_link_viewed", "site_visit")
NEW = ("contributor_cta_clicked", "contributor_upload", "editor_opened",
       "flip_video_downloaded", "reminder_clicked", "reminder_sent",
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
