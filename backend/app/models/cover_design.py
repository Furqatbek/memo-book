"""A ready-made cover the founder uploads, offered to customers by occasion.

Unlike page layouts and the built-in cover compositions — code, shipped with
a release — these are content: artwork files added, renamed and retired
without a deploy (A71). The row therefore carries both the artwork and the
geometry that goes with it, because a design is a whole thing: this picture,
with the customer's photo *here*, and the title *there*.

`book_types` is a comma-delimited list of occasion slugs, empty meaning "any
occasion". Deliberately not a JSON array or a join table: there will be tens
of designs, the filtering happens in Python, and a plain string keeps the
admin script and a psql session both readable.
"""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

JSONDoc = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


class CoverDesign(Base):
    __tablename__ = "cover_designs"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    # Stable handle used by the admin script and by tests; the customer never
    # sees it. Unique so re-uploading a design replaces it rather than
    # silently adding a second copy.
    slug: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(sa.String(120), default="")
    # "" = every occasion; otherwise "love,travel".
    book_types: Mapped[str] = mapped_column(sa.String(120), default="")

    # Three renditions, like a photo: the print original never leaves the
    # server, the display copy draws the editor canvas, the thumb fills a
    # gallery card.
    artwork_key: Mapped[str] = mapped_column(sa.String(255))
    display_key: Mapped[str] = mapped_column(sa.String(255))
    thumb_key: Mapped[str] = mapped_column(sa.String(255))
    artwork_width: Mapped[int] = mapped_column(sa.Integer)
    artwork_height: Mapped[int] = mapped_column(sa.Integer)

    # Where the customer's photo goes on this design, in front-panel trim mm
    # (same origin as the built-in compositions). NULL = a complete artwork
    # cover with no photo window.
    photo_rect: Mapped[dict | None] = mapped_column(JSONDoc, nullable=True)
    title_x_mm: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    title_y_mm: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    title_size_pt: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    # NULL = decide automatically, as an artwork-free cover does.
    title_color: Mapped[str | None] = mapped_column(sa.String(7), nullable=True)
    # Back panel and spine, which the artwork does not cover.
    bg_color: Mapped[str] = mapped_column(sa.String(7), default="#ffffff")

    sort_order: Mapped[int] = mapped_column(sa.Integer, default=100)
    # Retiring a design hides it from the gallery but never breaks the books
    # already using it — their covers must keep rendering.
    active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
