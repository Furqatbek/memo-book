"""The contributor link — CR-003-6.

Your travel companion always has the better photographs. This lets the
owner hand them a link that can do exactly one thing: add pictures to the
pool. It cannot see the book, cannot place anything, cannot read the
owner's details and cannot buy anything.

It is also, by some distance, the most abusable surface in the system: an
UNAUTHENTICATED endpoint that accepts files from anybody holding a URL. So
two things are true of this table:

* **The token is stored as a SHA-256, never in the clear.** A database
  backup, a log line or a stray `SELECT *` must not hand somebody the power
  to upload into a stranger's book. The owner's copy is the only copy.
* **There is one link per book and it is deletable.** "Turn it off" has to
  be a single row disappearing, not a hunt through a list.

The quotas are NOT counted here. They are derived from the photo rows
themselves — see `app/services/contribute.py` — because a counter column is
a number that can drift from the thing it claims to count, and this is the
one number in the system that somebody has an incentive to make drift.
"""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ContributorLink(Base):
    __tablename__ = "contributor_links"

    book_id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, sa.ForeignKey("books.id", ondelete="CASCADE"),
        primary_key=True)
    token_sha256: Mapped[str] = mapped_column(sa.String(64), unique=True,
                                              index=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
