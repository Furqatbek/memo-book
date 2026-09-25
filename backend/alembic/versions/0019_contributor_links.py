"""collaborative photo upload (CR-003-6)

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-25

One link per book, and the token is stored as a SHA-256 rather than in the
clear. That is the point of the column name: this table can be dumped,
logged or read by anybody with database access, and none of that may hand
them the power to upload into a stranger's book.

`photos.contributed_by` is likewise NOT the token. It is an opaque
per-contributor id, indexed because every quota check counts distinct
values of it.
"""
import sqlalchemy as sa

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contributor_links",
        sa.Column("book_id", sa.Uuid,
                  sa.ForeignKey("books.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("token_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_contributor_links_token", "contributor_links",
                    ["token_sha256"], unique=True)

    op.add_column("photos",
                  sa.Column("contributed_by", sa.String(64), nullable=True))
    op.add_column("photos",
                  sa.Column("contributor_name", sa.String(60), nullable=True))
    op.create_index("ix_photos_contributed_by", "photos", ["contributed_by"])


def downgrade() -> None:
    op.drop_index("ix_photos_contributed_by", table_name="photos")
    op.drop_column("photos", "contributor_name")
    op.drop_column("photos", "contributed_by")
    op.drop_index("ix_contributor_links_token", table_name="contributor_links")
    op.drop_table("contributor_links")
