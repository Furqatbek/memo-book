"""the customer's flip video (CR-003-5)

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-25

Its own table rather than a row in `pdf_artifacts`. A print artifact is
something the printer must have and whose absence stops an order; this is a
nicety whose absence nobody should ever notice, and keeping them apart is
what stops a query for print files tripping over a missing video.
"""
import sqlalchemy as sa

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "flip_videos",
        sa.Column("order_id", sa.Uuid,
                  sa.ForeignKey("orders.id", ondelete="CASCADE"),
                  primary_key=True),
        # The customer's link is /v/{token}. Unique so two orders cannot
        # ever answer to the same one, indexed because the token is the
        # only thing the lookup has.
        sa.Column("token", sa.String(64), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=False),
        sa.Column("bytes", sa.BigInteger, nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=False),
        sa.Column("page_count", sa.Integer, nullable=False),
        sa.Column("render_ms", sa.Integer, nullable=False),
        sa.Column("download_count", sa.Integer, nullable=False,
                  server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_flip_videos_token", "flip_videos", ["token"],
                    unique=True)


def downgrade() -> None:
    op.drop_index("ix_flip_videos_token", table_name="flip_videos")
    op.drop_table("flip_videos")
