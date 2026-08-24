"""Milestone 5: auto-place (R2) and checkout eligibility (R1/R3) over real data."""
import uuid
from datetime import UTC, datetime, timedelta

from app.models.photo import Photo, PhotoStatus
from tests.api.test_books import auth, make_book

T0 = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)


async def seed_photo(db, book_id: str, taken_offset_h: int | None,
                     uploaded_offset_s: int, status: str = PhotoStatus.READY.value) -> str:
    photo = Photo(
        id=uuid.uuid4(),
        book_id=uuid.UUID(book_id),
        status=status,
        original_key=f"books/{book_id}/orig/x",
        mime_original="image/jpeg",
        bytes_original=1000,
        orig_width=3000,
        orig_height=2000,
        taken_at=None if taken_offset_h is None else T0 + timedelta(hours=taken_offset_h),
        uploaded_at=T0 + timedelta(seconds=uploaded_offset_s),
        sha256=uuid.uuid4().hex,
    )
    db.add(photo)
    await db.commit()
    return str(photo.id)


async def do_auto_place(client, book, version=1):
    return await client.post(f"/api/v1/books/{book['book_id']}/auto-place",
                             headers={**auth(book), "If-Match": str(version)})


async def get_eligibility(client, book):
    resp = await client.get(f"/api/v1/books/{book['book_id']}/checkout-eligibility",
                            headers=auth(book))
    assert resp.status_code == 200
    return resp.json()


def placed_ids(layout: dict) -> list[str]:
    out = []
    for page in layout["pages"]:
        if page["placements"]:
            out.append(page["placements"][0]["photo_id"])
    return out


class TestAutoPlace:
    async def test_chronological_order_full_bleed(self, client, db):
        book = await make_book(client, 16)
        # Uploaded in reverse chronological order — taken_at must win.
        late = await seed_photo(db, book["book_id"], taken_offset_h=10, uploaded_offset_s=1)
        early = await seed_photo(db, book["book_id"], taken_offset_h=1, uploaded_offset_s=2)
        middle = await seed_photo(db, book["book_id"], taken_offset_h=5, uploaded_offset_s=3)

        resp = await do_auto_place(client, book)
        assert resp.status_code == 200
        body = resp.json()
        assert body["placed_count"] == 3
        assert placed_ids(body["layout"]) == [early, middle, late]

        first = body["layout"]["pages"][0]["placements"][0]
        assert (first["x_mm"], first["y_mm"]) == (-3.0, -3.0)
        assert (first["w_mm"], first["h_mm"]) == (154.0, 216.0)
        assert first["fit"] == "cover"
        # Pages beyond the photo count stay empty.
        assert body["layout"]["pages"][3]["placements"] == []
        assert body["layout_version"] == 2

    async def test_undated_photos_after_dated(self, client, db):
        book = await make_book(client, 16)
        undated_late = await seed_photo(db, book["book_id"], None, uploaded_offset_s=50)
        dated = await seed_photo(db, book["book_id"], taken_offset_h=2, uploaded_offset_s=99)
        undated_early = await seed_photo(db, book["book_id"], None, uploaded_offset_s=10)

        body = (await do_auto_place(client, book)).json()
        assert placed_ids(body["layout"]) == [dated, undated_early, undated_late]

    async def test_deterministic_across_runs(self, client, db):
        book = await make_book(client, 16)
        for i in range(6):
            await seed_photo(db, book["book_id"],
                             taken_offset_h=(i * 7) % 5, uploaded_offset_s=100 - i)
        first = (await do_auto_place(client, book, version=1)).json()
        second = (await do_auto_place(client, book, version=2)).json()
        assert placed_ids(first["layout"]) == placed_ids(second["layout"])

    async def test_surplus_photos_surfaced_not_dropped(self, client, db):
        book = await make_book(client, 16)
        ids = [await seed_photo(db, book["book_id"], taken_offset_h=i, uploaded_offset_s=i)
               for i in range(18)]
        body = (await do_auto_place(client, book)).json()
        assert body["placed_count"] == 16
        assert placed_ids(body["layout"]) == ids[:16]
        assert body["unplaced_photo_ids"] == ids[16:]  # R3: surfaced

    async def test_preserves_texts_and_cover(self, client, db):
        book = await make_book(client, 16)
        layout = book["layout"]
        layout["cover"]["title"] = "Italy 2026"
        layout["pages"][0]["texts"] = [{
            "id": "t1", "x_mm": 12, "y_mm": 180, "w_mm": 124, "h_mm": 18,
            "content": "Amalfi coast",
        }]
        patched = await client.patch(f"/api/v1/books/{book['book_id']}/layout",
                                     json=layout, headers={**auth(book), "If-Match": "1"})
        assert patched.status_code == 200
        await seed_photo(db, book["book_id"], taken_offset_h=1, uploaded_offset_s=1)

        body = (await do_auto_place(client, book, version=2)).json()
        assert body["layout"]["cover"]["title"] == "Italy 2026"
        assert body["layout"]["pages"][0]["texts"][0]["content"] == "Amalfi coast"
        assert len(body["layout"]["pages"][0]["placements"]) == 1

    async def test_ignores_failed_and_processing_photos(self, client, db):
        book = await make_book(client, 16)
        ready = await seed_photo(db, book["book_id"], 1, 1)
        await seed_photo(db, book["book_id"], 2, 2, status=PhotoStatus.FAILED.value)
        await seed_photo(db, book["book_id"], 3, 3, status=PhotoStatus.PROCESSING.value)
        body = (await do_auto_place(client, book)).json()
        assert placed_ids(body["layout"]) == [ready]

    async def test_requires_if_match(self, client, db):
        book = await make_book(client, 16)
        resp = await client.post(f"/api/v1/books/{book['book_id']}/auto-place",
                                 headers=auth(book))
        assert resp.status_code == 428

    async def test_stale_version_conflicts(self, client, db):
        book = await make_book(client, 16)
        await seed_photo(db, book["book_id"], 1, 1)
        assert (await do_auto_place(client, book, version=1)).status_code == 200
        assert (await do_auto_place(client, book, version=1)).status_code == 409


class TestEligibility:
    async def test_shortfall_blocks_with_details(self, client, db):
        book = await make_book(client, 16)
        for i in range(10):
            await seed_photo(db, book["book_id"], i, i)
        body = await get_eligibility(client, book)
        assert body["eligible"] is False
        assert (body["photo_count"], body["page_count"]) == (10, 16)
        issue = body["issues"][0]
        assert issue["code"] == "PHOTOS_INSUFFICIENT"
        assert issue["details"] == {"have": 10, "empty_pages": 16,
                                    "unplaced_photos": 10, "shortfall": 6}
        assert body["suggested_tier"] is None

    async def test_exact_count_eligible(self, client, db):
        book = await make_book(client, 16)
        for i in range(16):
            await seed_photo(db, book["book_id"], i, i)
        body = await get_eligibility(client, book)
        assert body["eligible"] is True
        assert body["issues"] == []
        assert body["suggested_tier"] is None

    async def test_surplus_suggests_next_tier(self, client, db):
        book = await make_book(client, 16)
        for i in range(20):
            await seed_photo(db, book["book_id"], i, i)
        body = await get_eligibility(client, book)
        assert body["eligible"] is True
        assert body["suggested_tier"] == 32

    async def test_unusable_photos_do_not_count(self, client, db):
        book = await make_book(client, 16)
        for i in range(16):
            await seed_photo(db, book["book_id"], i, i)
        await seed_photo(db, book["book_id"], 99, 99, status=PhotoStatus.FAILED.value)
        await seed_photo(db, book["book_id"], 98, 98, status=PhotoStatus.PENDING.value)
        body = await get_eligibility(client, book)
        assert body["photo_count"] == 16

    async def test_duplicates_count_as_placeable(self, client, db):
        book = await make_book(client, 16)
        for i in range(15):
            await seed_photo(db, book["book_id"], i, i)
        await seed_photo(db, book["book_id"], 15, 15, status=PhotoStatus.DUPLICATE.value)
        body = await get_eligibility(client, book)
        assert body["photo_count"] == 16
        assert body["eligible"] is True
