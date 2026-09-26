"""Making and delivering the flip video — CR-003-5.

The constraint this feature exists to answer is no content and no budget.
A customer who has just been told their book is printing is at the peak of
their excitement about it, and a vertical video of their own pages turning
is the one thing they will post without being asked. Every order becomes a
piece of content, and nobody had to make it.

THE RULE THAT OUTRANKS EVERYTHING ELSE HERE: a video failure must never
delay, fail or alter an order. Every entry point below catches everything
and answers False. An order is a printed book somebody paid for; this is a
nicety, and the two must never be able to touch.

Memory discipline copied from the print pipeline: pages are rendered one at
a time, and each composed frame is handed to ffmpeg and dropped.
"""
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta

import anyio
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import storage
from app.config import get_settings
from app.models.book import Book
from app.models.flip_video import FlipVideo
from app.models.order import Order
from app.models.photo import Photo, PhotoStatus

log = structlog.get_logger()

TOKEN_BYTES = 24
# The CR asks for a link that works for thirty days. Those thirty days live
# in the TOKEN, not in a signature: SigV4 refuses a presigned URL longer
# than seven days outright, so a 30-day one is not a long link, it is a
# 400 from the storage service at the moment the customer taps it.
#
# `/v/{token}` signs a fresh URL on every visit, which is why the token can
# outlive any signature — and why the redirect is 302 with no-store rather
# than something a cache could keep. This is the lifetime of the URL that
# redirect hands out, and it only has to survive the download.
URL_EXPIRY_S = 6 * 3600
# How long the token itself stays good. The CR's thirty days.
TOKEN_LIFETIME_DAYS = 30
# The CR's ceiling. Exceeding it is not an error — it is a sign the encode
# settings drifted, and it is worth a loud line in the log rather than a
# silent 30MB file somebody tries to send over mobile data.
TARGET_MAX_BYTES = 8 * 1024 * 1024


def _key(order_id: uuid.UUID) -> str:
    return f"orders/{order_id}/flip.mp4"


def video_url(token: str) -> str:
    """Absolute or nothing — see `public_links`."""
    from app.services.public_links import absolute

    return absolute(f"/v/{token}")


async def existing(session: AsyncSession, order_id: uuid.UUID) -> FlipVideo | None:
    return (await session.execute(
        select(FlipVideo).where(FlipVideo.order_id == order_id)
    )).scalar_one_or_none()


async def _page_jpegs(session: AsyncSession, book: Book,
                      limit: int) -> list[bytes]:
    """Cover first, then pages, each rendered and kept as a JPEG.

    JPEGs rather than decoded images: twenty 1080x1920 RGB frames would be
    125MB resident, and the whole point of holding them is to hand them to
    the encoder one at a time.
    """
    from app.render.preview import render_share_cover, render_share_page
    from app.services.cover_designs import design_artwork_bytes
    from app.services.photo_bytes import read_original

    photos = {str(p.id): p for p in (await session.execute(
        select(Photo).where(
            Photo.book_id == book.id,
            Photo.status.in_((PhotoStatus.READY.value,
                              PhotoStatus.DUPLICATE.value)))
    )).scalars()}

    out: list[bytes] = []
    cover = book.layout.get("cover") or {}
    cover_photo = photos.get(str(cover.get("photo_id") or ""))
    cover_bytes = None
    if cover_photo is not None:
        cover_bytes = await anyio.to_thread.run_sync(
            read_original, cover_photo.original_key)
    artwork = await design_artwork_bytes(session, cover.get("design_id"))
    out.append(await anyio.to_thread.run_sync(
        render_share_cover, cover, cover_bytes, artwork))
    del cover_bytes, artwork

    for page in book.layout.get("pages", []):
        if len(out) >= limit:
            break
        photo_bytes: dict[str, bytes] = {}
        for placement in page.get("placements", []):
            photo = photos.get(placement["photo_id"])
            if photo is not None:
                photo_bytes[placement["photo_id"]] = await anyio.to_thread.run_sync(
                    read_original, photo.original_key)
        out.append(await anyio.to_thread.run_sync(
            render_share_page, page, photo_bytes))
        del photo_bytes
    return out


async def generate(session: AsyncSession, order_id: uuid.UUID) -> bool:
    """Make the video for this order. Returns whether one now exists.

    Catches everything. The caller is a background job whose only other
    option is to let an exception escape into an order's lifecycle, which
    is precisely what must not happen.
    """
    from app.render.flip import MAX_PAGES, duration_s

    settings = get_settings()
    if not settings.flip_video_enabled:
        return False

    order = (await session.execute(
        select(Order).where(Order.id == order_id))).scalar_one_or_none()
    if order is None:
        return False
    if await existing(session, order_id) is not None:
        return True                      # idempotent: the job may be retried

    started = time.monotonic()
    try:
        book = (await session.execute(
            select(Book).where(Book.id == order.book_id))).scalar_one()
        pages = await _page_jpegs(session, book, MAX_PAGES)
        data = await anyio.to_thread.run_sync(_encode, pages)
        shown = len(pages)
        del pages
    except Exception as exc:  # noqa: BLE001 — job boundary, see the docstring
        log.warning("flip_video.failed", order=order.human_ref,
                    error=str(exc)[:300])
        return False

    key = _key(order_id)
    try:
        await anyio.to_thread.run_sync(storage.put_bytes, key, data, "video/mp4")
    except Exception as exc:  # noqa: BLE001 — job boundary
        log.warning("flip_video.upload_failed", order=order.human_ref,
                    error=str(exc)[:300])
        return False

    render_ms = int((time.monotonic() - started) * 1000)
    if len(data) > TARGET_MAX_BYTES:
        # Not a failure — the customer still gets their video. But the
        # encode settings have drifted, and somebody should know before a
        # customer tries to send this over mobile data.
        log.warning("flip_video.over_budget", order=order.human_ref,
                    bytes=len(data), budget=TARGET_MAX_BYTES)

    session.add(FlipVideo(
        order_id=order_id, token=secrets.token_urlsafe(TOKEN_BYTES),
        storage_key=key, size_bytes=len(data),
        duration_ms=int(duration_s(shown) * 1000),
        page_count=shown, render_ms=render_ms,
        download_count=0, created_at=datetime.now(UTC)))
    await session.commit()
    log.info("flip_video.generated", order=order.human_ref, bytes=len(data),
             pages=shown, render_ms=render_ms)

    from app.domain.events import EventType
    from app.services import funnel

    await funnel.emit_for_book(session, EventType.FLIP_VIDEO_GENERATED,
                               order.book_id,
                               properties={"bytes": len(data),
                                           "pages": shown,
                                           "render_ms": render_ms})
    await session.commit()

    await _announce(session, order_id)
    return True


def _encode(pages: list[bytes]) -> bytes:
    from app.render.flip import encode

    return encode(pages)


async def _announce(session: AsyncSession, order_id: uuid.UUID) -> None:
    """Tell the customer it exists, down whichever channel they use.

    Telegram gets the FILE, not a link: a video that plays where it lands
    is one people forward, and a link is one more tap between the customer
    and posting it. Email gets the link, because email cannot do better.
    """
    from app.services import outbox

    video = await existing(session, order_id)
    order = (await session.execute(
        select(Order).where(Order.id == order_id))).scalar_one()
    book = (await session.execute(
        select(Book).where(Book.id == order.book_id))).scalar_one()
    if video is None:
        return

    if book.telegram_chat_id is not None:
        outbox.enqueue(session, outbox.TOPIC_FLIP_VIDEO_TG, {
            "order_id": str(order_id),
            "chat_id": book.telegram_chat_id,
            "video_key": video.storage_key,
            "text": VIDEO_MESSAGE,
        })
    elif order.customer_email:
        outbox.enqueue(session, outbox.TOPIC_ORDER_PROGRESS, {
            "order_id": str(order_id),
            "email": order.customer_email,
            "human_ref": order.human_ref,
            "status": "flip_video",
            "text": f"{VIDEO_MESSAGE}\n\n{video_url(video.token)}",
        })
    else:
        return
    await session.commit()


# Said plainly, and it asks for nothing. The one thing people will not post
# is something that reads like it was written to be posted.
VIDEO_MESSAGE = (
    "Your book, page by page — a short video of it, yours to keep.\n"
    "Post it wherever you like.")


async def find(session: AsyncSession, token: str,
               now: datetime | None = None) -> FlipVideo | None:
    """The video a token names, or None — including when it has aged out.

    The CR's thirty days are enforced HERE, because this is the only place
    the token is exchanged for anything. Declaring the lifetime in a
    constant and never checking it would make the constant a comment.
    """
    if not token or len(token) > 64:
        return None
    video = (await session.execute(
        select(FlipVideo).where(FlipVideo.token == token)
    )).scalar_one_or_none()
    if video is None:
        return None
    created = video.created_at
    if created.tzinfo is None:          # SQLite hands these back naive
        created = created.replace(tzinfo=UTC)
    if (now or datetime.now(UTC)) - created > timedelta(
            days=TOKEN_LIFETIME_DAYS):
        return None
    return video


async def count_download(session: AsyncSession, video: FlipVideo) -> None:
    video.download_count = (video.download_count or 0) + 1
    await session.commit()
