"""payment receipt on an order (A100)

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-20

Four nullable columns and nothing touched. NULL means "no receipt", which is
every order that exists when this runs.
"""
import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders",
                  sa.Column("receipt_key", sa.String(255), nullable=True))
    op.add_column("orders",
                  sa.Column("receipt_content_type", sa.String(64), nullable=True))
    op.add_column("orders",
                  sa.Column("receipt_bytes", sa.Integer, nullable=True))
    op.add_column("orders",
                  sa.Column("receipt_uploaded_at", sa.DateTime(timezone=True),
                            nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "receipt_uploaded_at")
    op.drop_column("orders", "receipt_bytes")
    op.drop_column("orders", "receipt_content_type")
    op.drop_column("orders", "receipt_key")
