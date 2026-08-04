"""Milestone 4 API tests: presigned upload flow, ingest, dedupe, delete."""
import anyio

from app import storage
from tests.api.test_books import auth, make_book
from tests.services.test_image_processing import build_exif, heic_bytes, jpeg_bytes

TWENTY_SIX_MB = 26 * 1024 * 1024


async def start_upload(client, book, filename="trip.jpg", mime="image/jpeg", size=1000):
    resp = await client.post(
        f"/api/v1/books/{book['book_id']}/photos/upload-url",
        json={"filename": filename, "mime": mime, "bytes": size},
        headers=auth(book),
    )
    return resp


async def upload_photo(client, book, data: bytes, mime="image/jpeg"):
    """The full client flow: issue URL, put bytes to storage, complete."""
    issued = (await start_upload(client, book, mime=mime, size=len(data))).json()
    await anyio.to_thread.run_sync(storage.put_bytes, issued["storage_key"], data, mime)
    done = await client.post(
        f"/api/v1/books/{book['book_id']}/photos/{issued['photo_id']}/complete",
        headers=auth(book),
    )
    assert done.status_code == 200
    assert done.json() == {"status": "processing"}
    return issued["photo_id"]


async def photo_list(client, book):
    resp = await client.get(f"/api/v1/books/{book['book_id']}/photos", headers=auth(book))
    assert resp.status_code == 200
    return resp.json()["photos"]


class TestUploadUrl:
    async def test_presigned_url_issued(self, client):
        book = await make_book(client)
        resp = await start_upload(client, book)
        assert resp.status_code == 200
        body = resp.json()
        assert body["upload_url"].startswith("http")
        assert body["storage_key"].endswith(body["photo_id"])

    async def test_unsupported_mime_rejected(self, client):
        book = await make_book(client)
        resp = await start_upload(client, book, mime="application/pdf")
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    async def test_oversize_rejected(self, client):
        book = await make_book(client)
        resp = await start_upload(client, book, size=TWENTY_SIX_MB)
        assert resp.status_code == 422

    async def test_complete_without_upload_rejected(self, client):
        book = await make_book(client)
        issued = (await start_upload(client, book)).json()
        resp = await client.post(
            f"/api/v1/books/{book['book_id']}/photos/{issued['photo_id']}/complete",
            headers=auth(book),
        )
        assert resp.status_code == 422


class TestIngestFlow:
    async def test_jpeg_end_to_end(self, client):
        book = await make_book(client)
        pid = await upload_photo(client, book, jpeg_bytes(3000, 2000))
        [photo] = await photo_list(client, book)
        assert photo["photo_id"] == pid
        assert photo["status"] == "ready"
        assert (photo["width"], photo["height"]) == (3000, 2000)
        assert photo["resolution_status"] == "ok"
        assert photo["display_url"] and photo["thumb_url"]

    async def test_heic_taken_at_survives(self, client):
        book = await make_book(client)
        await upload_photo(client, book, heic_bytes(), mime="image/heic")
        [photo] = await photo_list(client, book)
        assert photo["status"] == "ready"
        assert photo["taken_at"] is not None  # R5 at the API level

    async def test_rotated_exif_stored_post_rotation(self, client):
        book = await make_book(client)
        await upload_photo(client, book, jpeg_bytes(400, 200, exif=build_exif(orientation=6)))
        [photo] = await photo_list(client, book)
        assert (photo["width"], photo["height"]) == (200, 400)

    async def test_low_resolution_flagged(self, client):
        book = await make_book(client)
        await upload_photo(client, book, jpeg_bytes(700, 900))
        [photo] = await photo_list(client, book)
        assert photo["status"] == "ready"
        assert photo["resolution_status"] == "block"  # <800px can't fill a page

    async def test_corrupt_upload_fails_cleanly(self, client):
        book = await make_book(client)
        await upload_photo(client, book, b"not an image at all" * 50)
        [photo] = await photo_list(client, book)
        assert photo["status"] == "failed"
        assert "not a valid image" in photo["error"]

    async def test_duplicate_detected_within_book(self, client):
        book = await make_book(client)
        data = jpeg_bytes(1200, 900)
        first = await upload_photo(client, book, data)
        second = await upload_photo(client, book, data)
        photos = {p["photo_id"]: p for p in await photo_list(client, book)}
        assert photos[first]["status"] == "ready"
        assert photos[second]["status"] == "duplicate"
        assert photos[second]["duplicate_of"] == first

    async def test_same_file_in_other_book_is_not_duplicate(self, client):
        data = jpeg_bytes(1200, 900)
        book_a = await make_book(client)
        book_b = await make_book(client)
        await upload_photo(client, book_a, data)
        await upload_photo(client, book_b, data)
        [photo_b] = await photo_list(client, book_b)
        assert photo_b["status"] == "ready"


class TestDelete:
    async def test_delete_removes_row_and_objects(self, client):
        book = await make_book(client)
        pid = await upload_photo(client, book, jpeg_bytes())
        assert len(await photo_list(client, book)) == 1
        key_exists = await anyio.to_thread.run_sync(
            storage.object_exists, f"books/{book['book_id']}/display/{pid}.jpg"
        )
        assert key_exists

        resp = await client.delete(f"/api/v1/books/{book['book_id']}/photos/{pid}",
                                   headers=auth(book))
        assert resp.status_code == 204
        assert await photo_list(client, book) == []
        still_there = await anyio.to_thread.run_sync(
            storage.object_exists, f"books/{book['book_id']}/display/{pid}.jpg"
        )
        assert not still_there


class TestBookIncludesPhotos:
    async def test_get_book_lists_photos(self, client):
        book = await make_book(client)
        pid = await upload_photo(client, book, jpeg_bytes())
        resp = await client.get(f"/api/v1/books/{book['book_id']}", headers=auth(book))
        photos = resp.json()["photos"]
        assert len(photos) == 1
        assert photos[0]["photo_id"] == pid
