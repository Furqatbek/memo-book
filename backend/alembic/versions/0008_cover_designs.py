"""cover design catalogue + the design a book's cover uses

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-24

"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

JSONDoc = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "cover_designs",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False, server_default=""),
        sa.Column("book_types", sa.String(120), nullable=False, server_default=""),
        sa.Column("artwork_key", sa.String(255), nullable=False),
        sa.Column("display_key", sa.String(255), nullable=False),
        sa.Column("thumb_key", sa.String(255), nullable=False),
        sa.Column("artwork_width", sa.Integer, nullable=False),
        sa.Column("artwork_height", sa.Integer, nullable=False),
        sa.Column("photo_rect", JSONDoc, nullable=True),
        sa.Column("title_x_mm", sa.Float, nullable=True),
        sa.Column("title_y_mm", sa.Float, nullable=True),
        sa.Column("title_size_pt", sa.Float, nullable=True),
        sa.Column("title_color", sa.String(7), nullable=True),
        sa.Column("bg_color", sa.String(7), nullable=False, server_default="#ffffff"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="100"),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_cover_designs_slug", "cover_designs", ["slug"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_cover_designs_slug", table_name="cover_designs")
    op.drop_table("cover_designs")
