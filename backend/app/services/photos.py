"""Photo service: presigned upload issuance, ingest orchestration, listing,
deletion. Uploads go direct to object storage (never through the API);
the ingest job runs in a worker (or inline when TASK_EAGER is set)."""
import uuid
from datetime import UTC, datetime

import anyio
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import storage
from app.domain.errors import DomainError, ErrorCode
from app.domain.geometry import CANVAS_H_MM, CANVAS_W_MM
from app.domain.resolution import resolution_status
from app.models.book import Book
from app.models.photo import Photo, PhotoStatus
from app.services.books import get_book_authed
from app.services.image_processing import IngestError, process_image

log = structlog.get_logger()

ALLOWED_MIMES = {"image/jpeg", "image/png", "image/heic", "image/heif"}
# The browser downscales before uploading, so real uploads land far below
# this; the ceiling only has to accommodate the untouched-original fallback
# (HEIC on browsers that cannot decode it) and block abuse.
MAX_UPLOAD_BYTES = 60 * 1024 * 1024


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
                           filename: str, mime: str, size_bytes: int) -> tuple[Photo, str]:
    book = await get_book_authed(session, book_id, edit_token)
    if mime not in ALLOWED_MIMES:
        raise DomainError(ErrorCode.VALIDATION_ERROR,
                          f"unsupported content type {mime}",
                          {"allowed": sorted(ALLOWED_MIMES)})
    if size_bytes <= 0 or size_bytes > MAX_UPLOAD_BYTES:
        raise DomainError(ErrorCode.VALIDATION_ERROR,
                          f"file size must be 1..{MAX_UPLOAD_BYTES} bytes",
                          {"bytes": size_bytes, "max": MAX_UPLOAD_BYTES})

    photo_id = uuid.uuid4()
    photo = Photo(
        id=photo_id,
        book_id=book.id,
        status=PhotoStatus.PENDING.value,
        original_key=f"books/{book.id}/orig/{photo_id}",
        mime_original=mime,
        bytes_original=size_bytes,
        uploaded_at=_now(),
    )
    session.add(photo)
    await session.commit()

    upload_url = await anyio.to_thread.run_sync(
        storage.presign_put, photo.original_key, mime
    )
    return photo, upload_url


async def complete_upload(session: AsyncSession, book_id: uuid.UUID, edit_token: str,
                          photo_id: uuid.UUID,
                          taken_at_exif: str | None = None) -> Photo:
    book = await get_book_authed(session, book_id, edit_token)
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
        photo.status = PhotoStatus.FAILED.value
        photo.error = exc.reason
        await session.commit()
        log.warning("photo.ingest_failed", photo_id=str(photo.id), reason=exc.reason)
    return photo


async def list_photos(session: AsyncSession, book_id: uuid.UUID,
                      edit_token: str) -> list[Photo]:
    book = await get_book_authed(session, book_id, edit_token)
    result = await session.execute(
        select(Photo).where(Photo.book_id == book.id).order_by(Photo.uploaded_at)
    )
    return list(result.scalars())


async def delete_photo(session: AsyncSession, book_id: uuid.UUID, edit_token: str,
                       photo_id: uuid.UUID) -> None:
    book = await get_book_authed(session, book_id, edit_token)
    photo = await _get_photo(session, book, photo_id)
    keys = [photo.original_key, photo.display_key, photo.thumb_key]
    await session.delete(photo)
    await session.commit()
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
        "display_url": storage.presign_get(photo.display_key) if photo.display_key else None,
        "thumb_url": storage.presign_get(photo.thumb_key) if photo.thumb_key else None,
    }
