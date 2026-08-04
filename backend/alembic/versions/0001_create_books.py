"""create books table

Revision ID: 0001
Revises:
Create Date: 2026-08-05

"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "books",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("edit_token", sa.String(64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("layout", postgresql.JSONB(), nullable=False),
        sa.Column("layout_version", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("reminder_3d_sent", sa.Boolean(), nullable=False),
        sa.Column("reminder_14d_sent", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_books_edit_token", "books", ["edit_token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_books_edit_token", table_name="books")
    op.drop_table("books")
