"""create photos table

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-05

"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "photos",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("book_id", sa.Uuid(),
                  sa.ForeignKey("books.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("original_key", sa.String(255), nullable=False),
        sa.Column("display_key", sa.String(255), nullable=True),
        sa.Column("thumb_key", sa.String(255), nullable=True),
        sa.Column("orig_width", sa.Integer(), nullable=True),
        sa.Column("orig_height", sa.Integer(), nullable=True),
        sa.Column("mime_original", sa.String(64), nullable=False),
        sa.Column("bytes_original", sa.BigInteger(), nullable=False),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exif_orientation", sa.Integer(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("duplicate_of", sa.Uuid(), nullable=True),
    )
    op.create_index("ix_photos_book_id", "photos", ["book_id"])
    op.create_index("ix_photos_sha256", "photos", ["sha256"])


def downgrade() -> None:
    op.drop_index("ix_photos_sha256", table_name="photos")
    op.drop_index("ix_photos_book_id", table_name="photos")
    op.drop_table("photos")
