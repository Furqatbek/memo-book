"""The upload path's back wall — CR-003 security groundwork.

A presigned PUT signs the bucket, the key and the content type. It does
NOT sign the length, so the size a client declares when it asks for the
URL is decorative: it can declare 1 MB and upload 5 GB. Before CR-003 this
was survivable because every upload door needed the book's edit token.
CR-003-6 adds an anonymous one, and an anonymous door onto an unbounded
path is not a feature, it is a hole.

These tests are about the shared path both doors use.
"""
import uuid

import pytest

from app.services import photos as svc
from app.services.photos import MAX_PHOTOS_PER_BOOK, MAX_UPLOAD_BYTES
from tests.api.test_books import make_book


class TestTheDeclaredSizeIsNotTrusted:
    async def test_ingest_refuses_an_object_bigger_than_the_limit(
            self, client, db, monkeypatch):
        """The declaration said it was small; storage says otherwise. The
        object is refused and deleted WITHOUT being read, because reading
        it is how the worker dies."""
        book = await make_book(client, 16)
        photo, _url = await svc.issue_upload_url(
            db, uuid.UUID(book["book_id"]), book["edit_token"],
            "big.jpg", "image/jpeg", 1024)

        read = []
        deleted = []
        monkeypatch.setattr(svc.storage, "head_size",
                            lambda key: MAX_UPLOAD_BYTES + 1)
        monkeypatch.setattr(svc.storage, "get_bytes",
                            lambda key: read.append(key) or b"")
        monkeypatch.setattr(svc.storage, "delete_key", deleted.append)

        out = await svc.ingest_photo(db, photo.id)
        assert out.status == "failed"
        assert out.error == "too_large"
        assert read == [], "the oversized object was read into memory"
        assert deleted == [photo.original_key]

    async def test_a_missing_object_fails_cleanly(self, client, db, monkeypatch):
        book = await make_book(client, 16)
        photo, _ = await svc.issue_upload_url(
            db, uuid.UUID(book["book_id"]), book["edit_token"],
            "gone.jpg", "image/jpeg", 1024)
        monkeypatch.setattr(svc.storage, "head_size", lambda key: None)
        monkeypatch.setattr(svc.storage, "delete_key", lambda key: None)
        out = await svc.ingest_photo(db, photo.id)
        assert out.status == "failed"
        assert out.error == "upload_missing"

    async def test_the_recorded_size_is_the_real_one(self, client, db, monkeypatch):
        """Not the number the client asked us to believe."""
        from tests.services.test_image_processing import jpeg_bytes

        book = await make_book(client, 16)
        photo, _ = await svc.issue_upload_url(
            db, uuid.UUID(book["book_id"]), book["edit_token"],
            "a.jpg", "image/jpeg", 999_999)
        data = jpeg_bytes()
        monkeypatch.setattr(svc.storage, "head_size", lambda key: len(data))
        monkeypatch.setattr(svc.storage, "get_bytes", lambda key: data)
        monkeypatch.setattr(svc.storage, "put_bytes",
                            lambda key, body, ct: None)
        out = await svc.ingest_photo(db, photo.id)
        assert out.status == "ready"
        assert out.bytes_original == len(data) != 999_999


class TestAFailedUploadDoesNotLinger:
    async def test_the_original_is_deleted_when_ingest_refuses_it(
            self, client, db, monkeypatch):
        """Otherwise a rejected file sits in the bucket for the book's whole
        30-day life — a month of free storage for whatever was pushed at
        us, which is exactly what an anonymous door would be used for."""
        book = await make_book(client, 16)
        photo, _ = await svc.issue_upload_url(
            db, uuid.UUID(book["book_id"]), book["edit_token"],
            "not-an-image.jpg", "image/jpeg", 1024)
        deleted = []
        monkeypatch.setattr(svc.storage, "head_size", lambda key: 12)
        monkeypatch.setattr(svc.storage, "get_bytes", lambda key: b"not an image")
        monkeypatch.setattr(svc.storage, "delete_key", deleted.append)
        out = await svc.ingest_photo(db, photo.id)
        assert out.status == "failed"
        assert deleted == [photo.original_key]


class TestABookHasACeiling:
    async def test_a_book_cannot_hold_unlimited_photos(self, client, db):
        """The back wall. Without it, every per-link cap is a fence around
        an open field."""
        from app.models.photo import Photo

        book = await make_book(client, 16)
        bid = uuid.UUID(book["book_id"])
        for _ in range(MAX_PHOTOS_PER_BOOK):
            db.add(Photo(id=uuid.uuid4(), book_id=bid, status="ready",
                         original_key="k", mime_original="image/jpeg",
                         bytes_original=1, uploaded_at=svc._now(),
                         sha256=uuid.uuid4().hex))
        await db.commit()
        with pytest.raises(Exception) as exc:
            await svc.issue_upload_url(db, bid, book["edit_token"],
                                       "one-too-many.jpg", "image/jpeg", 1024)
        assert "already holds" in str(exc.value)

    async def test_the_ceiling_is_generous_for_a_real_book(self):
        """A 96-page book uses a few hundred at most; this must never be
        the thing a real customer hits."""
        assert MAX_PHOTOS_PER_BOOK >= 500
