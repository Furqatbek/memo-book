"""back-panel artwork for a cover design (A95)

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-16

All four columns are nullable with no server default, and NULL is the
meaningful value: "this design has no back artwork, so the back panel is the
flat bg_color". Every design that exists when this runs keeps exactly the
cover it had.
"""
import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cover_designs",
                  sa.Column("back_artwork_key", sa.String(255), nullable=True))
    op.add_column("cover_designs",
                  sa.Column("back_display_key", sa.String(255), nullable=True))
    op.add_column("cover_designs",
                  sa.Column("back_artwork_width", sa.Integer, nullable=True))
    op.add_column("cover_designs",
                  sa.Column("back_artwork_height", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("cover_designs", "back_artwork_height")
    op.drop_column("cover_designs", "back_artwork_width")
    op.drop_column("cover_designs", "back_display_key")
    op.drop_column("cover_designs", "back_artwork_key")
