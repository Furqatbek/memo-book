"""Linking a Telegram account to the operator role (A97).

The flow, and why it is shaped this way:

    console  →  "Link Telegram"  →  shows a code
    Telegram →  /link 7K3M2QX4   →  that account may now move orders

The obvious design — the bot issues a code and you type it back — proves
nothing. Whatever the bot says is visible to everyone in the chat, so the
code would be a secret the untrusted surface handed out itself. Issuing it
in the **console** is the whole point: the console is authenticated, so
holding the code means holding `ADMIN_TOKEN`, and redeeming it means
controlling that Telegram account. The link binds the two identities, and
neither half alone is enough.

This is not privilege escalation: anyone who can read the code can already
cancel orders directly in the console. It grants an existing authority a
second, more convenient handle — it does not create a new one.
"""
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telegram import TelegramLinkCode, TelegramOperator
from app.rate_limit import limiter

log = structlog.get_logger()

# No I, L, O, U, 0 or 1: the code is read off a screen and typed into a
# phone, and every pair those letters form is a pair somebody gets wrong.
ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LEN = 8                    # 30^8 ≈ 2^39 — far past guessing
CODE_TTL = timedelta(minutes=10)

# Redemption attempts per Telegram account per minute. Generous for a person
# mistyping, useless for anything working through a keyspace.
REDEEM_ATTEMPTS_PER_MIN = 5


def _now() -> datetime:
    return datetime.now(UTC)


def _hash(code: str) -> str:
    return hashlib.sha256(normalize(code).encode()).hexdigest()


def normalize(code: str) -> str:
    """What the operator typed -> what was issued. People add spaces and
    dashes, and phones capitalise; none of that should be a failed link."""
    return "".join(c for c in (code or "").upper()
                   if c.isalnum())[:32]


def generate_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))


async def issue_code(session: AsyncSession) -> tuple[str, datetime]:
    """A fresh code, and the moment it dies.

    Issuing invalidates any code still outstanding. One live code at a time
    means a code read off a screen an hour ago, or shared and forgotten,
    cannot still be spent — and it makes "press the button again" the
    complete recovery for every way this can go wrong.
    """
    now = _now()
    await session.execute(
        update(TelegramLinkCode)
        .where(TelegramLinkCode.used_at.is_(None),
               TelegramLinkCode.expires_at > now)
        .values(expires_at=now))
    # Spent and expired codes are evidence for a while, not forever.
    await session.execute(
        delete(TelegramLinkCode)
        .where(TelegramLinkCode.created_at < now - timedelta(days=30)))

    code = generate_code()
    expires_at = now + CODE_TTL
    session.add(TelegramLinkCode(code_hash=_hash(code), created_at=now,
                                 expires_at=expires_at))
    await session.commit()
    log.info("telegram_link_code_issued", expires_at=expires_at.isoformat())
    return code, expires_at


class LinkResult:
    """Why a redemption did or did not work, in a form the bot can turn into
    a sentence. Deliberately not an exception: every outcome here is an
    ordinary thing a person does, including getting it wrong."""

    OK = "ok"
    ALREADY = "already"
    BAD = "bad"
    RATE_LIMITED = "rate_limited"


async def redeem(session: AsyncSession, code: str, user_id: int,
                 username: str = "", display_name: str = "") -> str:
    """Spend a code and link `user_id`. Returns a LinkResult."""
    if not limiter.allow(f"tglink:{user_id}", REDEEM_ATTEMPTS_PER_MIN):
        log.warning("telegram_link_rate_limited", user_id=user_id)
        return LinkResult.RATE_LIMITED

    now = _now()
    row = (await session.execute(
        select(TelegramLinkCode).where(
            TelegramLinkCode.code_hash == _hash(code),
            TelegramLinkCode.used_at.is_(None),
            TelegramLinkCode.expires_at > now)
    )).scalar_one_or_none()
    if row is None:
        # One answer for wrong, expired and already-spent. Telling them apart
        # would confirm that a guessed code was once real.
        log.info("telegram_link_rejected", user_id=user_id)
        return LinkResult.BAD

    row.used_at = now
    row.used_by_user_id = user_id

    existing = await session.get(TelegramOperator, user_id)
    if existing is not None:
        existing.username = username[:64]
        existing.display_name = display_name[:120]
        await session.commit()
        log.info("telegram_link_repeat", user_id=user_id)
        return LinkResult.ALREADY

    session.add(TelegramOperator(telegram_user_id=user_id,
                                 username=username[:64],
                                 display_name=display_name[:120],
                                 linked_at=now))
    await session.commit()
    log.info("telegram_operator_linked", user_id=user_id)
    return LinkResult.OK


async def is_operator(session: AsyncSession, user_id) -> bool:
    """May this account act?

    The env allowlist is kept as a break-glass path: if the console is down,
    or the last operator revoked themselves by accident, an id in `.env`
    still works. It is a second door for the person who owns the server, not
    a second way in for anyone else.
    """
    from app.services.telegram import control_user_ids

    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return False
    if uid in control_user_ids():
        return True
    return (await session.get(TelegramOperator, uid)) is not None


async def touch(session: AsyncSession, user_id: int) -> None:
    """Record that this operator did something, for the console's list."""
    row = await session.get(TelegramOperator, int(user_id))
    if row is not None:
        row.last_used_at = _now()


async def list_operators(session: AsyncSession) -> list[dict]:
    rows = (await session.execute(
        select(TelegramOperator).order_by(TelegramOperator.linked_at)
    )).scalars()
    return [{"telegram_user_id": r.telegram_user_id,
             "username": r.username,
             "display_name": r.display_name,
             "linked_at": r.linked_at,
             "last_used_at": r.last_used_at} for r in rows]


async def revoke(session: AsyncSession, user_id: int) -> bool:
    row = await session.get(TelegramOperator, int(user_id))
    if row is None:
        return False
    await session.delete(row)
    await session.commit()
    log.info("telegram_operator_revoked", user_id=user_id)
    return True
