"""Telegram operators and link codes (A97)

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-19

Two new tables and nothing touched. A deployment that never links an account
has two empty tables and behaves exactly as it did before.
"""
import sqlalchemy as sa

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_operators",
        sa.Column("telegram_user_id", sa.BigInteger, primary_key=True,
                  autoincrement=False),
        sa.Column("username", sa.String(64), nullable=False, server_default=""),
        sa.Column("display_name", sa.String(120), nullable=False, server_default=""),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "telegram_link_codes",
        sa.Column("id", sa.Uuid, primary_key=True),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_by_user_id", sa.BigInteger, nullable=True),
    )
    op.create_index("ix_telegram_link_codes_code_hash", "telegram_link_codes",
                    ["code_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_telegram_link_codes_code_hash",
                  table_name="telegram_link_codes")
    op.drop_table("telegram_link_codes")
    op.drop_table("telegram_operators")
