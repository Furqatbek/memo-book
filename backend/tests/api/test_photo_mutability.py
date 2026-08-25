"""A80: a book that has been paid for cannot have its photos taken away.

`app/services/photos.py` had no mutability check of any kind. Every other
layout mutation runs through `_require_mutable` — `books.py` opens with a
docstring saying so, and `checkout` tells the customer in as many words that
"after payment the book cannot be edited".

Deleting a photo is the most destructive edit in the product and it skipped
that gate entirely. A customer still holding their edit link could, on a book
that was locked, paid and mid-render, delete a photo: the row and the bytes
both go. The render then fails preflight, the order lands in `render_failed`,
and the photo is not coming back — the object is gone from storage.

Uploading to a locked book is gated too, for the same reason the promise is
worth keeping: a book someone has paid for is finished.
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.domain.states import BookStatus
from app.models.book import Book
from app.models.photo import Photo
from tests.api.test_checkout import do_checkout, ready_book


async def a_photo_of(db, book_id: str) -> Photo:
    return (await db.execute(
        select(Photo).where(Photo.book_id == uuid.UUID(book_id))
    )).scalars().first()


async def set_status(db, book_id: str, status: BookStatus) -> None:
    row = (await db.execute(
        select(Book).where(Book.id == uuid.UUID(book_id)))).scalar_one()
    row.status = status.value
    await db.commit()


class TestAPaidBookKeepsItsPhotos:
    async def test_deleting_is_refused_once_the_book_is_locked(
            self, client, db):
        book_id, headers = await ready_book(client, db)
        photo = await a_photo_of(db, book_id)
        await set_status(db, book_id, BookStatus.LOCKED)

        resp = await client.delete(
            f"/api/v1/books/{book_id}/photos/{photo.id}", headers=headers)
        assert resp.status_code == 423
        assert resp.json()["error"]["code"] == "BOOK_LOCKED"

    async def test_and_once_it_is_ordered(self, client, db):
        book_id, headers = await ready_book(client, db)
        photo = await a_photo_of(db, book_id)
        await set_status(db, book_id, BookStatus.ORDERED)

        resp = await client.delete(
            f"/api/v1/books/{book_id}/photos/{photo.id}", headers=headers)
        assert resp.status_code == 423

    async def test_the_photo_and_its_bytes_survive_the_refusal(
            self, client, db):
        """A refusal that had already deleted the object would be the same
        disaster with a different status code."""
        book_id, headers = await ready_book(client, db)
        photo = await a_photo_of(db, book_id)
        key = photo.original_key
        await set_status(db, book_id, BookStatus.ORDERED)

        await client.delete(f"/api/v1/books/{book_id}/photos/{photo.id}",
                            headers=headers)

        from app import storage
        assert await a_photo_of(db, book_id) is not None
        assert storage.get_bytes(key), "the object was deleted anyway"

    async def test_the_real_sequence_that_broke_it(self, client, db):
        """Checkout, then delete. This is the path a customer could actually
        walk: they have the edit link, the order is placed, and the book is
        supposed to be frozen."""
        book_id, headers = await ready_book(client, db)
        photo = await a_photo_of(db, book_id)
        assert (await do_checkout(client, book_id, headers)).status_code == 201

        resp = await client.delete(
            f"/api/v1/books/{book_id}/photos/{photo.id}", headers=headers)
        assert resp.status_code == 423, (
            "a checked-out book let its photos be deleted — the render would "
            "fail preflight and the file is unrecoverable")


class TestUploadingToAFinishedBook:
    async def test_upload_urls_are_refused(self, client, db):
        book_id, headers = await ready_book(client, db)
        await set_status(db, book_id, BookStatus.ORDERED)

        resp = await client.post(
            f"/api/v1/books/{book_id}/photos/upload-url",
            json={"filename": "a.jpg", "mime": "image/jpeg", "bytes": 1000},
            headers=headers)
        assert resp.status_code == 423


class TestADraftIsUnaffected:
    async def test_deleting_from_a_draft_still_works(self, client, db):
        """The gate must not cost the customer the ordinary case."""
        book_id, headers = await ready_book(client, db)
        photo = await a_photo_of(db, book_id)

        resp = await client.delete(
            f"/api/v1/books/{book_id}/photos/{photo.id}", headers=headers)
        assert resp.status_code == 204, resp.text
        assert (await db.execute(select(Photo).where(
            Photo.id == photo.id))).scalar_one_or_none() is None

    async def test_uploading_to_a_draft_still_works(self, client, db):
        book_id, headers = await ready_book(client, db)
        resp = await client.post(
            f"/api/v1/books/{book_id}/photos/upload-url",
            json={"filename": "a.jpg", "mime": "image/jpeg", "bytes": 1000},
            headers=headers)
        assert resp.status_code == 200, resp.text

    async def test_a_cancelled_order_unlocks_it_again(self, client, db):
        """A6: a cancelled payment returns the book to draft, and the
        customer must get their photos back under their control with it."""
        book_id, headers = await ready_book(client, db)
        photo = await a_photo_of(db, book_id)
        await do_checkout(client, book_id, headers)

        from app.models.order import Order
        from app.services.orders import cancel_order
        order = (await db.execute(select(Order).where(
            Order.book_id == uuid.UUID(book_id)))).scalar_one()
        await cancel_order(db, order.id, note="test")

        resp = await client.delete(
            f"/api/v1/books/{book_id}/photos/{photo.id}", headers=headers)
        assert resp.status_code == 204, resp.text


class TestTheLayoutNeverPointsAtNothing:
    """The other half of A80. Deleting the row and leaving the layout
    referencing it produced a book that could not be checked out and could
    not be repaired: PAGES_INCOMPLETE names a page that still has a
    placement on it, so it does not read as empty and the editor's
    "go to the first empty page" lands somewhere else entirely."""

    async def test_the_placement_goes_with_the_photo(self, client, db):
        book_id, headers = await ready_book(client, db)
        photo = await a_photo_of(db, book_id)

        before = (await client.get(f"/api/v1/books/{book_id}",
                                   headers=headers)).json()["layout"]
        assert any(pl["photo_id"] == str(photo.id)
                   for p in before["pages"] for pl in p["placements"])

        assert (await client.delete(
            f"/api/v1/books/{book_id}/photos/{photo.id}",
            headers=headers)).status_code == 204

        after = (await client.get(f"/api/v1/books/{book_id}",
                                  headers=headers)).json()["layout"]
        assert not any(pl["photo_id"] == str(photo.id)
                       for p in after["pages"] for pl in p["placements"]), (
            "the layout still points at a photo that no longer exists")

    async def test_the_page_becomes_genuinely_empty(self, client, db):
        """Not "has a placement pointing at nothing" — empty, so the editor
        can find it and the customer can fill it."""
        book_id, headers = await ready_book(client, db)
        photo = await a_photo_of(db, book_id)
        await client.delete(f"/api/v1/books/{book_id}/photos/{photo.id}",
                            headers=headers)

        layout = (await client.get(f"/api/v1/books/{book_id}",
                                   headers=headers)).json()["layout"]
        assert any(not p["placements"] for p in layout["pages"])

    async def test_the_version_moves_so_an_open_editor_notices(
            self, client, db):
        """An editor with the old layout in hand must lose its If-Match race
        rather than saving the deleted photo back."""
        book_id, headers = await ready_book(client, db)
        book = (await client.get(f"/api/v1/books/{book_id}",
                                 headers=headers)).json()
        photo = await a_photo_of(db, book_id)

        await client.delete(f"/api/v1/books/{book_id}/photos/{photo.id}",
                            headers=headers)

        stale = await client.patch(
            f"/api/v1/books/{book_id}/layout", json=book["layout"],
            headers={**headers, "If-Match": str(book["layout_version"])})
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "VERSION_CONFLICT"

    async def test_a_cover_photo_is_forgotten_too(self, client, db):
        book_id, headers = await ready_book(client, db)
        photo = await a_photo_of(db, book_id)
        book = (await client.get(f"/api/v1/books/{book_id}",
                                 headers=headers)).json()
        layout = book["layout"]
        layout["cover"]["photo_id"] = str(photo.id)
        saved = await client.patch(
            f"/api/v1/books/{book_id}/layout", json=layout,
            headers={**headers, "If-Match": str(book["layout_version"])})
        assert saved.status_code == 200, saved.text

        await client.delete(f"/api/v1/books/{book_id}/photos/{photo.id}",
                            headers=headers)

        after = (await client.get(f"/api/v1/books/{book_id}",
                                  headers=headers)).json()["layout"]
        assert after["cover"]["photo_id"] is None

    async def test_deleting_an_unplaced_photo_leaves_the_layout_alone(
            self, client, db):
        """No version bump for a photo nothing referenced — otherwise every
        tray tidy-up costs an open editor its next save."""
        book_id, headers = await ready_book(client, db)
        book = (await client.get(f"/api/v1/books/{book_id}",
                                 headers=headers)).json()
        version = book["layout_version"]

        from app.models.photo import PhotoStatus
        spare = Photo(id=uuid.uuid4(), book_id=uuid.UUID(book_id),
                      status=PhotoStatus.READY.value,
                      original_key=f"books/{book_id}/orig/spare",
                      mime_original="image/jpeg", bytes_original=1,
                      orig_width=100, orig_height=100,
                      uploaded_at=datetime.now(UTC))
        db.add(spare)
        await db.commit()

        assert (await client.delete(
            f"/api/v1/books/{book_id}/photos/{spare.id}",
            headers=headers)).status_code == 204

        after = (await client.get(f"/api/v1/books/{book_id}",
                                  headers=headers)).json()
        assert after["layout_version"] == version
