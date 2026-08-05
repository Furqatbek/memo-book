"""create payment_events and pdf_artifacts

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-05

"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("provider_event_id", sa.String(128), nullable=False),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("method", sa.String(32), nullable=False),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "provider_event_id", "method",
                            name="uq_payment_event"),
    )

    op.create_table(
        "pdf_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("order_id", sa.Uuid(),
                  sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.Column("render_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_pdf_artifacts_order_id", "pdf_artifacts", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_pdf_artifacts_order_id", table_name="pdf_artifacts")
    op.drop_table("pdf_artifacts")
    op.drop_table("payment_events")
