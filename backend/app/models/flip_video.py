"""The customer's shareable video of their own book — CR-003-5.

Its own table rather than a row in `pdf_artifacts`, and the distinction is
not cosmetic: a print artifact is something the printer MUST have and whose
absence stops an order, while this is a nicety whose absence nobody should
ever notice. Keeping them apart means no query looking for print files can
be confused by a missing video, and no alert fires for one.
"""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FlipVideo(Base):
    __tablename__ = "flip_videos"

    order_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("orders.id", ondelete="CASCADE"),
        primary_key=True)
    # The customer's link is /v/{token}, not a presigned URL pasted into a
    # message: a presigned URL cannot be counted, cannot be revoked, and
    # expires while the message is still sitting unread in a chat.
    token: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)
    storage_key: Mapped[str] = mapped_column(sa.String(255))
    size_bytes: Mapped[int] = mapped_column("bytes", sa.BigInteger)
    duration_ms: Mapped[int] = mapped_column(sa.Integer)
    page_count: Mapped[int] = mapped_column(sa.Integer)
    render_ms: Mapped[int] = mapped_column(sa.Integer)
    download_count: Mapped[int] = mapped_column(sa.Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
