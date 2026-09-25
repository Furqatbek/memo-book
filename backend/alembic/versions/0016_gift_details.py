"""gift mode at checkout (CR-003-3)

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-25

One table. The order id is the primary key, so an order is a gift or it is
not — there is no second gift for the same order to disagree with.
"""
import sqlalchemy as sa

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gift_details",
        sa.Column("order_id", sa.Uuid,
                  sa.ForeignKey("orders.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("recipient_name", sa.String(200), nullable=False),
        sa.Column("recipient_phone", sa.String(32), nullable=False),
        sa.Column("recipient_address", sa.Text, nullable=False),
        sa.Column("gift_message", sa.String(200), nullable=True),
        sa.Column("deliver_after", sa.Date, nullable=True),
        sa.Column("hide_price", sa.Boolean, nullable=False,
                  server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("gift_details")
