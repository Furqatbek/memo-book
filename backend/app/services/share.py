"""Read-only share links — CR-003-1.

A travel or family book is about people who are not the buyer. Every share
goes to somebody who is literally in the photographs: the warmest audience
there is, reached at no cost. It also commits the owner — a person who has
shown three friends their half-finished book is far likelier to finish it.

THREE SEPARATE SECRETS, and the separation is the design:

    edit_token       everything. Never leaves the owner's browser.
    telegram_token   attaches a chat to a book. Spent on use.
    share_token      read-only, low resolution, revocable.

A share link gets forwarded, screenshotted and pasted into group chats.
It must therefore be incapable of doing anything but showing pages, and
losing it must cost nothing but the showing.

WHAT A VIEWER CAN REACH is page images at 144 DPI and nothing else: no
originals, no print files, no display derivatives, no contact details, and
no mutation of any kind. The images are rendered by the same code that
renders the preview the customer approved, at a different scale, so the
thing being shown off cannot drift from the thing that gets printed.
"""
import secrets
import uuid
from datetime import UTC, datetime

import anyio
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import storage
from app.models.book import Book
from app.models.photo import Photo, PhotoStatus
from app.services.books import get_book_authed
from app.services.photo_bytes import read_original

log = structlog.get_logger()

TOKEN_BYTES = 32          # the CR's requirement: 32-byte URL-safe random
# How long a viewer's image links live. Short, because the page re-mints
# them on every view and a forwarded image URL should not outlive the
# forwarded page link by much.
VIEW_URL_EXPIRY_S = 6 * 3600


def _page_key(book_id: uuid.UUID, index: int) -> str:
    return f"books/{book_id}/share/page-{index}.jpg"


def _cover_key(book_id: uuid.UUID) -> str:
    return f"books/{book_id}/share/cover.jpg"


def share_url(token: str) -> str:
    """Absolute or nothing — see `public_links`. A relative share link is
    not a degraded link; it is a piece of text somebody pastes into a
    group chat and nobody can open."""
    from app.services.public_links import absolute

    return absolute(f"/s/{token}")


async def create(session: AsyncSession, book_id: uuid.UUID,
                 edit_token: str) -> Book:
    """Mint the link, or hand back the one that already exists.

    Reused rather than rotated, so that opening the panel twice does not
    quietly invalidate a link the owner has already sent to their family.
    """
    book = await get_book_authed(session, book_id, edit_token)
    if not book.share_token:
        book.share_token = secrets.token_urlsafe(TOKEN_BYTES)
        book.share_created_at = datetime.now(UTC)
        book.share_view_count = 0
    return book


async def revoke(session: AsyncSession, book_id: uuid.UUID,
                 edit_token: str) -> Book:
    """Off means off, immediately — and the rendered images go too.

    Clearing the token alone would leave the page pictures sitting in
    storage under guessable-by-nobody keys, but present; deleting them is
    what makes "revoke" mean what the owner thinks it means.
    """
    book = await get_book_authed(session, book_id, edit_token)
    keys = [_cover_key(book.id)]
    keys += [_page_key(book.id, p["index"]) for p in book.layout.get("pages", [])]
    book.share_token = None
    book.share_created_at = None
    book.share_layout_version = None
    await anyio.to_thread.run_sync(storage.delete_keys, keys)
    log.info("share.revoked", book_id=str(book.id))
    return book


async def find(session: AsyncSession, token: str) -> Book | None:
    """The book a share token names, or None.

    None covers every failure — unknown, revoked, expired book — because
    the caller answers all of them with the same 404. A share page is not
    an oracle for which tokens exist.
    """
    if not token or len(token) > 64:
        return None
    book = (await session.execute(
        select(Book).where(Book.share_token == token)
    )).scalar_one_or_none()
    if book is None:
        return None
    if book.status == "expired":
        return None
    return book


async def render(session: AsyncSession, book: Book) -> None:
    """Draw the share images for this book's current layout.

    Memory discipline copied from the preview pipeline, deliberately: one
    page's photographs are read, composed and freed before the next page
    is touched, because a 96-page book of 25 MB originals would otherwise
    be gigabytes resident at once.
    """
    from app.render.preview import render_share_cover, render_share_page
    from app.services.cover_designs import design_artwork_bytes

    layout_version = book.layout_version
    photos = {str(p.id): p for p in (await session.execute(
        select(Photo).where(
            Photo.book_id == book.id,
            Photo.status.in_((PhotoStatus.READY.value, PhotoStatus.DUPLICATE.value)))
    )).scalars()}

    cover = book.layout.get("cover") or {}
    cover_photo = photos.get(str(cover.get("photo_id") or ""))
    cover_bytes = None
    if cover_photo is not None:
        cover_bytes = await anyio.to_thread.run_sync(
            read_original, cover_photo.original_key)
    artwork = await design_artwork_bytes(session, cover.get("design_id"))
    cover_jpeg = await anyio.to_thread.run_sync(
        render_share_cover, cover, cover_bytes, artwork)
    del cover_bytes, artwork
    await anyio.to_thread.run_sync(
        storage.put_bytes, _cover_key(book.id), cover_jpeg, "image/jpeg")
    del cover_jpeg

    for page in book.layout.get("pages", []):
        photo_bytes: dict[str, bytes] = {}
        for placement in page.get("placements", []):
            photo = photos.get(placement["photo_id"])
            if photo is not None:
                photo_bytes[placement["photo_id"]] = await anyio.to_thread.run_sync(
                    read_original, photo.original_key)
        jpeg = await anyio.to_thread.run_sync(render_share_page, page, photo_bytes)
        del photo_bytes
        await anyio.to_thread.run_sync(
            storage.put_bytes, _page_key(book.id, page["index"]), jpeg, "image/jpeg")
        del jpeg

    book.share_layout_version = layout_version
    await session.commit()
    log.info("share.rendered", book_id=str(book.id), layout_version=layout_version)


def is_stale(book: Book) -> bool:
    return book.share_layout_version != book.layout_version


async def view(session: AsyncSession, book: Book) -> dict:
    """What a viewer gets: signed links to page images, and nothing else.

    Explicitly NOT here: the owner's email or phone, the edit token, photo
    ids, originals, print artifacts, or the price. A viewer is a stranger
    the owner trusted with a picture of their book, not with their account.
    """
    pages = [
        {"index": p["index"],
         "url": storage.presign_get(_page_key(book.id, p["index"]),
                                    expires_in=VIEW_URL_EXPIRY_S)}
        for p in book.layout.get("pages", [])
    ]
    cover = book.layout.get("cover") or {}
    return {
        "title": (cover.get("title") or "").strip(),
        "subtitle": (cover.get("subtitle") or "").strip(),
        "page_count": book.page_count,
        "cover_url": storage.presign_get(_cover_key(book.id),
                                         expires_in=VIEW_URL_EXPIRY_S),
        "pages": pages,
    }


async def count_view(session: AsyncSession, book: Book) -> None:
    book.share_view_count = (book.share_view_count or 0) + 1
    await session.commit()
