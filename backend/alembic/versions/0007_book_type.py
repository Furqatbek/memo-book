"""add book_type to books

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-08

"""
import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("books", sa.Column("book_type", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("books", "book_type")
