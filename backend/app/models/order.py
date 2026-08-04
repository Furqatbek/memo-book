import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.domain.states import OrderStatus


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    book_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("books.id"), unique=True  # one order per book
    )
    human_ref: Mapped[str] = mapped_column(sa.String(16), unique=True, index=True)

    customer_name: Mapped[str] = mapped_column(sa.String(200))
    customer_phone: Mapped[str] = mapped_column(sa.String(32))
    customer_address: Mapped[str] = mapped_column(sa.Text)
    customer_email: Mapped[str | None] = mapped_column(sa.String(320), nullable=True)

    amount_minor: Mapped[int] = mapped_column(sa.BigInteger)  # UZS tiyin, never floats
    currency: Mapped[str] = mapped_column(sa.String(3), default="UZS")
    status: Mapped[str] = mapped_column(sa.String(24),
                                        default=OrderStatus.DRAFT_ORDER.value)

    provider: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    provider_txn_id: Mapped[str | None] = mapped_column(sa.String(128), nullable=True,
                                                        index=True)

    preview_confirmed_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True),
                                                     nullable=True)
    rendered_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True),
                                                         nullable=True)
    shipped_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True),
                                                        nullable=True)


class OrderEvent(Base):
    """Append-only audit: every status transition writes a row (spec Part 3)."""

    __tablename__ = "order_events"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    from_status: Mapped[str | None] = mapped_column(sa.String(24), nullable=True)
    to_status: Mapped[str] = mapped_column(sa.String(24))
    note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
