"""Telegram as a recovery channel for a customer's own book — Change 2.

Distinct from `telegram_link`, which is the OPERATOR side: that decides who
may move orders, and it is a two-sided secret. This is the customer side —
somebody who started a book and would like to be reminded about it
somewhere they actually read. The two share a bot and a webhook and nothing
else, which is why they use different commands: an operator redeems a code
with `/link`, a customer taps a deep link that sends `/start <token>`.

THE TOKEN IS NOT THE EDIT TOKEN, and that is the whole security design of
this feature. A deep link travels through Telegram's servers, sits in a
chat list, and gets forwarded; the edit token is the only thing standing
between a stranger and somebody's photographs. So a book gets a second,
single-purpose secret that can do exactly one thing — attach a chat id to
a book — and expires. Leaking it costs the customer unwanted reminders,
not their book.

One chat may hold several books. A person who makes a book for their
mother and another for a wedding is one Telegram account and two books, so
the chat id is an ordinary nullable column on `books`, never a unique
constraint.
"""
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.book import Book
from app.models.telegram import TelegramUpdate

log = structlog.get_logger()

# Long enough that a link pasted into a chat still works tomorrow, short
# enough that one left in a forwarded message does not work for ever.
TOKEN_TTL = timedelta(days=14)
TOKEN_BYTES = 24

# How a recovered draft is labelled wherever it is counted.
REMINDER_SOURCE = "reminder"
REMINDER_MEDIUM = "lifecycle"
REMINDER_CAMPAIGN = "draft_recovery"


def reminder_query(day: int) -> str:
    """The query string every reminder link carries, wherever it is built.

    One place, because the relative fallback used when PUBLIC_BASE_URL is
    unset has to carry the same tags — a link missing them is a recovered
    order that cannot be told from new traffic, which is the one thing
    these tags exist for.
    """
    return (f"?r={day}&utm_source={REMINDER_SOURCE}"
            f"&utm_medium={REMINDER_MEDIUM}&utm_campaign={REMINDER_CAMPAIGN}")


def bot_username() -> str:
    return (get_settings().telegram_bot_username or "").lstrip("@")


def configured() -> bool:
    """A deep link needs a bot to point at. Without the username there is
    nothing to offer, and offering a broken link is worse than offering
    nothing — a customer who taps it and lands nowhere has learned that
    this product does not work."""
    return bool(bot_username() and get_settings().telegram_bot_token)


async def issue_token(session: AsyncSession, book: Book) -> str:
    """The token for this book, minted on first ask and reused until it
    expires — so a customer who opens the panel twice gets one link, not a
    trail of live secrets."""
    now = datetime.now(UTC)
    expires = book.telegram_token_expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if book.telegram_token and expires and expires > now:
        return book.telegram_token
    book.telegram_token = secrets.token_urlsafe(TOKEN_BYTES)
    book.telegram_token_expires_at = now + TOKEN_TTL
    return book.telegram_token


def deep_link(token: str) -> str:
    return f"https://t.me/{bot_username()}?start={token}"


async def link_chat(session: AsyncSession, token: str,
                    chat_id: int) -> Book | None:
    """Attach a chat to the book its token names. None if it means nothing.

    An unknown or expired token is an ordinary outcome, not an error: links
    get forwarded, and somebody else's copy of one should be answered
    politely rather than with a stack trace.
    """
    if not token:
        return None
    book = (await session.execute(
        select(Book).where(Book.telegram_token == token)
    )).scalar_one_or_none()
    if book is None:
        return None
    expires = book.telegram_token_expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if expires is None or expires <= datetime.now(UTC):
        return None

    book.telegram_chat_id = chat_id
    book.telegram_linked_at = datetime.now(UTC)
    # Spent on use. The chat is attached now, so the secret has no further
    # job and a forwarded copy of the link stops working.
    book.telegram_token = None
    book.telegram_token_expires_at = None
    log.info("telegram_recovery_linked", book_id=str(book.id))
    return book


async def unlink_chat(session: AsyncSession, chat_id: int) -> int:
    """`/stop`: this chat hears nothing more, about any book.

    Every book, not just the most recent one. Somebody who asks to be left
    alone has not asked to be left alone about one of their three books,
    and a partial stop is the kind of thing that gets a bot reported.
    """
    books = (await session.execute(
        select(Book).where(Book.telegram_chat_id == chat_id)
    )).scalars().all()
    for book in books:
        book.telegram_chat_id = None
        book.telegram_linked_at = None
    log.info("telegram_recovery_stopped", chats=1, books=len(books))
    return len(books)


async def already_seen(session: AsyncSession, update_id: int | None) -> bool:
    """Telegram retries until it gets a 200, and a retry must not act twice.

    Recorded in its own table rather than inferred from the effect, because
    the effects differ: a repeated `/start` would re-link harmlessly, but a
    repeated command that sends a message would send it twice, and the
    customer sees the duplicate.
    """
    if update_id is None:
        return False
    try:
        # The row is added INSIDE the savepoint, not before it. Added
        # outside, a duplicate leaves the object pending on the outer
        # session and the collision deactivates the caller's transaction —
        # which is the very failure the savepoint is here to prevent.
        async with session.begin_nested():
            session.add(TelegramUpdate(update_id=int(update_id),
                                       received_at=datetime.now(UTC)))
            await session.flush()
        return False
    except Exception:  # noqa: BLE001 — a duplicate primary key, nothing worse
        log.debug("telegram_update_replayed", update_id=update_id)
        return True


async def books_for_chat(session: AsyncSession, chat_id: int) -> list[Book]:
    return list((await session.execute(
        select(Book).where(Book.telegram_chat_id == chat_id)
    )).scalars())


def editor_url(book_id: uuid.UUID, day: int | None = None) -> str:
    """An absolute link, or nothing.

    A relative path is fine inside the editor and useless the moment it
    leaves: "/editor/abc" is not clickable in a Telegram message. With no
    base configured this returns "" and the caller sends a message with no
    link, which is better than a message with a broken one.
    """
    base = (get_settings().public_base_url or "").rstrip("/")
    if not base:
        return ""
    url = f"{base}/editor/{book_id}"
    if not day:
        return url
    # `r` is ours, for telling a day-3 click from a day-25 one. The utm
    # pair is there so the link reads honestly in anybody else's analytics
    # too — but it is NOT what attributes the recovery: see the note on
    # REMINDER_CLICKED in app/api/events.py. First touch still owns the
    # acquisition, or a reminder would quietly steal credit for a sale the
    # original campaign paid to win (Change 4).
    return url + reminder_query(day)
