"""Milestone 3: books CRUD, JSONB layout, optimistic concurrency, edit tokens.
Covers the 'Layout concurrency' block of spec Part 9.2."""
import uuid

from sqlalchemy import select

from app.domain.states import BookStatus
from app.models.book import Book


async def make_book(client, page_count=16):
    resp = await client.post("/api/v1/books", json={"page_count": page_count})
    assert resp.status_code == 201, resp.text
    return resp.json()


def auth(book):
    return {"X-Edit-Token": book["edit_token"]}


class TestCreate:
    async def test_create_returns_token_and_empty_layout(self, client):
        book = await make_book(client, 16)
        assert uuid.UUID(book["book_id"])
        assert len(book["edit_token"]) >= 43  # 32 url-safe bytes
        assert book["status"] == "draft"
        assert book["layout_version"] == 1
        assert len(book["layout"]["pages"]) == 16
        assert all(p["placements"] == [] for p in book["layout"]["pages"])
        assert book["photos"] == []

    async def test_invalid_tier_rejected_with_envelope(self, client):
        resp = await client.post("/api/v1/books", json={"page_count": 20})
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "INVALID_PAGE_TIER"


class TestAuth:
    async def test_get_with_token(self, client):
        book = await make_book(client)
        resp = await client.get(f"/api/v1/books/{book['book_id']}", headers=auth(book))
        assert resp.status_code == 200
        assert resp.json()["book_id"] == book["book_id"]

    async def test_wrong_token_indistinguishable_from_missing(self, client):
        book = await make_book(client)
        wrong = await client.get(f"/api/v1/books/{book['book_id']}",
                                 headers={"X-Edit-Token": "nope"})
        missing = await client.get(f"/api/v1/books/{uuid.uuid4()}",
                                   headers={"X-Edit-Token": book['edit_token']})
        assert wrong.status_code == missing.status_code == 404
        assert wrong.json() == missing.json()


def layout_with_text(book, x_mm=1.0):
    layout = book["layout"]
    layout["pages"][0]["texts"] = [{
        "id": "t1", "x_mm": x_mm, "y_mm": 50, "w_mm": 30, "h_mm": 10,
        "content": "Amalfi coast",
    }]
    return layout


class TestLayoutPatch:
    async def test_patch_applies_and_increments_version(self, client):
        book = await make_book(client)
        resp = await client.patch(
            f"/api/v1/books/{book['book_id']}/layout",
            json=layout_with_text(book, x_mm=10),
            headers={**auth(book), "If-Match": "1"},
        )
        assert resp.status_code == 200
        assert resp.json()["layout_version"] == 2

    async def test_stale_version_conflicts_with_current_layout(self, client):
        book = await make_book(client)
        first = await client.patch(f"/api/v1/books/{book['book_id']}/layout",
                                   json=layout_with_text(book, x_mm=10),
                                   headers={**auth(book), "If-Match": "1"})
        assert first.status_code == 200

        second = await client.patch(f"/api/v1/books/{book['book_id']}/layout",
                                    json=layout_with_text(book, x_mm=20),
                                    headers={**auth(book), "If-Match": "1"})
        assert second.status_code == 409
        body = second.json()["error"]
        assert body["code"] == "VERSION_CONFLICT"
        assert body["details"]["current_version"] == 2
        # The current layout comes back so the client can reconcile.
        assert body["details"]["layout"]["pages"][0]["texts"][0]["x_mm"] == 10

    async def test_sequential_patches_both_apply(self, client):
        book = await make_book(client)
        r1 = await client.patch(f"/api/v1/books/{book['book_id']}/layout",
                                json=layout_with_text(book, x_mm=10),
                                headers={**auth(book), "If-Match": "1"})
        r2 = await client.patch(f"/api/v1/books/{book['book_id']}/layout",
                                json=layout_with_text(book, x_mm=20),
                                headers={**auth(book), "If-Match": "2"})
        assert r1.json()["layout_version"] == 2
        assert r2.json()["layout_version"] == 3

    async def test_missing_if_match_is_precondition_required(self, client):
        book = await make_book(client)
        resp = await client.patch(f"/api/v1/books/{book['book_id']}/layout",
                                  json=book["layout"], headers=auth(book))
        assert resp.status_code == 428
        assert resp.json()["error"]["code"] == "VERSION_REQUIRED"

    async def test_text_near_edge_is_clamped_on_save(self, client):
        book = await make_book(client)
        resp = await client.patch(f"/api/v1/books/{book['book_id']}/layout",
                                  json=layout_with_text(book, x_mm=1.0),
                                  headers={**auth(book), "If-Match": "1"})
        assert resp.status_code == 200
        saved = resp.json()["layout"]["pages"][0]["texts"][0]
        assert saved["x_mm"] == 5.0  # silently clamped to the safe area

    async def test_placement_outside_canvas_rejected(self, client):
        book = await make_book(client)
        layout = book["layout"]
        layout["pages"][0]["placements"] = [{
            "photo_id": str(uuid.uuid4()),
            # Vertically off the page: horizontal overhang is legal now that
            # a photo may cross the fold (A62), but this never can be.
            "x_mm": 10, "y_mm": 190, "w_mm": 100, "h_mm": 100,
        }]
        resp = await client.patch(f"/api/v1/books/{book['book_id']}/layout",
                                  json=layout, headers={**auth(book), "If-Match": "1"})
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "INVALID_PLACEMENT"

        # Nothing was saved and the version did not move.
        current = await client.get(f"/api/v1/books/{book['book_id']}", headers=auth(book))
        assert current.json()["layout_version"] == 1
        assert current.json()["layout"]["pages"][0]["placements"] == []

    async def test_multi_photo_pages_accepted(self, client):
        """Page layouts put several photos on one page (the list seam that
        was always in the schema); the cap is the largest layout's slots."""
        from app.domain.layouts import LAYOUTS

        book = await make_book(client)
        layout = book["layout"]
        layout["pages"][0]["layout"] = "four"
        layout["pages"][0]["placements"] = [
            {"photo_id": str(uuid.uuid4()), **slot} for slot in LAYOUTS["four"]
        ]
        resp = await client.patch(f"/api/v1/books/{book['book_id']}/layout",
                                  json=layout, headers={**auth(book), "If-Match": "1"})
        assert resp.status_code == 200, resp.text
        assert len(resp.json()["layout"]["pages"][0]["placements"]) == 4

    async def test_more_photos_than_slots_rejected(self, client):
        from app.domain.layouts import LAYOUTS, MAX_PLACEMENTS_PER_PAGE

        book = await make_book(client)
        layout = book["layout"]
        slot = LAYOUTS["four"][0]
        layout["pages"][0]["placements"] = [
            {"photo_id": str(uuid.uuid4()), **slot}
            for _ in range(MAX_PLACEMENTS_PER_PAGE + 1)
        ]
        resp = await client.patch(f"/api/v1/books/{book['book_id']}/layout",
                                  json=layout, headers={**auth(book), "If-Match": "1"})
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"

    async def test_wrong_page_count_rejected(self, client):
        book = await make_book(client, 16)
        layout = book["layout"]
        layout["pages"] = layout["pages"][:8]
        resp = await client.patch(f"/api/v1/books/{book['book_id']}/layout",
                                  json=layout, headers={**auth(book), "If-Match": "1"})
        assert resp.status_code == 422
        assert resp.json()["error"]["details"] == {"have": 8, "need": 16}

    async def test_patch_on_locked_book_is_423(self, client, db):
        book = await make_book(client)
        row = (await db.execute(
            select(Book).where(Book.id == uuid.UUID(book["book_id"]))
        )).scalar_one()
        row.status = BookStatus.LOCKED.value
        await db.commit()

        resp = await client.patch(f"/api/v1/books/{book['book_id']}/layout",
                                  json=layout_with_text(book, x_mm=10),
                                  headers={**auth(book), "If-Match": "1"})
        assert resp.status_code == 423
        assert resp.json()["error"]["code"] == "BOOK_LOCKED"

    async def test_layout_mutation_extends_retention(self, client):
        book = await make_book(client)
        before = book["expires_at"]
        resp = await client.patch(f"/api/v1/books/{book['book_id']}/layout",
                                  json=layout_with_text(book, x_mm=10),
                                  headers={**auth(book), "If-Match": "1"})
        assert resp.status_code == 200
        after = (await client.get(f"/api/v1/books/{book['book_id']}",
                                  headers=auth(book))).json()["expires_at"]
        assert after >= before  # R6: extended to now + 30 days


class TestPageCount:
    async def test_grow_appends_empty_pages(self, client):
        book = await make_book(client, 16)
        resp = await client.patch(f"/api/v1/books/{book['book_id']}/page-count",
                                  json={"page_count": 32},
                                  headers={**auth(book), "If-Match": "1"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["page_count"] == 32
        assert len(body["layout"]["pages"]) == 32
        assert body["warnings"] == []
        assert [p["index"] for p in body["layout"]["pages"]] == list(range(32))

    async def test_shrink_warns_about_truncated_content(self, client):
        book = await make_book(client, 32)
        layout = book["layout"]
        layout["pages"][20]["placements"] = [
            {"photo_id": str(uuid.uuid4()), "x_mm": 0, "y_mm": 0, "w_mm": 100, "h_mm": 100}
        ]
        patched = await client.patch(f"/api/v1/books/{book['book_id']}/layout",
                                     json=layout, headers={**auth(book), "If-Match": "1"})
        assert patched.status_code == 200

        resp = await client.patch(f"/api/v1/books/{book['book_id']}/page-count",
                                  json={"page_count": 16},
                                  headers={**auth(book), "If-Match": "2"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["page_count"] == 16
        assert len(body["layout"]["pages"]) == 16
        assert len(body["warnings"]) == 1
        assert "1 placed photos" in body["warnings"][0]

    async def test_same_tier_is_noop(self, client):
        book = await make_book(client, 16)
        resp = await client.patch(f"/api/v1/books/{book['book_id']}/page-count",
                                  json={"page_count": 16},
                                  headers={**auth(book), "If-Match": "1"})
        assert resp.status_code == 200
        assert resp.json()["layout_version"] == 1  # nothing changed

    async def test_invalid_tier_rejected(self, client):
        book = await make_book(client)
        resp = await client.patch(f"/api/v1/books/{book['book_id']}/page-count",
                                  json={"page_count": 24},
                                  headers={**auth(book), "If-Match": "1"})
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "INVALID_PAGE_TIER"


class TestEmail:
    async def test_set_email(self, client):
        book = await make_book(client)
        resp = await client.patch(f"/api/v1/books/{book['book_id']}/email",
                                  json={"email": "traveller@example.com"},
                                  headers=auth(book))
        assert resp.status_code == 200
        assert resp.json()["email"] == "traveller@example.com"

    async def test_invalid_email_rejected(self, client):
        book = await make_book(client)
        resp = await client.patch(f"/api/v1/books/{book['book_id']}/email",
                                  json={"email": "not-an-email"}, headers=auth(book))
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
