"""Who the book is actually for — CR-003-3.

Checkout assumed buyer = recipient, and the entire next campaign is
gifting. Without this every gift buyer either abandons or emails to ask,
and both of those cost more than the table.

A separate table rather than columns on `Order` because most orders are
not gifts, and because the one rule that matters here — production
messages go to the BUYER, never the recipient — is easier to keep true
when the recipient's details live somewhere you have to go and ask for.
"""
import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GiftDetails(Base):
    __tablename__ = "gift_details"

    order_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("orders.id", ondelete="CASCADE"),
        primary_key=True)
    recipient_name: Mapped[str] = mapped_column(sa.String(200))
    recipient_phone: Mapped[str] = mapped_column(sa.String(32))
    recipient_address: Mapped[str] = mapped_column(sa.Text)
    gift_message: Mapped[str | None] = mapped_column(sa.String(200), nullable=True)
    # Advisory to the operator, not enforced by anything: at this volume the
    # person packing the box reads it off the Telegram notification.
    deliver_after: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    # Default TRUE. A present with the price in the box is not a present.
    hide_price: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
