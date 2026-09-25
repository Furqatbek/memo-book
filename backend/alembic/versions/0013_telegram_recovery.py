"""telegram as a recovery channel (Change 2)

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-25

Four nullable columns on `books` and one small table.

`telegram_chat_id` is an ordinary indexed column and NOT unique: one
Telegram account may hold several books — a person who makes one for their
mother and another for a wedding is one chat and two books — and a unique
constraint would make the second link silently fail.

`telegram_updates` exists because Telegram retries an update until it gets
a 200, and a retry must not act twice. The primary key does the
de-duplication; there is nothing else in the row worth reading.
"""
import sqlalchemy as sa

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("books", sa.Column("telegram_chat_id", sa.BigInteger,
                                     nullable=True))
    op.add_column("books", sa.Column("telegram_linked_at",
                                     sa.DateTime(timezone=True), nullable=True))
    # The deep-link secret. Separate from edit_token on purpose: a deep link
    # travels through Telegram and gets forwarded, and this one can only
    # attach a chat to a book.
    op.add_column("books", sa.Column("telegram_token", sa.String(64),
                                     nullable=True))
    op.add_column("books", sa.Column("telegram_token_expires_at",
                                     sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_books_telegram_chat_id", "books", ["telegram_chat_id"])
    op.create_index("uq_books_telegram_token", "books", ["telegram_token"],
                    unique=True)

    op.create_table(
        "telegram_updates",
        sa.Column("update_id", sa.BigInteger, primary_key=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("telegram_updates")
    op.drop_index("uq_books_telegram_token", table_name="books")
    op.drop_index("ix_books_telegram_chat_id", table_name="books")
    op.drop_column("books", "telegram_token_expires_at")
    op.drop_column("books", "telegram_token")
    op.drop_column("books", "telegram_linked_at")
    op.drop_column("books", "telegram_chat_id")
