"""A customer's review of their own book — CR-003-9.

The table stores what somebody wrote and whether they said it could be
published. It does NOT publish anything: the site's review section is a
hand-curated list in `assets/reviews.js`, and a person copies an approved
review into it. That is deliberate and should stay that way.

Three rules, and they are the whole reason this exists as a row rather
than as an email somebody forwards:

  * **Publishing requires the permission box.** Not implied by submitting,
    not implied by a photo, not implied by a five-star rating. `may_publish`
    is the only thing that grants it, it defaults to False, and a review
    without it is a private message.
  * **Nobody edits the wording.** The text is stored as written and copied
    as written. Tidying a customer's sentence is putting words in their
    mouth, and they cannot check what we made them say.
  * **Nobody invents one.** There is no path that writes a row here except
    a customer submitting the form behind their own one-time link.

One request per order, ever. No follow-up, no second ask.
"""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReviewRequest(Base):
    __tablename__ = "review_requests"

    order_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("orders.id", ondelete="CASCADE"),
        primary_key=True)
    # The customer's one-time link, /r/{token}. Unique, so two orders can
    # never answer to the same one.
    token: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)
    # When we asked. Its presence is what makes the ask once-only: the job
    # that sends these skips any order that already has a row.
    requested_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))

    submitted_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True)
    # As written. Never edited, never translated, never trimmed for fit.
    text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # As they agreed to be named — which may be "A.K." and may be nothing.
    display_name: Mapped[str | None] = mapped_column(sa.String(80),
                                                     nullable=True)
    city: Mapped[str | None] = mapped_column(sa.String(80), nullable=True)
    # The language THEY wrote in, so the site can mark it up correctly
    # rather than let a screen reader read Uzbek as though it were Russian.
    lang: Mapped[str | None] = mapped_column(sa.String(8), nullable=True)
    photo_key: Mapped[str | None] = mapped_column(sa.String(255),
                                                  nullable=True)
    # FALSE until the customer ticks the box. Everything else here may be
    # missing; this one is the difference between a review and a private
    # message, so it is not nullable and it does not default to true.
    may_publish: Mapped[bool] = mapped_column(sa.Boolean, default=False,
                                              nullable=False)
