"""Collaborative photo upload — CR-003-6.

Your travel companion has the better photographs, and until now the only
way to get them into the book was WhatsApp, a laptop, and an afternoon.
This replaces that with a link. It also puts a contributor inside the
product before they have bought anything, which makes them the cheapest
warm lead there is.

    THIS IS THE MOST ABUSABLE ENDPOINT IN THE SYSTEM.

Unauthenticated by design: the link is the credential, it will be pasted
into a group chat, and anybody holding it can send us files. Everything
below is arranged around that single fact.

WHAT A CONTRIBUTOR CAN DO
    add photographs to one book's pool, and see how many are in it.

WHAT A CONTRIBUTOR CANNOT DO — and each of these is a test:
    see the book, its pages, its layout or its preview;
    see, place, reorder or delete anything, including their own uploads;
    see the owner's name, phone, address or email;
    reach the checkout, the price or the order;
    reach any print-resolution file.

THE CAPS, and why they are shaped this way:

    100 photos      per book, from contributors
    200 MB          per book, from contributors
    10 contributors per book

They are counted from the PHOTO ROWS, not from counter columns. A counter
is a number that can drift from what it claims to count, and this is the
one number somebody has a motive to make drift. Counting the rows cannot
be wrong about them.

The declared size on an upload request is not evidence — a presigned PUT
signs the key and the content type, never the length — so the byte cap is
checked AGAIN during ingest, against what actually landed, and a photo
that pushes the book past the ceiling is deleted rather than kept.
"""
import hashlib
import secrets
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import DomainError, ErrorCode
from app.config import get_settings
from app.domain.states import BookStatus
from app.models.book import Book
from app.models.contributor import ContributorLink
from app.models.photo import Photo
from app.services.books import get_book_authed

log = structlog.get_logger()

TOKEN_BYTES = 32
MAX_CONTRIBUTED_PHOTOS = 100
MAX_CONTRIBUTED_BYTES = 200 * 1024 * 1024
MAX_CONTRIBUTORS = 10
NAME_MAX = 60


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def contributor_id(session_id: str | None) -> str:
    """An opaque, stable id for one contributor's browser.

    Derived from the anonymous funnel session, which is the only thing we
    have: a contributor has no account and never will. It is NOT a security
    boundary — clearing a cookie produces a new one — and the contributor
    cap is therefore a courtesy limit. The caps that actually defend the
    system are the photo count and the byte ceiling, which no cookie can
    move.
    """
    return hashlib.sha256(
        f"contributor:{session_id or uuid.uuid4()}".encode()).hexdigest()[:32]


def contribute_url(token: str) -> str:
    base = (get_settings().public_base_url or "").rstrip("/")
    return f"{base}/c/{token}" if base else f"/c/{token}"


def _enabled() -> None:
    """The kill switch. An unauthenticated upload endpoint is a thing worth
    being able to switch off from an env file at three in the morning,
    without a deploy."""
    if not get_settings().contributor_links_enabled:
        raise DomainError(ErrorCode.VALIDATION_ERROR,
                          "contributor links are switched off",
                          {"setting": "CONTRIBUTOR_LINKS_ENABLED"})


async def create(session: AsyncSession, book_id: uuid.UUID,
                 edit_token: str) -> tuple[Book, str]:
    """Mint the link, or replace the one that exists.

    Returns the raw token, which is the ONLY time it exists in readable
    form anywhere in this system. If the owner loses it they mint another,
    and the old one stops working — which is also how "revoke and re-share"
    is spelled.
    """
    _enabled()
    book = await get_book_authed(session, book_id, edit_token)
    if book.status != BookStatus.DRAFT.value:
        raise DomainError(ErrorCode.BOOK_LOCKED,
                          "this book is no longer being edited",
                          {"status": book.status})
    existing = await _link_for_book(session, book_id)
    token = secrets.token_urlsafe(TOKEN_BYTES)
    if existing is None:
        session.add(ContributorLink(book_id=book_id, token_sha256=_hash(token),
                                    created_at=datetime.now(UTC)))
    else:
        existing.token_sha256 = _hash(token)
    log.info("contributor.link_created", book_id=str(book_id))
    return book, token


async def revoke(session: AsyncSession, book_id: uuid.UUID,
                 edit_token: str) -> None:
    """Off means off. The photographs contributors already sent STAY — they
    are part of the book now, and deleting somebody's holiday pictures
    because a link was turned off would be its own kind of disaster."""
    await get_book_authed(session, book_id, edit_token)
    link = await _link_for_book(session, book_id)
    if link is not None:
        await session.delete(link)
    log.info("contributor.link_revoked", book_id=str(book_id))


async def _link_for_book(session: AsyncSession,
                         book_id: uuid.UUID) -> ContributorLink | None:
    return (await session.execute(
        select(ContributorLink).where(ContributorLink.book_id == book_id)
    )).scalar_one_or_none()


async def find(session: AsyncSession, token: str) -> Book | None:
    """The book a contributor token names, or None.

    None covers unknown, revoked, expired and no-longer-a-draft, because
    the caller answers every one of them with the same 404. A contributor
    page is not an oracle for which books exist.
    """
    if not get_settings().contributor_links_enabled:
        return None
    if not token or len(token) > 128:
        return None
    link = (await session.execute(
        select(ContributorLink).where(
            ContributorLink.token_sha256 == _hash(token))
    )).scalar_one_or_none()
    if link is None:
        return None
    book = (await session.execute(
        select(Book).where(Book.id == link.book_id))).scalar_one_or_none()
    if book is None:
        return None
    # Expires with the draft: an expired book's photographs have been
    # deleted from storage, and a locked one is paid for and unchangeable.
    if book.status != BookStatus.DRAFT.value:
        return None
    return book


async def usage(session: AsyncSession, book_id: uuid.UUID) -> dict:
    """What contributors have put into this book, counted from the rows.

    `bytes_original` is the DECLARED size until ingest replaces it with
    what actually landed, so this figure is an estimate for photos still in
    flight and the truth for everything else.
    """
    row = (await session.execute(
        select(func.count(Photo.id),
               func.coalesce(func.sum(Photo.bytes_original), 0),
               func.count(func.distinct(Photo.contributed_by)))
        .where(Photo.book_id == book_id, Photo.contributed_by.is_not(None))
    )).one()
    return {"photos": int(row[0] or 0), "bytes": int(row[1] or 0),
            "contributors": int(row[2] or 0)}


async def check_quota(session: AsyncSession, book: Book, who: str,
                      declared_bytes: int) -> None:
    """Refuse the call that would exceed a cap — including the one that
    lands exactly on it.

    Raises with a message a contributor can act on. There is no point
    being coy here: the caps are not a secret, and somebody who has just
    been refused deserves to know they were refused for a reason rather
    than at random.
    """
    used = await usage(session, book.id)
    if used["photos"] >= MAX_CONTRIBUTED_PHOTOS:
        raise DomainError(
            ErrorCode.VALIDATION_ERROR,
            f"this book has reached its limit of {MAX_CONTRIBUTED_PHOTOS} "
            "contributed photos",
            {"max_photos": MAX_CONTRIBUTED_PHOTOS, "used": used["photos"]})
    if used["bytes"] + max(0, declared_bytes) > MAX_CONTRIBUTED_BYTES:
        raise DomainError(
            ErrorCode.VALIDATION_ERROR,
            "this book has reached its limit for contributed photos",
            {"max_bytes": MAX_CONTRIBUTED_BYTES, "used_bytes": used["bytes"]})

    already = (await session.execute(
        select(Photo.id).where(Photo.book_id == book.id,
                               Photo.contributed_by == who).limit(1)
    )).scalar_one_or_none()
    if already is None and used["contributors"] >= MAX_CONTRIBUTORS:
        raise DomainError(
            ErrorCode.VALIDATION_ERROR,
            f"this book already has {MAX_CONTRIBUTORS} people adding photos",
            {"max_contributors": MAX_CONTRIBUTORS})


async def over_byte_cap(session: AsyncSession, photo: Photo) -> bool:
    """Checked again at ingest, against what actually arrived.

    A presigned PUT signs the bucket, the key and the content type — never
    the length. So the size a contributor declared when they asked for the
    URL is decorative, and this is the only check that sees the real
    number. Called from the ingest path; a photo that pushes the book over
    the ceiling is deleted rather than kept.
    """
    if photo.contributed_by is None:
        return False
    total = (await session.execute(
        select(func.coalesce(func.sum(Photo.bytes_original), 0)).where(
            Photo.book_id == photo.book_id,
            Photo.contributed_by.is_not(None))
    )).scalar() or 0
    return int(total) > MAX_CONTRIBUTED_BYTES


async def public_view(session: AsyncSession, book: Book) -> dict:
    """Everything a contributor is allowed to know about the book.

    Read the list twice: it is shorter than it looks, and everything absent
    from it is absent on purpose. No pages, no layout, no photographs, no
    owner, no price, no order.
    """
    from app import storage

    cover = book.layout.get("cover") or {}
    used = await usage(session, book.id)
    thumb = None
    cover_photo_id = cover.get("photo_id")
    if cover_photo_id:
        photo = (await session.execute(
            select(Photo).where(Photo.id == uuid.UUID(str(cover_photo_id)))
        )).scalar_one_or_none()
        if photo is not None and photo.thumb_key:
            thumb = storage.presign_get(photo.thumb_key)
    return {
        "book_title": (cover.get("title") or "").strip(),
        "contributed_count": used["photos"],
        "cover_thumb": thumb,
        "photos_left": max(0, MAX_CONTRIBUTED_PHOTOS - used["photos"]),
    }


def clean_name(raw: str | None) -> str | None:
    if not raw:
        return None
    text = "".join(c for c in raw if c.isprintable()).strip()
    return text[:NAME_MAX] or None
