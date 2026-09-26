"""Photo service: presigned upload issuance, ingest orchestration, listing,
deletion. Uploads go direct to object storage (never through the API);
the ingest job runs in a worker (or inline when TASK_EAGER is set).

Everything here that changes what the book is made of runs through
`_require_mutable` first. Nothing did, for a long time: deleting a photo is
the most destructive edit in the product — the row AND the object go — and it
was the one mutation with no gate at all. A customer still holding their edit
link could empty a book that was locked, paid and mid-render, and the file is
not recoverable afterwards (A80).
"""
import uuid
from copy import deepcopy
from datetime import UTC, datetime

import anyio
import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import storage
from app.domain.errors import DomainError, ErrorCode
from app.domain.geometry import CANVAS_H_MM, CANVAS_W_MM
from app.domain.resolution import resolution_status
from app.models.book import Book
from app.models.photo import Photo, PhotoStatus
from app.services.books import _require_mutable, get_book_authed
from app.services.image_processing import IngestError, process_image

log = structlog.get_logger()

# DNG is here because a phone shooting ProRAW, or anyone exporting from
# Lightroom, produces one — and refusing it used to mean a red card with no
# reason on it. What we actually print is the full-size preview the camera
# rendered into the file, which is both what the customer saw and the only
# thing in there we can decode without a raw processor (A103).
ALLOWED_MIMES = {"image/jpeg", "image/png", "image/heic", "image/heif",
                 "image/x-adobe-dng"}
# The browser downscales before uploading, so real uploads land far below
# this; the ceiling only has to accommodate the untouched-original fallback
# (HEIC on browsers that cannot decode it) and block abuse.
MAX_UPLOAD_BYTES = 60 * 1024 * 1024
# How many photographs one book may hold. A 96-page book uses at most a few
# hundred; this is generous for any real customer and is the back wall
# behind every other upload limit — without it, "100 photos per contributor
# link" is a fence with nothing behind it, and the owner path itself is
# unbounded (CR-003).
MAX_PHOTOS_PER_BOOK = 600


def _now() -> datetime:
    return datetime.now(UTC)


def _photo_not_found() -> DomainError:
    return DomainError(ErrorCode.NOT_FOUND, "photo not found")


async def _get_photo(session: AsyncSession, book: Book, photo_id: uuid.UUID) -> Photo:
    result = await session.execute(
        select(Photo).where(Photo.id == photo_id, Photo.book_id == book.id)
    )
    photo = result.scalar_one_or_none()
    if photo is None:
        raise _photo_not_found()
    return photo


async def issue_upload_url(session: AsyncSession, book_id: uuid.UUID, edit_token: str,
                           filename: str, mime: str,
                           size_bytes: int) -> tuple[Photo, dict]:
    book = await get_book_authed(session, book_id, edit_token)
    return await _issue_for_book(book, session, mime, size_bytes)


async def issue_contributor_upload_url(
        session: AsyncSession, book: Book, who: str, contributor_name: str | None,
        mime: str, size_bytes: int) -> tuple[Photo, dict]:
    """The same upload, for somebody holding only a contributor link.

    IDENTICAL validation to the owner's path — same MIME allow-list, same
    ceiling, same book cap — because a contributor's file goes through the
    same ingest and ends up in the same printed book. The contributor caps
    are an EXTRA fence on top, checked first so the commonest refusal is
    the one with the useful message.

    The book's REMAINING contributor allowance is then baked into the
    upload policy, so a contributor cannot spend more of it than they were
    granted even by ignoring the size they declared. That is the whole
    reason this path is worth the extra argument.
    """
    from app.services import contribute

    await contribute.check_quota(session, book, who, size_bytes)
    used = await contribute.usage(session, book.id)
    remaining = max(1, contribute.MAX_CONTRIBUTED_BYTES - used["bytes"])
    return await _issue_for_book(book, session, mime, size_bytes,
                                 contributed_by=who,
                                 contributor_name=contributor_name,
                                 policy_max_bytes=remaining)


async def _issue_for_book(book: Book, session: AsyncSession, mime: str,
                          size_bytes: int, *, contributed_by: str | None = None,
                          contributor_name: str | None = None,
                          policy_max_bytes: int | None = None
                          ) -> tuple[Photo, dict]:
    _require_mutable(book)
    if mime not in ALLOWED_MIMES:
        raise DomainError(ErrorCode.VALIDATION_ERROR,
                          f"unsupported content type {mime}",
                          {"allowed": sorted(ALLOWED_MIMES)})
    if size_bytes <= 0 or size_bytes > MAX_UPLOAD_BYTES:
        raise DomainError(ErrorCode.VALIDATION_ERROR,
                          f"file size must be 1..{MAX_UPLOAD_BYTES} bytes",
                          {"bytes": size_bytes, "max": MAX_UPLOAD_BYTES})

    held = (await session.execute(
        select(func.count()).select_from(Photo).where(Photo.book_id == book.id)
    )).scalar() or 0
    if held >= MAX_PHOTOS_PER_BOOK:
        raise DomainError(ErrorCode.VALIDATION_ERROR,
                          f"this book already holds {held} photos",
                          {"max": MAX_PHOTOS_PER_BOOK})

    photo_id = uuid.uuid4()
    photo = Photo(
        id=photo_id,
        book_id=book.id,
        status=PhotoStatus.PENDING.value,
        original_key=f"books/{book.id}/orig/{photo_id}",
        mime_original=mime,
        bytes_original=size_bytes,
        uploaded_at=_now(),
        contributed_by=contributed_by,
        contributor_name=contributor_name,
    )
    session.add(photo)
    await session.commit()

    # The cap the STORAGE SERVICE will enforce, before any byte lands. The
    # declared size is not it: a client that lied about the size is exactly
    # the case this exists for. Whichever ceiling is lower applies — the
    # global one, or what is left of a contributor's allowance.
    ceiling = MAX_UPLOAD_BYTES
    if policy_max_bytes is not None:
        ceiling = min(ceiling, policy_max_bytes)
    upload = await anyio.to_thread.run_sync(
        storage.presign_post, photo.original_key, mime, ceiling
    )
    return photo, upload


async def complete_upload(session: AsyncSession, book_id: uuid.UUID, edit_token: str,
                          photo_id: uuid.UUID,
                          taken_at_exif: str | None = None) -> Photo:
    book = await get_book_authed(session, book_id, edit_token)
    return await _complete_for_book(session, book, photo_id, taken_at_exif)


async def complete_contributor_upload(session: AsyncSession, book: Book, who: str,
                                      photo_id: uuid.UUID,
                                      taken_at_exif: str | None = None) -> Photo:
    """Finish a contributor's upload — and ONLY their own.

    The `contributed_by` check is what stops a contributor link being used
    to touch the owner's photographs, or another contributor's. Without it,
    a token that can only add pictures could still reach in and complete —
    or, worse, later be extended into anything else that takes a photo id.
    """
    photo = await _get_photo(session, book, photo_id)
    if photo.contributed_by != who:
        raise _photo_not_found()
    return await _complete_for_book(session, book, photo_id, taken_at_exif)


async def _complete_for_book(session: AsyncSession, book: Book,
                             photo_id: uuid.UUID,
                             taken_at_exif: str | None = None) -> Photo:
    _require_mutable(book)
    photo = await _get_photo(session, book, photo_id)
    if taken_at_exif:
        # Browser-downscaled uploads carry no EXIF; the client forwards the
        # original capture time so date ordering (R2) still works. Parsed by
        # the SAME helper the server-side EXIF path uses, so semantics match.
        from app.services.image_processing import _parse_exif_datetime

        photo.taken_at = _parse_exif_datetime(taken_at_exif) or photo.taken_at
    if photo.status not in (PhotoStatus.PENDING.value, PhotoStatus.FAILED.value):
        return photo  # idempotent: completing twice is harmless

    exists = await anyio.to_thread.run_sync(storage.object_exists, photo.original_key)
    if not exists:
        raise DomainError(ErrorCode.VALIDATION_ERROR,
                          "no uploaded object found for this photo",
                          {"photo_id": str(photo_id)})

    photo.status = PhotoStatus.PROCESSING.value
    await session.commit()
    return photo


async def ingest_photo(session: AsyncSession, photo_id: uuid.UUID) -> Photo:
    """The ingest job body (spec Part 6). Runs in a worker; also called inline
    in eager mode. Failures land in status=failed with a reason, never raise."""
    result = await session.execute(select(Photo).where(Photo.id == photo_id))
    photo = result.scalar_one()

    try:
        # What is ACTUALLY there, before anything reads it into memory.
        #
        # A presigned PUT signs bucket, key and content type — not length —
        # so `bytes_original` is only what the client SAID it would upload.
        # Without this check a 5 GB body against a 1 MB declaration is read
        # straight into the worker's RAM, and the way that ends is the
        # worker dying rather than the upload being refused.
        actual = await anyio.to_thread.run_sync(
            storage.head_size, photo.original_key)
        if actual is None:
            raise IngestError("upload_missing", "no object at the upload key")
        if actual > MAX_UPLOAD_BYTES:
            # Deleted by the IngestError handler below, which is the one
            # place that cleans up a refused upload.
            raise IngestError(
                "too_large",
                f"uploaded {actual} bytes, over the {MAX_UPLOAD_BYTES} limit")
        photo.bytes_original = actual
        # The contributor byte ceiling, checked against what ACTUALLY
        # arrived rather than what was declared (CR-003-6). The declaration
        # is not evidence — a presigned PUT does not sign the length — so a
        # contributor can promise 1 MB and send sixty. This is the check
        # that sees the real number, and it runs before the bytes are read
        # into memory.
        if photo.contributed_by is not None:
            from app.services.contribute import (
                MAX_CONTRIBUTED_BYTES,
                over_byte_cap,
            )

            if await over_byte_cap(session, photo):
                raise IngestError(
                    "quota_exceeded",
                    "this book has reached its limit for contributed photos "
                    f"({MAX_CONTRIBUTED_BYTES // (1024 * 1024)} MB)")
        data = await anyio.to_thread.run_sync(storage.get_bytes, photo.original_key)
        processed = await anyio.to_thread.run_sync(process_image, data)

        display_key = f"books/{photo.book_id}/display/{photo.id}.jpg"
        thumb_key = f"books/{photo.book_id}/thumb/{photo.id}.jpg"
        await anyio.to_thread.run_sync(
            storage.put_bytes, display_key, processed.display_jpeg, "image/jpeg"
        )
        await anyio.to_thread.run_sync(
            storage.put_bytes, thumb_key, processed.thumb_jpeg, "image/jpeg"
        )

        photo.display_key = display_key
        photo.thumb_key = thumb_key
        photo.orig_width = processed.width
        photo.orig_height = processed.height
        photo.taken_at = processed.taken_at or photo.taken_at
        photo.exif_orientation = 1  # R4: rotation applied physically
        photo.sha256 = processed.sha256
        photo.bytes_original = len(data)
        photo.error = None

        duplicate = (await session.execute(
            select(Photo).where(
                Photo.book_id == photo.book_id,
                Photo.sha256 == processed.sha256,
                Photo.id != photo.id,
                Photo.status.in_([PhotoStatus.READY.value, PhotoStatus.DUPLICATE.value]),
            ).order_by(Photo.uploaded_at)
        )).scalars().first()

        if duplicate is not None:
            photo.status = PhotoStatus.DUPLICATE.value
            photo.duplicate_of = duplicate.id
        else:
            photo.status = PhotoStatus.READY.value

        await session.commit()
        log.info("photo.ingested", photo_id=str(photo.id), book_id=str(photo.book_id),
                 status=photo.status, width=photo.orig_width, height=photo.orig_height,
                 taken_at=str(photo.taken_at))
    except IngestError as exc:
        # The original is no use to anyone now, and leaving it until the
        # book expires is a month of free storage for whatever was pushed
        # at us. Derivatives were never written, so there is nothing else
        # to clean up.
        await anyio.to_thread.run_sync(storage.delete_key, photo.original_key)
        photo.status = PhotoStatus.FAILED.value
        # The CODE, not the prose. This column is read by the editor, which
        # has to say what went wrong in one of five languages; the English
        # sentence goes to the log, where English is the right language
        # (A103).
        photo.error = exc.code
        await session.commit()
        log.warning("photo.ingest_failed", photo_id=str(photo.id),
                    code=exc.code, reason=exc.reason)
    return photo


async def list_photos(session: AsyncSession, book_id: uuid.UUID,
                      edit_token: str) -> list[Photo]:
    book = await get_book_authed(session, book_id, edit_token)
    result = await session.execute(
        select(Photo).where(Photo.book_id == book.id).order_by(Photo.uploaded_at)
    )
    return list(result.scalars())


def _forget_photo(book: Book, photo_id: str) -> bool:
    """Strip every reference to this photo out of the book's layout."""
    layout = deepcopy(book.layout)
    changed = False
    for page in layout.get("pages") or []:
        placements = page.get("placements") or []
        kept = [pl for pl in placements if pl.get("photo_id") != photo_id]
        if len(kept) != len(placements):
            page["placements"] = kept
            changed = True
    cover = layout.get("cover") or {}
    if cover.get("photo_id") == photo_id:
        cover["photo_id"] = None
        changed = True
    if changed:
        # Assigning a NEW dict, not mutating the old one: SQLAlchemy compares
        # by identity for a JSON column, so an in-place edit commits as a
        # silent no-op.
        book.layout = layout
        book.layout_version += 1
        book.updated_at = _now()
    return changed


async def delete_photo(session: AsyncSession, book_id: uuid.UUID, edit_token: str,
                       photo_id: uuid.UUID) -> None:
    """Remove a photo, and every placement of it, in one transaction.

    Cleaning the layout is the server's job, not the editor's. The editor
    does tidy up and autosave, so the invariant held for exactly as long as
    that request landed — and stopped the moment it did not. A layout
    pointing at a photo that no longer exists refuses checkout with
    PAGES_INCOMPLETE, and the page it blames still has a placement on it, so
    it does not read as empty and the customer has nowhere to go (A80).
    """
    book = await get_book_authed(session, book_id, edit_token)
    _require_mutable(book)
    photo = await _get_photo(session, book, photo_id)
    keys = [photo.original_key, photo.display_key, photo.thumb_key]
    await session.delete(photo)
    _forget_photo(book, str(photo_id))
    await session.commit()
    # Objects go after the commit, as in the expiry job: a crash between the
    # two leaves a re-runnable delete, never a live layout with missing bytes.
    await anyio.to_thread.run_sync(storage.delete_keys, keys)


def serialize_photo(photo: Photo) -> dict:
    res_status = None
    if photo.orig_width and photo.orig_height:
        # Badge for the default full-bleed placement; the editor recomputes
        # per actual placed size via the domain thresholds.
        res_status = resolution_status(
            photo.orig_width, photo.orig_height, CANVAS_W_MM, CANVAS_H_MM
        )
    return {
        "photo_id": photo.id,
        "status": photo.status,
        "error": photo.error,
        "width": photo.orig_width,
        "height": photo.orig_height,
        "mime_original": photo.mime_original,
        "bytes_original": photo.bytes_original,
        "taken_at": photo.taken_at,
        "uploaded_at": photo.uploaded_at,
        "resolution_status": res_status,
        "duplicate_of": photo.duplicate_of,
        # Flagged so the owner can tell whose pictures are whose (CR-003-6),
        # and delete any of them. The opaque contributor id stays on the
        # server; the owner gets the name the contributor typed, or nothing.
        "contributed": photo.contributed_by is not None,
        "contributor_name": photo.contributor_name,
        "display_url": storage.presign_get(photo.display_key) if photo.display_key else None,
        "thumb_url": storage.presign_get(photo.thumb_key) if photo.thumb_key else None,
    }
