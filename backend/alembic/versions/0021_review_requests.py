"""the post-delivery review request (CR-003-9)

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-25

One row per order, created when we ask and filled in if they answer. Its
existence is what makes the ask once-only, which is why `requested_at` is
NOT NULL: a row that exists means the question was put, and no job may put
it again.

`may_publish` is NOT NULL and defaults to false. It is the only thing that
grants publication, and a nullable column with an ambiguous middle state
would eventually be read as "probably fine".
"""
import sqlalchemy as sa

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_requests",
        sa.Column("order_id", sa.Uuid,
                  sa.ForeignKey("orders.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("text", sa.Text, nullable=True),
        sa.Column("display_name", sa.String(80), nullable=True),
        sa.Column("city", sa.String(80), nullable=True),
        sa.Column("lang", sa.String(8), nullable=True),
        sa.Column("photo_key", sa.String(255), nullable=True),
        sa.Column("may_publish", sa.Boolean, nullable=False,
                  server_default=sa.false()),
    )
    op.create_index("ix_review_requests_token", "review_requests", ["token"],
                    unique=True)


def downgrade() -> None:
    op.drop_index("ix_review_requests_token", table_name="review_requests")
    op.drop_table("review_requests")
