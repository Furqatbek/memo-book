"""shareable draft links (CR-003-1)

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-25

Four nullable columns on `books`. `share_token` is unique and indexed
because it is looked up by strangers on every view of a shared page, and
it is a third secret distinct from `edit_token` and `telegram_token` —
a link that gets forwarded must never carry edit rights.
"""
import sqlalchemy as sa

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("books", sa.Column("share_token", sa.String(64), nullable=True))
    op.add_column("books", sa.Column("share_created_at",
                                     sa.DateTime(timezone=True), nullable=True))
    op.add_column("books", sa.Column("share_view_count", sa.Integer,
                                     nullable=False, server_default="0"))
    op.add_column("books", sa.Column("share_layout_version", sa.Integer,
                                     nullable=True))
    op.create_index("uq_books_share_token", "books", ["share_token"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_books_share_token", table_name="books")
    op.drop_column("books", "share_layout_version")
    op.drop_column("books", "share_view_count")
    op.drop_column("books", "share_created_at")
    op.drop_column("books", "share_token")
