"""Who may drive orders from Telegram, and how they came to be allowed (A97).

A96 kept this list in an environment variable, which meant adding a second
operator — or removing one who left — was an SSH session, a file edit and a
restart. Worse, the only way to learn a Telegram user id was a CLI command
that stops working the moment a webhook exists.

The list lives here instead, and an account joins it by redeeming a code
issued in the admin console. That is what makes the link two-sided: the code
is only visible to someone holding `ADMIN_TOKEN`, and redeeming it proves
control of a particular Telegram account. Neither half alone is enough.
"""
import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TelegramOperator(Base):
    """A Telegram account allowed to move orders."""

    __tablename__ = "telegram_operators"

    # Telegram's own id, and the primary key: the same account must not be
    # linkable twice. BigInteger because Telegram ids passed 2^31 long ago.
    telegram_user_id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True)
    # For the console's list, so a row is recognisable as a person rather
    # than a number. Telegram gives neither reliably, so both may be blank.
    username: Mapped[str] = mapped_column(sa.String(64), default="")
    display_name: Mapped[str] = mapped_column(sa.String(120), default="")
    linked_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    # Updated on every accepted action, so the console can show who is
    # actually using this and who has not touched it in months.
    last_used_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True)


class TelegramLinkCode(Base):
    """A single-use, short-lived code issued in the console and typed into
    the bot.

    The code is stored as a SHA-256 hash, not in the clear. It is a live
    credential for as long as it lasts, and a credential that can be read
    out of a database backup is one worth not writing down.
    """

    __tablename__ = "telegram_link_codes"

    id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, primary_key=True, default=uuid.uuid4)
    code_hash: Mapped[str] = mapped_column(sa.String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    # Set the moment it is spent, which is what makes it single-use. A code
    # is never deleted on redemption: the row is the record of who linked
    # and when, and that is worth keeping.
    used_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True)
    used_by_user_id: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
