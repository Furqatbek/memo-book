"""third reminder at day 25 (Change 4)

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-25

One boolean. Day 25 is the last useful moment: a draft expires 30 days
after its last edit, so this is the reminder that can still be acted on,
and it is the one that says so.
"""
import sqlalchemy as sa

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("books", sa.Column("reminder_25d_sent", sa.Boolean,
                                     nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("books", "reminder_25d_sent")
