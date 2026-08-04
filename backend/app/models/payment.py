import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.book import JSONDoc


class PaymentEvent(Base):
    """Append-only audit + idempotency (R10): a webhook is processed at most
    once per (provider, provider_event_id, method)."""

    __tablename__ = "payment_events"
    __table_args__ = (
        sa.UniqueConstraint("provider", "provider_event_id", "method",
                            name="uq_payment_event"),
    )

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(sa.String(16))
    provider_event_id: Mapped[str] = mapped_column(sa.String(128))
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.Uuid, sa.ForeignKey("orders.id"), nullable=True
    )
    method: Mapped[str] = mapped_column(sa.String(32))
    raw_payload: Mapped[dict] = mapped_column(JSONDoc)
    received_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))


class PdfArtifact(Base):
    __tablename__ = "pdf_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(sa.String(8))  # interior | cover
    storage_key: Mapped[str] = mapped_column(sa.String(255))
    sha256: Mapped[str] = mapped_column(sa.String(64))
    page_count: Mapped[int] = mapped_column(sa.Integer)
    size_bytes: Mapped[int] = mapped_column("bytes", sa.BigInteger)
    render_ms: Mapped[int] = mapped_column(sa.Integer)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
