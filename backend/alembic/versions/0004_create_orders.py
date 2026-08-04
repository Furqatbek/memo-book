"""create orders and order_events

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-05

"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("book_id", sa.Uuid(), sa.ForeignKey("books.id"),
                  nullable=False, unique=True),
        sa.Column("human_ref", sa.String(16), nullable=False),
        sa.Column("customer_name", sa.String(200), nullable=False),
        sa.Column("customer_phone", sa.String(32), nullable=False),
        sa.Column("customer_address", sa.Text(), nullable=False),
        sa.Column("customer_email", sa.String(320), nullable=True),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("provider", sa.String(16), nullable=True),
        sa.Column("provider_txn_id", sa.String(128), nullable=True),
        sa.Column("preview_confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rendered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_orders_human_ref", "orders", ["human_ref"], unique=True)
    op.create_index("ix_orders_provider_txn_id", "orders", ["provider_txn_id"])

    op.create_table(
        "order_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("order_id", sa.Uuid(),
                  sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_status", sa.String(24), nullable=True),
        sa.Column("to_status", sa.String(24), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_order_events_order_id", "order_events", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_order_events_order_id", table_name="order_events")
    op.drop_table("order_events")
    op.drop_index("ix_orders_provider_txn_id", table_name="orders")
    op.drop_index("ix_orders_human_ref", table_name="orders")
    op.drop_table("orders")
